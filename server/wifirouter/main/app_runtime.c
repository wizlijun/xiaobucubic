/* Native event loop corresponding to main.lua: one-second lifecycle tick,
   asynchronous HTTP, server-anchored time, preserved cache and 5..300s retry. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "driver/i2c_master.h"
#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_spiffs.h"
#include "esp_timer.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "app_runtime.h"
#include "app_ui.h"
#include "board.h"
#include "display_geometry.h"
#include "ft6336_touch.h"

static const char *TAG = "ap24_app";
static app_view_t *view;
static QueueHandle_t request_queue, response_queue;
static nvs_handle_t cache;
static bool cache_ready;
static char status_json[1536] = "{\"state\":\"starting\"}";
static portMUX_TYPE status_lock = portMUX_INITIALIZER_UNLOCKED;
typedef struct { uint32_t id; } request_t;
typedef struct { uint32_t id; int code; char *body; size_t size; } response_t;
static i2c_master_dev_handle_t touch;
static bool pressed;
static int start_x, start_y, last_x, last_y;
static int64_t press_time;

static int64_t mono(void) { return esp_timer_get_time() / 1000000; }
static int64_t now(void) { return view->server_epoch ? view->server_epoch + mono() - view->received_mono : 0; }
static bool link_up(void)
{
    esp_netif_t *wan = esp_netif_get_handle_from_ifkey("USB_WAN");
    esp_netif_ip_info_t ip = {0};
    return wan && esp_netif_is_netif_up(wan) && esp_netif_get_ip_info(wan, &ip) == ESP_OK && ip.ip.addr;
}
static void sync_messages(void)
{
    view->active_count = app_active_messages(view->snapshot, now(), view->active);
    int selected = -1;
    char key[340];
    for (int i = 0; i < view->active_count; ++i) {
        const app_message_t *m = &view->snapshot->messages[view->active[i]];
        if (m->id[0]) snprintf(key, sizeof(key), "%s", m->id); else snprintf(key, sizeof(key), "index:%d", i + 1);
        if (!strcmp(key, view->message_key)) { selected = i; break; }
    }
    if (selected >= 0) view->message = selected;
    else if (view->message >= view->active_count) view->message = view->active_count ? view->active_count - 1 : 0;
    key[0] = 0;
    if (view->active_count) {
        const app_message_t *m = &view->snapshot->messages[view->active[view->message]];
        if (m->id[0]) snprintf(key, sizeof(key), "%s", m->id); else snprintf(key, sizeof(key), "index:%d", view->message + 1);
    }
    snprintf(view->message_key, sizeof(view->message_key), "%s", key);
    if (view->quota_page >= app_quota_pages(view->snapshot)) view->quota_page = app_quota_pages(view->snapshot) - 1;
    if (!view->active_count) view->page = 0;
}
static void render(void) { sync_messages(); app_ui_render(view, now()); }
static void fail(const char *message)
{
    view->busy = false; view->failures++;
    int exponent = view->failures > 7 ? 6 : view->failures - 1;
    int delay = 5 * (1 << exponent); if (delay > 300) delay = 300;
    view->retry_at = mono() + delay; view->error = message;
    view->connection = view->snapshot ? "离线缓存" : "未连接";
    render();
}
static void refresh(bool force)
{
    if (!view->alive || view->busy) return;
    if (!view->api_url[0]) { view->connection = "待配置"; render(); return; }
    if (!force && (view->retry_at ? mono() < view->retry_at : view->tick - view->last_fetch < view->refresh_seconds)) return;
    if (!link_up()) { fail("USB 网络未连接"); return; }
    view->busy = true; view->last_fetch = view->tick; view->request_id++; view->polls++;
    request_t request = {.id = view->request_id};
    if (xQueueSend(request_queue, &request, 0) != pdTRUE) fail("网络接口不可用");
}
static void http_worker(void *arg)
{
    request_t request;
    while (xQueueReceive(request_queue, &request, portMAX_DELAY)) {
        response_t response = {.id = request.id, .code = -1};
        esp_http_client_config_t config = {
            .url = view->api_url, .timeout_ms = 10000, .disable_auto_redirect = true,
            .crt_bundle_attach = esp_crt_bundle_attach, .buffer_size = 2048,
        };
        esp_http_client_handle_t client = esp_http_client_init(&config);
        if (client) {
            esp_http_client_set_header(client, "Accept", "application/json");
            char authorization[530];
            if (view->read_token[0]) {
                snprintf(authorization, sizeof(authorization), "Bearer %s", view->read_token);
                esp_http_client_set_header(client, "Authorization", authorization);
            }
            int64_t deadline = esp_timer_get_time() + 10000000;
            if (esp_http_client_open(client, 0) == ESP_OK) {
                int64_t length = esp_http_client_fetch_headers(client);
                int code = esp_http_client_get_status_code(client);
                if (code != 200) response.code = code;
                else if (length >= 0 && length <= APP_BODY_LIMIT) {
                    response.body = heap_caps_malloc(APP_BODY_LIMIT + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
                    if (response.body) {
                        bool valid = true;
                        while (!esp_http_client_is_complete_data_received(client)) {
                            if (response.size == APP_BODY_LIMIT || esp_timer_get_time() >= deadline) { valid = false; break; }
                            int n = esp_http_client_read(client, response.body + response.size, APP_BODY_LIMIT - response.size);
                            if (n < 0) { valid = false; break; }
                            if (n == 0) { valid = esp_http_client_is_complete_data_received(client); break; }
                            response.size += n;
                        }
                        response.body[response.size] = 0;
                        if (valid && (!length || length == response.size)) response.code = 200;
                    }
                }
            }
            esp_http_client_cleanup(client);
        }
        xQueueSend(response_queue, &response, portMAX_DELAY);
    }
}
static bool accept_body(const char *raw, size_t size, bool live)
{
    cJSON *doc = size <= APP_BODY_LIMIT ? cJSON_ParseWithLengthOpts(raw, size + 1, NULL, true) : NULL;
    app_snapshot_t *next = heap_caps_malloc(sizeof(*next), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    const char *error = "接口数据无效";
    bool valid = next && doc && app_normalize(doc, next, &error);
    cJSON_Delete(doc);
    if (!valid) { free(next); if (live) fail(error); return false; }
    if (view->snapshot) free(view->snapshot->subscriptions);
    free(view->snapshot); view->snapshot = next;
    view->cached = true;
    if (live) {
        view->server_epoch = next->generated; view->received_mono = mono();
        view->failures = 0; view->retry_at = 0; view->error = NULL; view->connection = "已同步";
        if (cache_ready) {
            esp_err_t err = nvs_set_blob(cache, "snapshot", raw, size);
            if (err == ESP_OK) err = nvs_commit(cache);
            if (err != ESP_OK) ESP_LOGW(TAG, "Cache write failed: %s", esp_err_to_name(err));
        }
    } else view->connection = "离线缓存";
    return true;
}
static void responses(void)
{
    response_t response;
    while (xQueueReceive(response_queue, &response, 0)) {
        if (view->alive && response.id == view->request_id) {
            view->busy = false; view->last_http = response.code;
            if (response.code != 200) fail(response.code == 401 || response.code == 403 ? "接口鉴权失败" : "连接失败，请稍后重试");
            else if (accept_body(response.body, response.size, true)) render();
        }
        free(response.body);
    }
}
static void advance_message(void)
{
    sync_messages();
    if (!view->active_count) { view->message = 0; return; }
    view->message = (view->message + 1) % view->active_count;
    const char *id = view->snapshot->messages[view->active[view->message]].id;
    if (id[0]) snprintf(view->message_key, sizeof(view->message_key), "%s", id);
    else snprintf(view->message_key, sizeof(view->message_key), "index:%d", view->message + 1);
}
static void switch_page(int delta)
{
    sync_messages();
    int quota_pages = app_quota_pages(view->snapshot);
    int total = quota_pages + (view->active_count ? 1 : 0);
    int current = view->page ? total - 1 : view->quota_page;
    if (view->page) advance_message();
    int target = (current + delta + total) % total;
    view->page = target >= quota_pages;
    if (!view->page) view->quota_page = target;
    view->rotate_at = view->tick + view->rotate_seconds;
}
static void key_press(int key)
{
    if (!view->alive) return;
    if (key == 6) { view->alive = false; ++view->request_id; app_ui_stop(); return; }
    if (key == 2 || key == 3) switch_page(key == 3 ? 1 : -1);
    else if (key == 4) {
        if (view->page) { advance_message(); view->rotate_at = view->tick + view->rotate_seconds; }
        else refresh(true);
    } else if (key == 5) view->auto_rotate = !view->auto_rotate;
    render();
}
static void lifecycle_tick(void)
{
    if (!view->alive) return;
    view->tick++;
    bool link = link_up();
    if (view->link_known && link != view->previous_link && !view->busy) {
        view->failures = 0; view->retry_at = 0; view->last_fetch = view->tick - 10000;
    }
    view->previous_link = link; view->link_known = true;
    if (view->busy && view->tick - view->last_fetch > 15) { view->request_id++; fail("请求超时"); }
    int indices[APP_MAX_MESSAGES];
    if (app_active_messages(view->snapshot, now(), indices) != view->active_count) render();
    if (view->auto_rotate && view->tick >= view->rotate_at) { switch_page(1); render(); }
    else if (view->tick % 30 == 0) render();
    refresh(false);
}
static bool touch_read(uint16_t reg, void *data, size_t size)
{
    uint8_t address[] = {reg >> 8, reg & 255};
#if CONFIG_PANEL_YX40006ACT
    return i2c_master_transmit_receive(touch, address + 1, 1, data, size, 20) == ESP_OK;
#else
    return i2c_master_transmit_receive(touch, address, 2, data, size, 20) == ESP_OK;
#endif
}
static void touch_init(void)
{
    /* Shared with Qualia's LCD-control expander; owned by board.c. */
    i2c_master_bus_handle_t bus;
    if (board_i2c_get(&bus) != ESP_OK) return;
