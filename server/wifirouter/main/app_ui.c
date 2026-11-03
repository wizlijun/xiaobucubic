/* Layout and styles translated from apps/xiaobucubic/package/main.lua.
   Coordinates remain in the original 320x240 design space; 480x480 output
   scales layout and uses screen-sized fonts with measured text fitting. */
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <sys/stat.h>
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "lvgl.h"
#include "app_ui.h"

enum { BG=0x070C12, PANEL=0x111C28, TEXT=0xF0F5FC, MUTED=0x8497AC,
       MINT=0x6DE1C2, BLUE=0x83B6FF, AMBER=0xFFC078, YELLOW=0xFFD166, RED=0xFF5F6D };
typedef struct { char id[64]; lv_obj_t *obj, *parent; bool seen; } node_t;
static node_t nodes[96];
static lv_font_t *fonts[4];
static const lv_font_t *small, *medium, *message_font, *message_compact;
static lv_obj_t *root;
static int current_page = -1;
static const char *background;
static esp_lcd_panel_handle_t lcd;
static lv_disp_draw_buf_t draw_buffer;
static lv_disp_drv_t driver;
static SemaphoreHandle_t frame_boundary;
/* The IRAM-safe RGB callback must only access internal memory. */
static StaticSemaphore_t frame_boundary_storage;
static atomic_uint rgb_vsyncs, rgb_frame_completions, max_vsync_gap_us;
static int64_t previous_vsync_us;
static uint32_t presented_frames, frame_wait_timeouts, render_us, max_render_us, flip_us;
static int message_font_px = 32;
typedef struct { const uint8_t *data; uint32_t size, position; } font_file_t;
static font_file_t font_blob;
static void *font_open(lv_fs_drv_t *drv, const char *path, lv_fs_mode_t mode)
{
    if (mode != LV_FS_MODE_RD || !font_blob.data) return NULL;
    font_file_t *file = malloc(sizeof(*file));
    if (file) *file = font_blob;
    return file;
}
static lv_fs_res_t font_close(lv_fs_drv_t *drv, void *file) { free(file); return LV_FS_RES_OK; }
static lv_fs_res_t font_read(lv_fs_drv_t *drv, void *handle, void *buffer, uint32_t count, uint32_t *read)
{
    font_file_t *file = handle;
    *read = count < file->size - file->position ? count : file->size - file->position;
    memcpy(buffer, file->data + file->position, *read); file->position += *read; return LV_FS_RES_OK;
}
static lv_fs_res_t font_seek(lv_fs_drv_t *drv, void *handle, uint32_t position, lv_fs_whence_t whence)
{
    font_file_t *file = handle;
    uint64_t target = whence == LV_FS_SEEK_SET ? position : whence == LV_FS_SEEK_CUR ? (uint64_t)file->position + position : (uint64_t)file->size + position;
    if (target > file->size) return LV_FS_RES_INV_PARAM;
    file->position = target; return LV_FS_RES_OK;
}
static lv_fs_res_t font_tell(lv_fs_drv_t *drv, void *handle, uint32_t *position) { *position = ((font_file_t *)handle)->position; return LV_FS_RES_OK; }
static lv_font_t *load_font(const char *path)
{
    /* LVGL's binary loader does thousands of tiny seeks. Read flash once,
       then parse the unchanged font in PSRAM through a temporary LVGL drive. */
    struct stat st;
    if (stat(path, &st) || st.st_size <= 0 || st.st_size > 2 * 1024 * 1024) return NULL;
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    uint8_t *bytes = heap_caps_malloc(st.st_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    size_t read = bytes ? fread(bytes, 1, st.st_size, f) : 0; fclose(f);
    if (read != st.st_size) { free(bytes); return NULL; }
    font_blob = (font_file_t){bytes, st.st_size, 0};
    lv_font_t *font = lv_font_load("M:font");
    font_blob.data = NULL; free(bytes); return font;
}
static int px(double x) { return (int)floor(x * 1.5 + .5); }
static int py(double y) { return (int)floor(y * 2.0 + .5); }

/* LVGL 8 refreshes styles even for equal assignments. Match the original
   Lua property cache so unchanged data does not invalidate the whole screen. */
static void cached_style(lv_obj_t *o, lv_style_prop_t property, lv_style_value_t value)
{
    lv_style_value_t old = {0};
    if (lv_obj_get_local_style_prop(o, property, &old, 0) == LV_STYLE_RES_FOUND && !memcmp(&old, &value, sizeof(value))) return;
    lv_obj_set_local_style_prop(o, property, value, 0);
}
#define STYLE_NUMBER(name, prop) static void cached_##name(lv_obj_t *o, int v, int selector) { cached_style(o, prop, (lv_style_value_t){.num = v}); }
STYLE_NUMBER(bg_opa, LV_STYLE_BG_OPA) STYLE_NUMBER(border_width, LV_STYLE_BORDER_WIDTH)
STYLE_NUMBER(radius, LV_STYLE_RADIUS)
STYLE_NUMBER(text_align, LV_STYLE_TEXT_ALIGN) STYLE_NUMBER(text_line_space, LV_STYLE_TEXT_LINE_SPACE)
STYLE_NUMBER(bg_grad_dir, LV_STYLE_BG_GRAD_DIR) STYLE_NUMBER(bg_main_stop, LV_STYLE_BG_MAIN_STOP) STYLE_NUMBER(bg_grad_stop, LV_STYLE_BG_GRAD_STOP)
#define STYLE_COLOR(name, prop) static void cached_##name(lv_obj_t *o, lv_color_t v, int selector) { cached_style(o, prop, (lv_style_value_t){.color = v}); }
STYLE_COLOR(bg_color, LV_STYLE_BG_COLOR) STYLE_COLOR(bg_grad_color, LV_STYLE_BG_GRAD_COLOR) STYLE_COLOR(text_color, LV_STYLE_TEXT_COLOR)
static void cached_text_font(lv_obj_t *o, const lv_font_t *font, int selector) { cached_style(o, LV_STYLE_TEXT_FONT, (lv_style_value_t){.ptr = font}); }
static void cached_pad_all(lv_obj_t *o, int value, int selector)
{
    const lv_style_prop_t props[] = {LV_STYLE_PAD_TOP, LV_STYLE_PAD_BOTTOM, LV_STYLE_PAD_LEFT, LV_STYLE_PAD_RIGHT};
    for (int i = 0; i < 4; ++i) cached_style(o, props[i], (lv_style_value_t){.num = value});
}
#define lv_obj_set_style_bg_color cached_bg_color
#define lv_obj_set_style_bg_opa cached_bg_opa
#define lv_obj_set_style_border_width cached_border_width
#define lv_obj_set_style_radius cached_radius
#define lv_obj_set_style_pad_all cached_pad_all
#define lv_obj_set_style_text_align cached_text_align
#define lv_obj_set_style_text_line_space cached_text_line_space
#define lv_obj_set_style_bg_grad_dir cached_bg_grad_dir
#define lv_obj_set_style_bg_main_stop cached_bg_main_stop
#define lv_obj_set_style_bg_grad_stop cached_bg_grad_stop
#define lv_obj_set_style_bg_grad_color cached_bg_grad_color
#define lv_obj_set_style_text_color cached_text_color
#define lv_obj_set_style_text_font cached_text_font

static lv_obj_t *node(const char *id, int kind, lv_obj_t *parent)
{
    node_t *slot = NULL;
    for (size_t i = 0; i < 96; ++i) {
        if (nodes[i].obj && !strcmp(nodes[i].id, id)) { nodes[i].seen = true; return nodes[i].obj; }
        if (!nodes[i].obj && !slot) slot = &nodes[i];
    }
    if (!slot) abort(); /* Fixed layout has fewer than 60 objects. */
    slot->obj = kind == 1 ? lv_label_create(parent) : kind == 2 ? lv_img_create(parent) : lv_obj_create(parent);
    slot->parent = parent; slot->seen = true; snprintf(slot->id, sizeof(slot->id), "%s", id);
    lv_obj_clear_flag(slot->obj, LV_OBJ_FLAG_SCROLLABLE);
    return slot->obj;
}
static lv_obj_t *box(const char *id, lv_obj_t *parent, double x, double y, double w, double h, uint32_t color, int radius, int opacity)
{
    lv_obj_t *o = node(id, 0, parent);
    lv_obj_set_pos(o, px(x), py(y)); lv_obj_set_size(o, px(w), py(h));
    lv_obj_set_style_bg_color(o, lv_color_hex(color), 0); lv_obj_set_style_bg_opa(o, opacity, 0);
    lv_obj_set_style_border_width(o, 0, 0); lv_obj_set_style_radius(o, radius, 0); lv_obj_set_style_pad_all(o, 0, 0);
    return o;
}
static lv_obj_t *label(const char *id, lv_obj_t *parent, int x, int y, int w, int h, const char *text,
                       const lv_font_t *font, uint32_t color, lv_text_align_t align, lv_label_long_mode_t mode)
{
    lv_obj_t *o = node(id, 1, parent);
    lv_obj_set_pos(o, px(x), py(y)); lv_obj_set_size(o, px(w), py(h));
    lv_obj_set_style_text_font(o, font, 0); lv_obj_set_style_text_color(o, lv_color_hex(color), 0);
    lv_obj_set_style_text_align(o, align, 0);
    if (lv_label_get_long_mode(o) != mode) lv_label_set_long_mode(o, mode);
    if (strcmp(lv_label_get_text(o), text)) lv_label_set_text(o, text);
    return o;
}
static void finish_frame(void)
{
    /* Delete unseen roots first, then forget descendants without touching freed objects. */
    bool removed[96] = {0};
    for (int i = 0; i < 96; ++i) removed[i] = nodes[i].obj && !nodes[i].seen;
    for (int i = 0; i < 96; ++i) if (removed[i]) {
        bool parent_removed = false;
        for (int j = 0; j < 96; ++j) if (removed[j] && nodes[j].obj == nodes[i].parent) parent_removed = true;
        if (!parent_removed) lv_obj_del(nodes[i].obj);
    }
    for (int i = 0; i < 96; ++i) if (removed[i]) memset(&nodes[i], 0, sizeof(nodes[i]));
}
static uint32_t mix(uint32_t a, uint32_t b, double weight)
{
    uint32_t color = 0;
    for (int shift = 0; shift <= 16; shift += 8) {
        int x = (a >> shift) & 255, y = (b >> shift) & 255;
        color |= (uint32_t)floor(x + (y - x) * weight + .5) << shift;
    }
    return color;
}
static uint32_t tone(int value, app_window_state_t state, uint32_t accent)
{
    return value >= 0 && value < 5 ? RED : value >= 0 && value < 20 ? YELLOW : state == APP_OK ? accent : MUTED;
}
static void gradient(lv_obj_t *o, uint32_t color, double weight)
{
    lv_obj_set_style_bg_grad_color(o, lv_color_hex(mix(PANEL, color, weight)), 0);
    lv_obj_set_style_bg_grad_dir(o, LV_GRAD_DIR_VER, 0);
    lv_obj_set_style_bg_main_stop(o, 0, 0); lv_obj_set_style_bg_grad_stop(o, 255, 0);
}
static const char *num(char out[32], double n, const char *suffix)
{
    if (isnan(n)) snprintf(out, 32, "--"); else snprintf(out, 32, "%.0f%s", n, suffix);
    return out;
}
static void network_indicator(const app_view_t *s)
{
    const char *badge = s->busy ? "同步中" : !strcmp(s->connection, "已同步") ? "USB" :
        !strcmp(s->connection, "离线缓存") ? "离线" : !strcmp(s->connection, "待配置") ? "待配置" : "未连接";
    if (s->error && !strcmp(s->error, "接口鉴权失败")) badge = "鉴权失败";
    else if (s->error && !strcmp(s->error, "请求超时")) badge = "超时";
    uint32_t color = s->error ? AMBER : !strcmp(s->connection, "已同步") ? MINT : MUTED;
    if (s->page) color = s->error ? 0x823B20 : 0x38432B;
    label("network.text", root, 230, 5, 78, 17, badge, small, color, LV_TEXT_ALIGN_RIGHT, LV_LABEL_LONG_WRAP);
    label("network.demo", root, 253, 23, 55, 14, s->snapshot && s->snapshot->demo ? "演示" : "", small, s->page ? 0x823B20 : AMBER, LV_TEXT_ALIGN_RIGHT, LV_LABEL_LONG_WRAP);
}
static void weather_background(const app_view_t *s)
{
    const char *asset = app_weather_asset(s->snapshot ? &s->snapshot->weather : NULL);
    lv_obj_t *layer = box("background", root, 0, 0, 320, 240, BG, 0, 255);
    char path[128]; struct stat st;
    snprintf(path, sizeof(path), "/sd/apps/xiaobucubic/assets/weather/%s.png", asset ? asset : "");
    if (asset && !stat(path, &st)) {
        lv_obj_t *img = node("background.image", 2, layer);
        char src[128]; snprintf(src, sizeof(src), "S:/apps/xiaobucubic/assets/weather/%s.png", asset);
        const char *old = lv_img_get_src(img);
        if (!old || strcmp(old, src)) lv_img_set_src(img, src);
        /* The original artwork is 4:3; cover the square LCD and crop its
           sides so weather remains behind all three translucent cards. */
        lv_img_set_pivot(img, 0, 0); lv_obj_set_pos(img, -80, 0); lv_img_set_zoom(img, 512);
        box("background.shade", layer, 0, 0, 320, 240, BG, 0, 40); background = asset;
    } else background = NULL;
}
static void weather_inline(const app_view_t *s, int64_t now)
{
    const app_weather_t *w = s->snapshot ? &s->snapshot->weather : NULL;
    bool valid = w && w->present && !isnan(w->temperature);
    bool stale = !valid || app_stale(w->updated, now, s->snapshot->ttl);
    char value[128], a[32], b[32], city[32];
    label("weather.temperature", root, 12, 12, 100, 35, valid ? num(a, w->temperature, "°C") : "--°C", &lv_font_montserrat_48, stale ? MUTED : TEXT, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_WRAP);
    app_text(city, sizeof(city), valid ? w->city : "天气待同步", 7, false);
    label("weather.city", root, 119, 10, 89, 20, city, medium, stale ? MUTED : MINT, LV_TEXT_ALIGN_CENTER, LV_LABEL_LONG_SCROLL);
    snprintf(value, sizeof(value), "%s%s", valid ? num(a, w->humidity, "") : "", valid ? "%" : "");
    label("weather.humidity", root, 119, 30, 89, 20, value, medium, MUTED, LV_TEXT_ALIGN_CENTER, LV_LABEL_LONG_WRAP);
    if (valid) snprintf(value, sizeof(value), "%s–%s°C", num(a, w->low, ""), num(b, w->high, "")); else value[0] = 0;
    label("weather.range", root, 12, 51, 105, 20, value, medium, MUTED, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_WRAP);
    snprintf(value, sizeof(value), "%s%s", valid ? num(a, w->pressure, "") : "", valid ? " hPa" : "");
    label("weather.pressure", root, 119, 51, 89, 20, value, medium, MUTED, LV_TEXT_ALIGN_CENTER, LV_LABEL_LONG_WRAP);
    label("weather.status", root, 210, 37, 98, 14, valid && stale ? "已过期" : "", small, AMBER, LV_TEXT_ALIGN_RIGHT, LV_LABEL_LONG_WRAP);
    label("weather.condition", root, 210, 51, 98, 20, valid ? w->condition : "", medium, MUTED, LV_TEXT_ALIGN_RIGHT, LV_LABEL_LONG_SCROLL);
}
static void subscriptions(app_view_t *s, int64_t now)
{
    weather_background(s); weather_inline(s, now);
    s->window = 0; /* Latest app keeps server primary/secondary roles fixed. */
    if (!s->snapshot || !s->snapshot->subscription_count) {
        label("quota.empty.title", root, 18, 113, 284, 26, "等待额度数据", medium, TEXT, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_WRAP);
        label("quota.empty.body", root, 18, 149, 284, 60, !s->api_url[0] ? "设置数据接口后开始同步。" : "接口接通后，这里显示服务端提供的剩余额度。", medium, MUTED, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_WRAP);
        return;
    }
    app_card_t cards[6];
    int count = app_subscription_layout(s->snapshot, s->quota_page, cards);
    if (app_quota_pages(s->snapshot) > 1) {
        char pages[32]; snprintf(pages, sizeof(pages), "%d/%d", s->quota_page + 1, app_quota_pages(s->snapshot));
        label("quota.pages", root, 211, 23, 34, 14, pages, small, MUTED, LV_TEXT_ALIGN_RIGHT, LV_LABEL_LONG_WRAP);
    }
    const uint32_t palette[] = {AMBER, MINT, BLUE};
    for (int i = 0; i < count; ++i) {
        app_card_t *card = &cards[i];
        const app_subscription_t *p = &s->snapshot->subscriptions[card->index];
        const app_window_t *w = p->count ? &p->windows[0] : NULL;
        const app_window_t *companion = p->count > 1 ? &p->windows[1] : NULL;
        int width = card->width, height = card->height;
        bool grid = width < 200;
        char id[64], detail[384], reset[64], percent[32], balance[80] = "";
#define ID(suffix) (snprintf(id, sizeof(id), "quota.%d" suffix, i), id)
        lv_obj_t *panel = box(ID(""), root, card->x, card->y, width, height, PANEL, 7, background ? 52 : 255);
        uint32_t accent = palette[card->index % 3];
        app_window_state_t status = app_window_state(p, w, now, s->snapshot->ttl);
        int value = app_remaining(w); uint32_t color = tone(value, status, accent);
        lv_obj_t *fill = box(ID(".progress"), panel, 0, 0, value > 0 ? fmax(1, (double)width * value / 100) : 1, height, color, 7, value > 0 ? status == APP_OK ? 64 : 35 : 0);
        gradient(fill, color, .16);
        if (w && w->bytes_valid) {
            char remaining[32], total[32]; app_format_bytes(w->remaining_bytes, remaining); app_format_bytes(w->total_bytes, total);
            snprintf(balance, sizeof(balance), "%s/%s", remaining, total);
        }
        int top = height < 45 || grid ? 2 : 5;
        int value_width = grid ? 50 : balance[0] ? 176 : 82, value_x = width - 12 - value_width;
        label(ID(".name"), panel, grid ? 6 : 10, top, value_x - (grid ? 10 : 16), 20, p->name, medium, TEXT, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_DOT);
        snprintf(percent, sizeof(percent), value >= 0 ? "%d%%" : "--", value);
        label(ID(".value"), panel, value_x, top, value_width, 20, !grid && balance[0] ? balance : percent, medium, color, LV_TEXT_ALIGN_RIGHT, LV_LABEL_LONG_DOT);
        const char *source = !strcmp(p->source, "official") ? "官方" : !strcmp(p->source, "manual") ? "手动" : !strcmp(p->source, "estimated") ? "估算" : "待接入";
        bool show_source = (!companion && !grid && height >= 45) || strcmp(p->source, "official");
        snprintf(detail, sizeof(detail), "%s%s%s", app_window_label(w), balance[0] || show_source ? " · " : "", balance[0] ? percent : show_source ? source : "");
        app_reset_date(w ? w->reset : 0, now, s->utc_offset_minutes, reset);
        const char *extra = status == APP_STALE ? " · 已过期" : status == APP_EXPIRED ? " · 待刷新" : "";
        strncat(detail, extra, sizeof(detail) - strlen(detail) - 1);
        if (status != APP_STALE && status != APP_EXPIRED && reset[0]) {
            strncat(detail, " ", sizeof(detail) - strlen(detail) - 1); strncat(detail, reset, sizeof(detail) - strlen(detail) - 1);
        }
        int detail_y = height < 45 || grid ? 21 : 28, detail_h = height < 45 || grid ? 13 : 15;
        label(ID(".detail"), panel, grid ? 6 : 10, detail_y, grid ? width - 12 : companion ? 120 : width - 20,
              detail_h, grid && balance[0] ? balance : detail, small, MUTED, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_DOT);
        if (grid && balance[0] && !companion)
            label(ID(".reset"), panel, 6, 35, width - 12, 13, detail, small, MUTED, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_DOT);
        if (companion) {
            status = app_window_state(p, companion, now, s->snapshot->ttl); value = app_remaining(companion); color = tone(value, status, accent);
            snprintf(percent, sizeof(percent), value >= 0 ? "%d%%" : "--", value);
            snprintf(detail, sizeof(detail), "%s%s%s", !strcmp(companion->label, "7天") ? "" : app_window_label(companion), !strcmp(companion->label, "7天") ? "" : " ", percent);
            extra = status == APP_STALE ? " · 已过期" : status == APP_EXPIRED ? " · 待刷新" : "";
            strncat(detail, extra, sizeof(detail) - strlen(detail) - 1);
            app_reset_date(companion->reset, now, s->utc_offset_minutes, reset);
            if (status != APP_STALE && status != APP_EXPIRED && reset[0]) {
                strncat(detail, " ", sizeof(detail) - strlen(detail) - 1); strncat(detail, reset, sizeof(detail) - strlen(detail) - 1);
            }
            label(ID(".secondary.label"), panel, grid ? 6 : width - 164, grid ? 35 : detail_y, grid ? width - 12 : 152,
                  detail_h, detail, small, color, LV_TEXT_ALIGN_RIGHT, grid ? LV_LABEL_LONG_SCROLL : LV_LABEL_LONG_DOT);
            int rail_y = height - 3, rail_height = 2;
            if (!grid && height >= 45) { rail_y = height - 6; rail_height = 4; }
            box(ID(".secondary.track"), panel, 10, rail_y, width - 22, rail_height, MUTED, 2, 24);
            fill = box(ID(".secondary.fill"), panel, 10, rail_y, value > 0 ? fmax(1, (width - 22.0) * value / 100) : 1, rail_height, color, 2,
                       value > 0 ? status == APP_OK ? 112 : 55 : 0);
            gradient(fill, color, .35);
        }
#undef ID
    }
}
static bool closing_punctuation(uint32_t cp)
{
    return cp == 0x3002 || cp == 0xFF0C || cp == 0x3001 || cp == 0xFF01 || cp == 0xFF1F ||
           cp == 0xFF1B || cp == 0xFF1A || cp == 0x201D || cp == 0x2019 || cp == 0x300B ||
           cp == 0x300D || cp == 0x300F || cp == 0x3011 || cp == 0xFF09;
}
static void note_layout(const char *text, const lv_font_t *font, int width, char out[1024])
{
    size_t used = 0;
    while (*text && used < 1023) {
        uint32_t count = _lv_txt_get_next_line(text, font, 0, width, NULL, LV_TEXT_FLAG_NONE);
        if (!count) break;
        if (text[count] && text[count - 1] != '\n') {
            uint32_t next = count, previous = count;
            uint32_t cp = _lv_txt_encoded_next(text, &next);
            uint32_t before = _lv_txt_encoded_prev(text, &previous);
            /* Keep Chinese closing punctuation with its preceding character,
               instead of leaving a full stop alone on the next line. */
            if (previous && before >= 0x2E80 && closing_punctuation(cp)) count = previous;
        }
        if (used + count + 1 >= 1024) break; /* Input is bounded to 180 characters. */
        memcpy(out + used, text, count); used += count; text += count;
        if (*text && out[used - 1] != '\n') out[used++] = '\n';
    }
    out[used] = 0;
}
static void reminder(app_view_t *s, int64_t now)
{
    if (!s->active_count) return;
    static const uint32_t colors[][2] = {
        {0xFFF2A6, 0xE2CA65}, {0xDDEEB4, 0xAEC87C}, {0xF7B6B2, 0xDE8580}, {0xB9DFF2, 0x83BBD7},
    };
    const uint32_t *color = colors[s->message % 4];
    const app_message_t *r = &s->snapshot->messages[s->active[s->message]];
    char text[256], body_text[1024], due[64] = "";
    box("message.header", root, 0, 0, 320, 29, color[1], 0, 255);
    snprintf(text, sizeof(text), "便签 · %d / %d", s->message + 1, s->active_count);
    label("message.count", root, 14, 6, 210, 20, text, medium, 0x30382D, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_WRAP);
    lv_obj_t *sheet = box("message.paper", root, 0, 29, 320, 211, color[0], 0, 255);
    /* Fit the actual text to the physical paper, not the old 264px/5-line
       preview. Keep short notes large; long notes use 24px with ellipsis
       only when even that size cannot fit. LVGL measures and wraps glyphs. */
    lv_point_t measured;
    const int line_space = 6, body_width = px(276), body_height = py(158);
    note_layout(r->text, message_font, body_width, body_text);
    lv_txt_get_size(&measured, body_text, message_font, 0, line_space, body_width, LV_TEXT_FLAG_NONE);
    const lv_font_t *body_font = measured.y <= body_height ? message_font : message_compact;
    if (body_font != message_font) note_layout(r->text, body_font, body_width, body_text);
    message_font_px = body_font == message_font ? 32 : 24;
    lv_obj_t *body = label("message.body", sheet, 22, 14, 276, 158, body_text, body_font, 0x30382D, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_line_space(body, line_space, 0);
    if (r->due && now) {
        int64_t mins = (int64_t)ceil((r->due - now) / 60.0);
        if (mins <= 0) snprintf(due, sizeof(due), " · 已到提醒时间");
        else if (mins < 60) snprintf(due, sizeof(due), " · %lld分钟后", (long long)mins);
        else snprintf(due, sizeof(due), " · %lld小时后", (long long)((mins + 59) / 60));
    }
    snprintf(text, sizeof(text), "%s%s%s", r->bot ? "Bot · " : "", r->high ? "重要" : "备忘", due);
    label("message.meta", sheet, 22, 184, 226, 17, text, small, 0x626B50, LV_TEXT_ALIGN_LEFT, LV_LABEL_LONG_CLIP);
}
static bool IRAM_ATTR frame_complete(esp_lcd_panel_handle_t panel, const esp_lcd_rgb_panel_event_data_t *event, void *context)
{
    atomic_fetch_add_explicit(&rgb_frame_completions, 1, memory_order_relaxed);
    BaseType_t wake = pdFALSE;
    xSemaphoreGiveFromISR((SemaphoreHandle_t)context, &wake);
    return wake == pdTRUE;
}
static bool IRAM_ATTR frame_vsync(esp_lcd_panel_handle_t panel, const esp_lcd_rgb_panel_event_data_t *event, void *context)
{
    int64_t now = esp_timer_get_time();
    if (previous_vsync_us) {
        uint32_t gap = (uint32_t)(now - previous_vsync_us);
        if (gap > atomic_load_explicit(&max_vsync_gap_us, memory_order_relaxed))
            atomic_store_explicit(&max_vsync_gap_us, gap, memory_order_relaxed);
    }
    previous_vsync_us = now;
    atomic_fetch_add_explicit(&rgb_vsyncs, 1, memory_order_relaxed);
    return false;
}
static void flush(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *pixels)
{
    int64_t started = esp_timer_get_time();
    /* pixels is one of the driver's two full-frame buffers, so this changes
       the pending buffer index without copying into the visible frame. */
    esp_err_t error = esp_lcd_panel_draw_bitmap(lcd, 0, 0, 480, 480, pixels);
    if (error != ESP_OK) ESP_LOGE("ap24_ui", "Frame submit failed: %s", esp_err_to_name(error));
    /* Discard acknowledgments before/during submission. The next callback
       occurs after the bounce driver has selected the new frame; only then
       may LVGL repaint the previous front buffer. A VSYNC alone is too early
       for the driver's two preloaded bounce buffers. */
    xSemaphoreTake(frame_boundary, 0);
    if (xSemaphoreTake(frame_boundary, pdMS_TO_TICKS(200)) != pdTRUE) {
        ++frame_wait_timeouts;
        ESP_LOGW("ap24_ui", "Waiting for RGB frame boundary");
        xSemaphoreTake(frame_boundary, portMAX_DELAY);
    }
    flip_us = esp_timer_get_time() - started;
    ++presented_frames;
    lv_disp_flush_ready(drv);
}
bool app_ui_init(esp_lcd_panel_handle_t panel, app_view_t *view)
{
    lcd = panel; lv_init();
    lv_fs_drv_t fs; lv_fs_drv_init(&fs); fs.letter = 'M';
    fs.open_cb = font_open; fs.close_cb = font_close; fs.read_cb = font_read; fs.seek_cb = font_seek; fs.tell_cb = font_tell;
    lv_fs_drv_register(&fs);
    void *front, *back;
    if (esp_lcd_rgb_panel_get_frame_buffer(panel, 2, &front, &back) != ESP_OK) return false;
    frame_boundary = xSemaphoreCreateBinaryStatic(&frame_boundary_storage);
    if (!frame_boundary) return false;
    esp_lcd_rgb_panel_event_callbacks_t callbacks = {.on_frame_buf_complete = frame_complete, .on_vsync = frame_vsync};
    if (esp_lcd_rgb_panel_register_event_callbacks(panel, &callbacks, frame_boundary) != ESP_OK) return false;
    /* RGB starts with buffer zero: LVGL must draw buffer one first. */
    lv_disp_draw_buf_init(&draw_buffer, back, front, 480 * 480);
    lv_disp_drv_init(&driver); driver.hor_res = 480; driver.ver_res = 480;
    driver.flush_cb = flush; driver.draw_buf = &draw_buffer; driver.full_refresh = 1;
    if (!lv_disp_drv_register(&driver)) return false;
    root = lv_scr_act();
    const char *paths[] = {"/sd/apps/xiaobucubic/font/ui18.bin", "/sd/apps/xiaobucubic/font/ui24.bin",
                          "/sd/apps/xiaobucubic/font/wenkai24.bin", "/sd/apps/xiaobucubic/font/wenkai32.bin"};
    for (int i = 0; i < 4; ++i) { fonts[i] = load_font(paths[i]); if (fonts[i]) ++view->fonts_loaded; }
    small = fonts[0] ? fonts[0] : &lv_font_montserrat_12;
    medium = fonts[1] ? fonts[1] : &lv_font_montserrat_16;
    message_compact = fonts[2] ? fonts[2] : medium;
    message_font = fonts[3] ? fonts[3] : message_compact;
    return view->fonts_loaded == 4;
}
void app_ui_render(app_view_t *s, int64_t now)
{
    if (!s->alive) return;
    if (current_page != s->page) {
        lv_obj_clean(root); memset(nodes, 0, sizeof(nodes)); current_page = s->page;
        lv_obj_set_style_bg_color(root, lv_color_hex(BG), 0); lv_obj_set_style_bg_opa(root, 255, 0);
        lv_obj_set_style_pad_all(root, 0, 0); lv_obj_clear_flag(root, LV_OBJ_FLAG_SCROLLABLE);
    }
    for (int i = 0; i < 96; ++i) nodes[i].seen = false;
    if (!s->page) subscriptions(s, now); else reminder(s, now);
    network_indicator(s); finish_frame();
}
void app_ui_tick(uint32_t elapsed_ms)
{
    lv_tick_inc(elapsed_ms);
    uint32_t previous_frames = presented_frames;
    int64_t started = esp_timer_get_time();
    lv_timer_handler();
    if (presented_frames != previous_frames) {
        render_us = esp_timer_get_time() - started;
        if (render_us > max_render_us) max_render_us = render_us;
    }
}
void app_ui_add_metrics(cJSON *object)
{
    cJSON_AddStringToObject(object, "refresh_mode", "whole_frame_double_buffer");
    cJSON_AddNumberToObject(object, "presented_frames", presented_frames);
    cJSON_AddNumberToObject(object, "render_ms", render_us / 1000.0);
    cJSON_AddNumberToObject(object, "max_render_ms", max_render_us / 1000.0);
    cJSON_AddNumberToObject(object, "frame_swap_ms", flip_us / 1000.0);
    cJSON_AddNumberToObject(object, "frame_wait_timeouts", frame_wait_timeouts);
    cJSON_AddNumberToObject(object, "rgb_vsyncs", atomic_load_explicit(&rgb_vsyncs, memory_order_relaxed));
    cJSON_AddNumberToObject(object, "rgb_frame_completions", atomic_load_explicit(&rgb_frame_completions, memory_order_relaxed));
    cJSON_AddNumberToObject(object, "max_vsync_gap_ms", atomic_load_explicit(&max_vsync_gap_us, memory_order_relaxed) / 1000.0);
    cJSON_AddStringToObject(object, "typography", "480px_adaptive_18_24_32");
    cJSON_AddStringToObject(object, "message_font_family", "LXGW WenKai");
    cJSON_AddNumberToObject(object, "message_font_px", message_font_px);
}
void app_ui_stop(void) { lv_obj_clean(root); for (int i = 0; i < 4; ++i) if (fonts[i]) lv_font_free(fonts[i]); }
