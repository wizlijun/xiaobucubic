#pragma once
#include "app_model.h"
#include "esp_lcd_panel_ops.h"

typedef struct {
    app_snapshot_t *snapshot;
    bool alive, busy, auto_rotate, cached, touch_available;
    int page, quota_page, window, message, active_count, active[APP_MAX_MESSAGES];
    int utc_offset_minutes;
    int refresh_seconds, rotate_seconds, failures, last_http, fonts_loaded;
    uint32_t tick, last_fetch, rotate_at, request_id, polls;
    int64_t received_mono, server_epoch, retry_at;
    bool previous_link, link_known;
    char message_key[340];
    const char *connection, *error;
    char api_url[1025], read_token[513];
} app_view_t;

bool app_ui_init(esp_lcd_panel_handle_t panel, app_view_t *view);
void app_ui_render(app_view_t *view, int64_t now);
void app_ui_tick(uint32_t elapsed_ms);
void app_ui_stop(void);
void app_ui_add_metrics(cJSON *object);