#if CONFIG_PANEL_YX40006ACT
    /* FT6336U needs >=300 ms after power/reset before reporting touches. */
    vTaskDelay(pdMS_TO_TICKS(300));
    int address = i2c_master_probe(bus, 0x38, 30) == ESP_OK ? 0x38 : 0;
#else
    int address = i2c_master_probe(bus, 0x5d, 30) == ESP_OK ? 0x5d : i2c_master_probe(bus, 0x14, 30) == ESP_OK ? 0x14 : 0;
#endif
    if (!address) return;
    i2c_device_config_t device = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = address, .scl_speed_hz = 400000};
    if (i2c_master_bus_add_device(bus, &device, &touch) != ESP_OK) return;
#if CONFIG_PANEL_YX40006ACT
    uint8_t chip = 0;
    if (!touch_read(0xa3, &chip, 1) || chip != 0x64) {
        ESP_LOGW(TAG, "FT6336U identity unavailable (0x%02x)", chip);
        i2c_master_bus_rm_device(touch); touch = NULL; return;
    }
    view->touch_available = true; ESP_LOGI(TAG, "FT6336U touch detected");
#else
    char product[5] = {0};
    if (!touch_read(0x8140, product, 4) || strncmp(product, "911", 3)) {
        i2c_master_bus_rm_device(touch); touch = NULL; return;
    }
    view->touch_available = true; ESP_LOGI(TAG, "GT911 touch detected");
