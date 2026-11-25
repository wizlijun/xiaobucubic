/* Native C translation of display_model.lua; preserve server order and limits. */
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include <stdlib.h>
#include <time.h>
#include "app_model.h"

static const cJSON *field(const cJSON *o, const char *name) { return cJSON_GetObjectItemCaseSensitive(o, name); }
static const char *string(const cJSON *v) { return cJSON_IsString(v) ? v->valuestring : NULL; }
static double number(const cJSON *v, double lo, double hi)
{
    return cJSON_IsNumber(v) && isfinite(v->valuedouble) && v->valuedouble >= lo && v->valuedouble <= hi ? v->valuedouble : NAN;
}
static int64_t epoch(const cJSON *v) { double n = number(v, 1, 4102444800.0); return isnan(n) ? 0 : (int64_t)n; }
static size_t utf8_length(const unsigned char *s)
{
    if (*s < 128) return 1;
    size_t n = *s >= 194 && *s <= 223 ? 2 : *s <= 239 && *s >= 224 ? 3 : *s >= 240 && *s <= 244 ? 4 : 0;
    for (size_t i = 1; i < n; ++i) if (!s[i] || (s[i] & 0xc0) != 0x80) return 0;
    return n;
}
void app_text(char *out, size_t capacity, const char *value, int max_chars, bool multiline)
{
    size_t used = 0;
    int chars = 0;
    const unsigned char *s = (const unsigned char *)(value ? value : "");
    while (*s && chars < max_chars && used + 1 < capacity) {
        if (multiline && *s == '\t') {
            for (int i = 0; i < 4 && chars < max_chars && used + 1 < capacity; ++i) { out[used++] = ' '; ++chars; }
            ++s; continue;
        }
        if (multiline && *s == '\r') { out[used++] = '\n'; ++chars; s += s[1] == '\n' ? 2 : 1; continue; }
        size_t n = utf8_length(s);
        if (!n || (*s < 32 && !(multiline && *s == '\n')) || *s == 127) { ++s; continue; }
        if (used + n >= capacity) break;
        memcpy(out + used, s, n); used += n; s += n; ++chars;
    }
    out[used] = 0;
}
static void text_field(char *out, size_t capacity, const cJSON *o, const char *key, const char *fallback, int max)
{
    const char *s = string(field(o, key)); app_text(out, capacity, s ? s : fallback, max, false);
}
bool app_normalize(const cJSON *doc, app_snapshot_t *out, const char **error)
{
    if (!cJSON_IsObject(doc) || number(field(doc, "schema_version"), 1, 1) != 1) { *error = "接口版本不支持"; return false; }
    if (!epoch(field(doc, "generated_at"))) { *error = "缺少数据时间"; return false; }
    const cJSON *subs = field(doc, "subscriptions"), *messages = field(doc, "messages");
    if (!cJSON_IsArray(subs) || !cJSON_IsArray(messages)) { *error = "数据格式错误"; return false; }
    memset(out, 0, sizeof(*out));
    int capacity = cJSON_GetArraySize(subs);
    out->subscriptions = capacity ? calloc(capacity, sizeof(app_subscription_t)) : NULL;
    if (capacity && !out->subscriptions) { *error = "显示内存不足"; return false; }
    out->generated = epoch(field(doc, "generated_at"));
    out->demo = cJSON_IsTrue(field(doc, "demo"));
    double ttl = number(field(doc, "stale_after_seconds"), 30, 86400); out->ttl = isnan(ttl) ? 900 : (int)ttl;
    const cJSON *p;
    cJSON_ArrayForEach(p, subs) {
        const char *id = string(field(p, "id"));
        if (!cJSON_IsObject(p) || !id || !*id) continue;
        bool duplicate = false;
        /* Compare raw IDs exactly like Lua's seen table, before truncation. */
        for (const cJSON *prior = subs->child; prior != p; prior = prior->next) {
            const char *other = string(field(prior, "id"));
            if (other && !strcmp(id, other)) duplicate = true;
        }
        if (duplicate) continue;
        app_subscription_t *s = &out->subscriptions[out->subscription_count++];
        app_text(s->id, sizeof(s->id), id, 64, false);
        text_field(s->name, sizeof(s->name), p, "name", id, 40);
        const char *source = string(field(p, "source"));
        snprintf(s->source, sizeof(s->source), "%s", source && (!strcmp(source, "official") || !strcmp(source, "manual") || !strcmp(source, "estimated")) ? source : "unknown");
        s->updated = epoch(field(p, "updated_at"));
        const cJSON *windows = field(p, "windows"), *w;
        if (cJSON_IsArray(windows)) cJSON_ArrayForEach(w, windows) {
            if (!cJSON_IsObject(w) || s->count == 2) continue;
            app_window_t *window = &s->windows[s->count++];
            text_field(window->label, sizeof(window->label), w, "label", "用量", 16);
            window->used = number(field(w, "used_percent"), 0, 1000);
            window->reset = epoch(field(w, "reset_at"));
            double total = number(field(w, "total_bytes"), 1, 9007199254740991.0);
            double used = number(field(w, "used_bytes"), 0, 9007199254740991.0);
            if (!isnan(total) && !isnan(used) && floor(total) == total && floor(used) == used) {
                window->bytes_valid = true; window->total_bytes = total;
                window->remaining_bytes = fmax(0, total - used); window->used = used / total * 100;
            }
        }
    }
    cJSON_ArrayForEach(p, messages) {
        const char *raw = string(field(p, "text"));
        if (!cJSON_IsObject(p) || !raw || out->message_count == APP_MAX_MESSAGES) continue;
        app_message_t *m = &out->messages[out->message_count];
        app_text(m->text, sizeof(m->text), raw, 180, true);
        bool nonempty = false;
        for (const unsigned char *s = (const unsigned char *)m->text; *s; ++s) if (!isspace(*s)) nonempty = true;
        if (!nonempty) continue;
        text_field(m->id, sizeof(m->id), p, "id", "", 80);
        const char *priority = string(field(p, "priority")), *sender = string(field(p, "sender"));
        m->high = priority && !strcmp(priority, "high"); m->bot = sender && !strcmp(sender, "bot");
        m->updated = epoch(field(p, "updated_at")); m->due = epoch(field(p, "due_at")); m->expires = epoch(field(p, "expires_at"));
        ++out->message_count;
    }
    p = field(doc, "weather");
    app_weather_t *w = &out->weather;
    w->temperature = w->low = w->high = w->humidity = w->pressure = NAN;
    if (cJSON_IsObject(p)) {
        w->present = true; w->night = cJSON_IsFalse(field(p, "is_day"));
        text_field(w->city, sizeof(w->city), p, "city", "", 30);
        text_field(w->condition, sizeof(w->condition), p, "condition", "", 30);
        w->temperature = number(field(p, "temperature_c"), -100, 100);
        w->low = number(field(p, "low_c"), -100, 100); w->high = number(field(p, "high_c"), -100, 100);
        w->humidity = number(field(p, "humidity_percent"), 0, 100); w->pressure = number(field(p, "pressure_hpa"), 0, 2000);
        w->updated = epoch(field(p, "updated_at"));
    }
    return true;
}
bool app_stale(int64_t updated, int64_t now, int ttl) { return !updated || !now || now - updated > ttl || updated - now > 300; }
int app_remaining(const app_window_t *w) { return !w || isnan(w->used) ? -1 : (int)floor(fmax(0, 100 - w->used)); }
app_window_state_t app_window_state(const app_subscription_t *s, const app_window_t *w, int64_t now, int ttl)
{
    if (app_remaining(w) < 0) return APP_UNKNOWN;
    if (app_stale(s->updated, now, ttl)) return APP_STALE;
    if (w->reset && now >= w->reset) return APP_EXPIRED;
    return APP_OK;
}
bool app_has_secondary(const app_snapshot_t *data)
{
    if (data) for (int i = 0; i < data->subscription_count; ++i) if (data->subscriptions[i].count > 1) return true;
    return false;
}
int app_active_messages(const app_snapshot_t *data, int64_t now, int indices[APP_MAX_MESSAGES])
{
    int n = 0;
    if (data) for (int i = 0; i < data->message_count; ++i)
        if (!data->messages[i].expires || (now && data->messages[i].expires > now)) indices[n++] = i;
    return n;
}
const char *app_weather_asset(const app_weather_t *w)
{
    if (!w || !w->present) return NULL;
    char c[sizeof(w->condition)];
    for (size_t i = 0; i < sizeof(c); ++i) c[i] = tolower((unsigned char)w->condition[i]);
#define HAS(x) (strstr(c, x) != NULL)
    if (HAS("雨") || HAS("冰雹") || HAS("rain") || HAS("drizzle") || HAS("thunder") || HAS("hail")) return "rain";
    if (HAS("雪") || HAS("snow") || HAS("sleet")) return "snow";
    if (HAS("雾") || HAS("霧") || HAS("霾") || HAS("fog") || HAS("mist") || HAS("haze") || HAS("阴") || HAS("陰") || HAS("overcast")) return "overcast";
    if (HAS("云") || HAS("雲") || HAS("cloud")) return "partly_cloudy";
    if (HAS("晴") || HAS("clear") || HAS("sun")) return w->night || HAS("夜") || HAS("night") ? "clear_night" : "sunny";
    return "overcast";
}

