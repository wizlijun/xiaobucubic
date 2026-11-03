#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "app_model.h"
int main(void)
{
    char input[65536]; size_t length = fread(input, 1, sizeof(input) - 1, stdin); input[length] = 0;
    cJSON *doc = cJSON_Parse(input), *out = cJSON_CreateObject();
    app_snapshot_t data; const char *error = NULL;
    if (!app_normalize(doc, &data, &error)) cJSON_AddStringToObject(out, "error", error);
    else {
        cJSON *clock = cJSON_GetObjectItem(doc, "_now"); int64_t now = cJSON_IsNumber(clock) ? clock->valuedouble : 0;
        cJSON_AddNumberToObject(out, "subscriptions", data.subscription_count);
        cJSON_AddNumberToObject(out, "messages", data.message_count);
        cJSON_AddNumberToObject(out, "ttl", data.ttl);
        cJSON_AddBoolToObject(out, "secondary", app_has_secondary(&data));
        cJSON_AddNumberToObject(out, "quota_pages", app_quota_pages(&data));
        cJSON *page = cJSON_GetObjectItem(doc, "_quota_page");
        app_card_t cards[6]; int visible = app_subscription_layout(&data, cJSON_IsNumber(page) ? page->valueint - 1 : 0, cards);
        cJSON *layout = cJSON_AddArrayToObject(out, "layout");
        for (int i = 0; i < visible; ++i) {
            cJSON *card = cJSON_CreateObject(); cJSON_AddItemToArray(layout, card);
            cJSON_AddNumberToObject(card, "index", cards[i].index + 1); cJSON_AddNumberToObject(card, "x", cards[i].x);
            cJSON_AddNumberToObject(card, "y", cards[i].y); cJSON_AddNumberToObject(card, "width", cards[i].width); cJSON_AddNumberToObject(card, "height", cards[i].height);
        }
        const char *asset = app_weather_asset(&data.weather);
        if (asset) cJSON_AddStringToObject(out, "weather", asset); else cJSON_AddNullToObject(out, "weather");
        cJSON *rows = cJSON_AddArrayToObject(out, "rows");
        const char *states[] = {"unknown", "stale", "expired", "ok"};
        for (int i = 0; i < data.subscription_count; ++i) {
            app_subscription_t *s = &data.subscriptions[i];
            cJSON *r = cJSON_CreateObject(); cJSON_AddItemToArray(rows, r);
            cJSON_AddStringToObject(r, "id", s->id); cJSON_AddStringToObject(r, "name", s->name);
            cJSON *windows = cJSON_AddArrayToObject(r, "windows");
            for (int j = 0; j < s->count; ++j) {
                cJSON *w = cJSON_CreateObject(); cJSON_AddItemToArray(windows, w);
                cJSON_AddStringToObject(w, "label", s->windows[j].label);
                int remaining = app_remaining(&s->windows[j]);
                if (remaining < 0) cJSON_AddNullToObject(w, "remaining"); else cJSON_AddNumberToObject(w, "remaining", remaining);
                cJSON_AddStringToObject(w, "state", states[app_window_state(s, &s->windows[j], now, data.ttl)]);
                cJSON_AddStringToObject(w, "display_label", app_window_label(&s->windows[j]));
                if (s->windows[j].bytes_valid) {
                    char bytes[32]; app_format_bytes(s->windows[j].remaining_bytes, bytes);
                    cJSON_AddStringToObject(w, "balance", bytes);
                }
            }
        }
        int indices[APP_MAX_MESSAGES], n = app_active_messages(&data, now, indices);
        cJSON_AddNumberToObject(out, "active", n);
        cJSON *bodies = cJSON_AddArrayToObject(out, "bodies");
        for (int i = 0; i < data.message_count; ++i) cJSON_AddItemToArray(bodies, cJSON_CreateString(data.messages[i].text));
        free(data.subscriptions);
    }
    const cJSON *text = cJSON_GetObjectItem(doc, "_chunk_text");
    if (cJSON_IsString(text)) {
        char parts[APP_MAX_PARTS][800]; int n = app_message_chunks(text->valuestring, parts);
        cJSON *a = cJSON_AddArrayToObject(out, "chunks");
        for (int i = 0; i < n; ++i) cJSON_AddItemToArray(a, cJSON_CreateString(parts[i]));
        char preview[800]; app_message_preview(text->valuestring, preview); cJSON_AddStringToObject(out, "preview", preview);
    }
    cJSON *reset = cJSON_GetObjectItem(doc, "_reset");
    if (cJSON_IsNumber(reset)) {
        char date[64]; cJSON *clock = cJSON_GetObjectItem(doc, "_now"), *offset = cJSON_GetObjectItem(doc, "_offset");
        app_reset_date(reset->valuedouble, cJSON_IsNumber(clock) ? clock->valuedouble : 0, cJSON_IsNumber(offset) ? offset->valueint : 480, date);
        cJSON_AddStringToObject(out, "reset_date", date);
    }
    char *printed = cJSON_PrintUnformatted(out); puts(printed); free(printed); cJSON_Delete(out); cJSON_Delete(doc);
    return 0;
}
