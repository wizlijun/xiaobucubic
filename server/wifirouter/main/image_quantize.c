#include "image_quantize.h"
#include <string.h>

size_t app_rgb565_error_count(unsigned width)
{
    if (!width || width > 4096) return 0;
    return ((size_t)width + 2) * 6;
}

bool app_rgb565_dither_rgba(uint8_t *rgba, unsigned width, unsigned height,
                           int32_t *workspace, size_t error_count)
{
    size_t required = app_rgb565_error_count(width);
    if (!rgba || !workspace || !required || !height || error_count < required ||
        (size_t)height > SIZE_MAX / 4 / width) return false;
    size_t row_size = required / 2;
    memset(workspace, 0, required * sizeof(*workspace));
    int32_t *current = workspace, *next = workspace + row_size;
    for (unsigned y = 0; y < height; ++y) {
        int direction = (y & 1) ? -1 : 1;
        for (unsigned i = 0; i < width; ++i) {
            unsigned x = direction > 0 ? i : width - 1 - i;
            uint8_t *pixel = rgba + ((size_t)y * width + x) * 4;
            if (!pixel[3]) continue; /* Invisible RGB must not color its neighbors. */
            size_t offset = ((size_t)x + 1) * 3;
            for (unsigned c = 0; c < 3; ++c) {
                unsigned maximum = c == 1 ? 63 : 31;
                unsigned original = pixel[c];
                int corrected = (int)original * 16 + current[offset + c];
                if (corrected < 0) corrected = 0;
                if (corrected > 255 * 16) corrected = 255 * 16;
                unsigned code = (corrected * maximum + 255 * 8) / (255 * 16);
                /* Keep contrast noise within the two neighboring RGB565 codes. */
                unsigned low = original * maximum / 255;
                unsigned high = (original * maximum + 254) / 255;
                if (code < low) code = low;
                if (code > high) code = high;
                pixel[c] = code << (c == 1 ? 2 : 3);
                int represented = (code * 255 * 16 + maximum / 2) / maximum;
                int error = corrected - represented;
                /* Serpentine Floyd-Steinberg: all errors are in 1/16 intensity units. */
                current[(int)offset + direction * 3 + c] += error * 7 / 16;
                next[(int)offset - direction * 3 + c] += error * 3 / 16;
                next[offset + c] += error * 5 / 16;
                next[(int)offset + direction * 3 + c] += error / 16;
            }
        }
        int32_t *previous = current; current = next; next = previous;
        memset(next, 0, row_size * sizeof(*next));
    }
    return true;
}
