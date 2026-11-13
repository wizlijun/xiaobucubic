#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* Packed RGB565 full frame only. The caller owns the inactive buffer.
 * Reverse whole pixels, preserving their bytes and every color bit.
 * Small memcpy operations avoid aliasing assumptions about lv_color_t. */
static inline void frame_rotate_rgb565_180(void *frame, size_t pixels)
{
    uint8_t *data = frame;
    for (size_t i = 0; i < pixels / 2; ++i) {
        size_t opposite = pixels - 1 - i;
        uint16_t first, last;
        memcpy(&first, data + i * 2, sizeof(first));
        memcpy(&last, data + opposite * 2, sizeof(last));
        memcpy(data + i * 2, &last, sizeof(last));
        memcpy(data + opposite * 2, &first, sizeof(first));
    }
}