#endif
}
static void touch_poll(void)
{
    if (!touch) return;
    int raw_x = 0, raw_y = 0;
#if CONFIG_PANEL_YX40006ACT
    uint8_t point[5];
    bool down;
    if (!touch_read(0x02, point, sizeof(point))) return;
    if (!ft6336_decode(point, display_geometry, &down, &raw_x, &raw_y)) { pressed = false; return; }
#else
    uint8_t status;
    if (!touch_read(0x814e, &status, 1) || !(status & 0x80)) return;
    uint8_t point[8];
    bool down = (status & 15) > 0;
    if (down && !touch_read(0x814f, point, sizeof(point))) return;
    const uint8_t clear[] = {0x81, 0x4e, 0};
    if (i2c_master_transmit(touch, clear, sizeof(clear), 20) != ESP_OK) return;
    if (down) { raw_x = point[1] | point[2] << 8; raw_y = point[3] | point[4] << 8; }
#endif
    if (down) {
        /* Match the panel's hardware 180-degree rotation for taps/swipes. */
        if (!display_touch_rotate_180(display_geometry, raw_x, raw_y, &last_x, &last_y)) return;
#if CONFIG_APP_FRAME_ROTATE_180
        /* Map panel coordinates back through the additional frame rotation. */
        if (!display_touch_rotate_180(display_geometry, last_x, last_y, &last_x, &last_y)) return;
#endif
        if (!pressed) { start_x = last_x; start_y = last_y; press_time = mono(); }
    } else if (pressed) {
        int dx = last_x - start_x, dy = last_y - start_y;
        if (mono() - press_time >= 3) key_press(6); /* Original Home / exit. */
        else if (abs(dx) > display_scale_480(display_geometry.width, 50) && abs(dx) > abs(dy)) key_press(dx > 0 ? 3 : 2);
        else if (abs(dy) > display_scale_480(display_geometry.height, 50)) key_press(dy > 0 ? 5 : 4);
        else key_press(display_tap_key(display_geometry, start_x, start_y));
    }
    pressed = down;
}
static void update_status(const char *state)
{
    cJSON *j = cJSON_CreateObject();
    if (!j) return;
    cJSON_AddStringToObject(j, "state", state);
    if (view) {
        cJSON_AddStringToObject(j, "implementation", "native_c");
        cJSON_AddStringToObject(j, "source_version", "1.2.2");
        cJSON_AddStringToObject(j, "source_revision", "ce2c175");
        cJSON_AddStringToObject(j, "transport", "usb_ncm");
        cJSON_AddStringToObject(j, "connection", view->connection);
        cJSON_AddStringToObject(j, "error", view->error ? view->error : "");
        cJSON_AddStringToObject(j, "page", view->page ? "messages" : "subscriptions");
        cJSON_AddNumberToObject(j, "active_messages", view->active_count);
        cJSON_AddNumberToObject(j, "message", view->message + 1);
        cJSON_AddNumberToObject(j, "quota_page", view->quota_page + 1);
        cJSON_AddNumberToObject(j, "quota_pages", app_quota_pages(view->snapshot));
        cJSON_AddNumberToObject(j, "subscriptions", view->snapshot ? view->snapshot->subscription_count : 0);
        const char *paper[] = {"#FFF2A6", "#DDEEB4", "#F7B6B2", "#B9DFF2"};
        cJSON_AddStringToObject(j, "note_color", view->page ? paper[view->message % 4] : "");
        cJSON_AddNumberToObject(j, "window", view->window + 1);
        cJSON_AddNumberToObject(j, "http_status", view->last_http);
        cJSON_AddNumberToObject(j, "polls", view->polls);
        cJSON_AddNumberToObject(j, "failures", view->failures);
        cJSON_AddNumberToObject(j, "retry_in_seconds", view->retry_at > mono() ? view->retry_at - mono() : 0);
        cJSON_AddNumberToObject(j, "fonts_loaded", view->fonts_loaded);
        cJSON_AddNumberToObject(j, "generated_at", view->snapshot ? view->snapshot->generated : 0);
        cJSON_AddBoolToObject(j, "busy", view->busy);
        cJSON_AddBoolToObject(j, "auto_rotate", view->auto_rotate);
        cJSON_AddBoolToObject(j, "cache_available", cache_ready);
        cJSON_AddBoolToObject(j, "has_snapshot", view->snapshot != NULL);
        cJSON_AddBoolToObject(j, "touch_available", view->touch_available);
#if CONFIG_PANEL_YX40006ACT
        cJSON_AddStringToObject(j, "touch_controller", "FT6336U");
#else
        cJSON_AddStringToObject(j, "touch_controller", "GT911");
#endif
        app_ui_add_metrics(j);
    }
    char *text = cJSON_PrintUnformatted(j); cJSON_Delete(j);
    if (text) {
        portENTER_CRITICAL(&status_lock);
        snprintf(status_json, sizeof(status_json), "%s", text);
        portEXIT_CRITICAL(&status_lock); free(text);
    }
}
void app_runtime_add_status(cJSON *json)
{
    char copy[sizeof(status_json)];
    portENTER_CRITICAL(&status_lock); memcpy(copy, status_json, sizeof(copy)); portEXIT_CRITICAL(&status_lock);
    cJSON *status = cJSON_Parse(copy);
    if (status) cJSON_AddItemToObject(json, "app", status);
}
static void load_config(void)
{
    FILE *f = fopen("/sd/apps/xiaobucubic/config.json", "rb");
    if (!f) return;
    char raw[4096]; size_t size = fread(raw, 1, sizeof(raw) - 1, f); fclose(f); raw[size] = 0;
    cJSON *config = cJSON_Parse(raw);
    if (!config) return;
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(config, "api_url");
    if (cJSON_IsString(item)) snprintf(view->api_url, sizeof(view->api_url), "%s", item->valuestring);
    item = cJSON_GetObjectItemCaseSensitive(config, "read_token");
    if (cJSON_IsString(item)) snprintf(view->read_token, sizeof(view->read_token), "%s", item->valuestring);
    item = cJSON_GetObjectItemCaseSensitive(config, "refresh_seconds");
    if (cJSON_IsNumber(item) && item->valuedouble >= 15 && item->valuedouble <= 3600) view->refresh_seconds = item->valueint;
    item = cJSON_GetObjectItemCaseSensitive(config, "rotate_seconds");
    if (cJSON_IsNumber(item) && item->valuedouble >= 8 && item->valuedouble <= 120) view->rotate_seconds = item->valueint;
    view->auto_rotate = !cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(config, "auto_rotate"));
    item = cJSON_GetObjectItemCaseSensitive(config, "utc_offset_minutes");
    if (cJSON_IsNumber(item) && item->valuedouble >= -720 && item->valuedouble <= 840) view->utc_offset_minutes = item->valueint;
    cJSON_Delete(config);
}
void app_runtime_run(esp_lcd_panel_handle_t panel)
{
    view = heap_caps_calloc(1, sizeof(*view), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!view) { update_status("out_of_memory"); return; }
    view->alive = view->auto_rotate = true; view->refresh_seconds = 60; view->rotate_seconds = 15;
    view->utc_offset_minutes = 480;
    view->last_fetch = (uint32_t)-10000; view->connection = "等待配置";
    esp_vfs_spiffs_conf_t fs = {.base_path = "/sd", .partition_label = "app_assets", .max_files = 8, .format_if_mount_failed = false};
    if (esp_vfs_spiffs_register(&fs) != ESP_OK) { update_status("assets_mount_failed"); return; }
    load_config(); view->rotate_at = view->rotate_seconds;
    cache_ready = nvs_flash_init_partition("app_cache") == ESP_OK && nvs_open_from_partition("app_cache", "display", NVS_READWRITE, &cache) == ESP_OK;
    size_t size = 0;
    if (cache_ready && nvs_get_blob(cache, "snapshot", NULL, &size) == ESP_OK && size <= APP_BODY_LIMIT) {
        char *raw = heap_caps_malloc(size + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (raw) { if (nvs_get_blob(cache, "snapshot", raw, &size) == ESP_OK) { raw[size] = 0; accept_body(raw, size, false); } free(raw); }
    }
    if (!app_ui_init(panel, view)) { view->error = "中文字库或显示内存不可用"; update_status("ui_init_failed"); return; }
    request_queue = xQueueCreate(1, sizeof(request_t)); response_queue = xQueueCreate(2, sizeof(response_t));
    if (!request_queue || !response_queue || xTaskCreate(http_worker, "app_http", 8192, NULL, 2, NULL) != pdPASS) { update_status("http_init_failed"); return; }
    touch_init(); render(); refresh(true); update_status("running");
    ESP_LOGI(TAG, "Native xiaobucubic app started, fonts=%d", view->fonts_loaded);
    int64_t previous_ms = esp_timer_get_time() / 1000, next_second = previous_ms + 1000, next_touch = previous_ms;
    for (;;) {
        int64_t current = esp_timer_get_time() / 1000;
        responses();
        if (current >= next_touch) { touch_poll(); next_touch = current + 50; }
        if (current >= next_second) { lifecycle_tick(); update_status(view->alive ? "running" : "stopped"); next_second += 1000; }
        app_ui_tick(current - previous_ms); previous_ms = current;
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
