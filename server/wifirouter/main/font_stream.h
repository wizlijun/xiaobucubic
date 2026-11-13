#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* Caller owns the file and cache. Absolute seeks keep LVGL's small reads cheap
 * without retaining a second complete copy of a font in PSRAM. */
typedef struct {
    FILE *file;
    uint8_t *cache;
    uint32_t size, position, capacity, start, length;
} font_stream_t;

static inline bool font_stream_seek(font_stream_t *s, uint64_t position)
{
    if (position > s->size) return false;
    s->position = (uint32_t)position;
    return true;
}

static inline bool font_stream_read(font_stream_t *s, void *buffer,
                                    uint32_t count, uint32_t *read)
{
    *read = 0;
    if (!s->capacity || s->position > s->size) return false;
    uint32_t remaining = s->size - s->position;
    if (count > remaining) count = remaining;
    while (*read < count) {
        if (!s->length || s->position < s->start || s->position - s->start >= s->length) {
            s->start = s->position;
            s->length = 0;
            if (fseek(s->file, s->start, SEEK_SET)) return false;
            uint32_t chunk = s->size - s->start;
            if (chunk > s->capacity) chunk = s->capacity;
            s->length = fread(s->cache, 1, chunk, s->file);
            if (s->length != chunk) return false;
        }
        uint32_t offset = s->position - s->start;
        uint32_t chunk = s->length - offset;
        if (chunk > count - *read) chunk = count - *read;
        memcpy((uint8_t *)buffer + *read, s->cache + offset, chunk);
        s->position += chunk;
        *read += chunk;
    }
    return true;
}