int app_quota_pages(const app_snapshot_t *data)
{
    int count = data ? data->subscription_count : 0;
    return count ? (count + 5) / 6 : 1;
}
int app_subscription_layout(const app_snapshot_t *data, int page, app_card_t cards[6])
{
    int pages = app_quota_pages(data);
    if (page < 0) page = 0;
    if (page >= pages) page = pages - 1;
    int first = page * 6, visible = data ? data->subscription_count - first : 0;
    if (visible > 6) visible = 6;
    int rows = visible > 1 ? visible : 1;
    int gap = rows >= 6 ? 2 : 3;
    int avail = rows >= 6 ? 166 : 164;
    int height = (avail - (rows - 1) * gap) / rows;
    if (height > 52) height = 52;
    int width = 296;
    for (int i = 0; i < visible; ++i) cards[i] = (app_card_t){first + i, 12, 72 + i * (height + gap), width, height};
    return visible;
}
const char *app_window_label(const app_window_t *w) { return !w ? "暂无用量" : !strcmp(w->label, "7天") ? "周限" : w->label; }
void app_format_bytes(double bytes, char out[32])
{
    if (!isfinite(bytes) || bytes < 0 || bytes > 9007199254740991.0) { strcpy(out, "--"); return; }
    const char *units[] = {"B", "KiB", "MiB", "GiB", "TiB", "PiB"};
    int unit = 0;
    while (bytes >= 1024 && unit < 5) { bytes /= 1024; ++unit; }
    double value = floor(bytes * 10) / 10;
    snprintf(out, 32, floor(value) == value ? "%.0f%s" : "%.1f%s", value, units[unit]);
}
void app_reset_date(int64_t timestamp, int64_t clock, int offset_minutes, char out[64])
{
    out[0] = 0;
    if (timestamp < 1 || timestamp > 4102444800LL) return;
    if (offset_minutes < -720 || offset_minutes > 840) offset_minutes = 480;
    int offset = offset_minutes * 60;
    time_t local = timestamp + offset, current = clock + offset;
    struct tm date, today;
    gmtime_r(&local, &date); gmtime_r(&current, &today);
    int64_t day = (int64_t)floor((double)local / 86400), current_day = (int64_t)floor((double)current / 86400);
    int weekday = ((current_day + 3) % 7 + 7) % 7;
    char prefix[32] = "";
    if (clock && day == current_day) {}
    else if (clock && day >= current_day - weekday && day < current_day - weekday + 7) {
        const char *week[] = {"一", "二", "三", "四", "五", "六", "日"};
        snprintf(prefix, sizeof(prefix), "周%s", week[((day + 3) % 7 + 7) % 7]);
    } else if (clock && date.tm_year != today.tm_year) snprintf(prefix, sizeof(prefix), "%d/%02d/%02d ", date.tm_year + 1900, date.tm_mon + 1, date.tm_mday);
    else snprintf(prefix, sizeof(prefix), "%02d/%02d ", date.tm_mon + 1, date.tm_mday);
    snprintf(out, 64, "%s%02d:%02d重置", prefix, date.tm_hour, date.tm_min);
}
static int char_width(const unsigned char *c, size_t size)
{
    if (*c == ' ' || *c == '\t') return 6;
    if (size > 1) return 22;
    if (strchr("ilI!.,:;'|`", *c)) return 7;
    if (strchr("MW@%", *c)) return 22;
    if (*c >= 'A' && *c <= 'Z') return 16;
    if (*c == 'm' || *c == 'w') return 19;
    return 13;
}
typedef struct {
    char (*parts)[800]; int part, lines, width; size_t used, length;
    bool space; char line[800];
} chunk_writer_t;
static void chunk_line(chunk_writer_t *w)
{
    if (w->part >= APP_MAX_PARTS) return;
    if (w->lines) w->parts[w->part][w->used++] = '\n';
    memcpy(w->parts[w->part] + w->used, w->line, w->length); w->used += w->length;
    w->length = 0; w->width = 0;
    if (++w->lines == 5) { ++w->part; w->lines = 0; w->used = 0; }
}
static void chunk_token(chunk_writer_t *w, const unsigned char *text, size_t length)
{
    int width = 0;
    for (size_t i = 0; i < length;) { size_t n = utf8_length(text + i); if (!n) { ++i; continue; } width += char_width(text + i, n); i += n; }
    int gap = w->space && w->length ? 6 : 0;
    if (w->length && w->width + gap + width > 264) { chunk_line(w); gap = 0; }
    if (gap) { w->line[w->length++] = ' '; w->width += gap; }
    w->space = false;
    for (size_t i = 0; i < length;) {
        size_t n = utf8_length(text + i); if (!n) { ++i; continue; }
        int advance = char_width(text + i, n);
        if (w->length && w->width + advance > 264) chunk_line(w);
        if (w->length + n < sizeof(w->line)) { memcpy(w->line + w->length, text + i, n); w->length += n; w->width += advance; }
        i += n;
    }
}
int app_message_chunks(const char *text, char parts[APP_MAX_PARTS][800])
{
    memset(parts, 0, APP_MAX_PARTS * 800);
    chunk_writer_t writer = {.parts = parts};
    const unsigned char *s = (const unsigned char *)text;
    while (*s && writer.part < APP_MAX_PARTS) {
        size_t n = utf8_length(s); if (!n) { ++s; continue; }
        if (*s == '\n') { chunk_line(&writer); writer.space = false; ++s; }
        else if (*s == ' ' || *s == '\t' || *s == '\r') { writer.space = true; ++s; }
        else if (n == 1) {
            const unsigned char *start = s;
            while (*s && *s < 128 && *s != ' ' && *s != '\t' && *s != '\r' && *s != '\n') ++s;
            chunk_token(&writer, start, s - start);
        } else { chunk_token(&writer, s, n); s += n; }
    }
    if (writer.length) chunk_line(&writer);
    int count = writer.part + (writer.lines ? 1 : 0);
    return count ? count : 1;
}
void app_message_preview(const char *text, char out[800])
{
    char (*parts)[800] = calloc(APP_MAX_PARTS, 800);
    if (!parts) { out[0] = 0; return; }
    int count = app_message_chunks(text, parts);
    snprintf(out, 800, "%s", parts[0]); free(parts);
    if (count <= 1) return;
    char *last = strrchr(out, '\n'); last = last ? last + 1 : out;
    size_t offsets[200], chars = 0, length = strlen(last);
    int width = 0;
    for (size_t i = 0; i < length && chars < 200;) { size_t n = utf8_length((unsigned char *)last + i); if (!n) { ++i; continue; } offsets[chars++] = i; width += char_width((unsigned char *)last + i, n); i += n; }
    bool removed = false;
    while (width + 22 > 264 && chars) {
        length = offsets[--chars]; width -= char_width((unsigned char *)last + length, utf8_length((unsigned char *)last + length)); last[length] = 0; removed = true;
    }
    if (removed) while (length && ((unsigned char)last[length - 1] < 128) && (isalnum((unsigned char)last[length - 1]) || last[length - 1] == '_')) last[--length] = 0;
    while (length && isspace((unsigned char)last[length - 1])) last[--length] = 0;
    strcat(last, "…");
}
