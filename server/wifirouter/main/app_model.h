#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "cJSON.h"

/* Bounds and rules mirror apps/xiaobucubic/package/display_model.lua. */
#define APP_MAX_MESSAGES 12
#define APP_MAX_PARTS 40
#define APP_BODY_LIMIT 24576
typedef struct { char label[65]; double used, total_bytes, remaining_bytes; int64_t reset; bool bytes_valid; } app_window_t;
typedef struct {
    char id[257], name[161], source[12];
    int64_t updated;
    int count;
    app_window_t windows[2];
} app_subscription_t;
typedef struct {
    char id[321], text[721];
    bool high, bot;
    int64_t updated, due, expires;
} app_message_t;
typedef struct {
    bool present, night;
    char city[121], condition[121];
    double temperature, low, high, humidity, pressure;
    int64_t updated;
} app_weather_t;
typedef struct {
    int64_t generated;
    int ttl, subscription_count, message_count;
    bool demo;
    app_subscription_t *subscriptions;
    app_message_t messages[APP_MAX_MESSAGES];
    app_weather_t weather;
} app_snapshot_t;
typedef enum { APP_UNKNOWN, APP_STALE, APP_EXPIRED, APP_OK } app_window_state_t;

bool app_normalize(const cJSON *doc, app_snapshot_t *out, const char **error);
void app_text(char *out, size_t capacity, const char *value, int max_chars, bool multiline);
bool app_stale(int64_t updated, int64_t now, int ttl);
int app_remaining(const app_window_t *window); /* -1 means unknown. */
app_window_state_t app_window_state(const app_subscription_t *s, const app_window_t *w, int64_t now, int ttl);
bool app_has_secondary(const app_snapshot_t *data);
int app_active_messages(const app_snapshot_t *data, int64_t now, int indices[APP_MAX_MESSAGES]);
const char *app_weather_asset(const app_weather_t *weather);
int app_message_chunks(const char *text, char parts[APP_MAX_PARTS][800]);
void app_message_preview(const char *text, char out[800]);
int app_quota_pages(const app_snapshot_t *data);
typedef struct { int index, x, y, width, height; } app_card_t;
int app_subscription_layout(const app_snapshot_t *data, int page, app_card_t cards[6]);
const char *app_window_label(const app_window_t *window);
void app_reset_date(int64_t timestamp, int64_t now, int offset_minutes, char out[64]);
void app_format_bytes(double bytes, char out[32]);
