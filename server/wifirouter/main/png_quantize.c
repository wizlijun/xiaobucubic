#include <stdlib.h>
#include "esp_heap_caps.h"
#include "image_quantize.h"

unsigned __real_lodepng_decode32(unsigned char **out, unsigned *width, unsigned *height,
                                const unsigned char *input, size_t size);

/* LVGL's PNG adapter subsequently packs these RGBA bytes into RGB565+alpha.
 * Quantize before that packing loses the original 8-bit channel precision. */
unsigned __wrap_lodepng_decode32(unsigned char **out, unsigned *width, unsigned *height,
                                const unsigned char *input, size_t size)
{
    unsigned error = __real_lodepng_decode32(out, width, height, input, size);
    if (error || !*out) return error;
    size_t count = app_rgb565_error_count(*width);
    int32_t *rows = count ? heap_caps_calloc(count, sizeof(*rows), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) : NULL;
    if (rows) {
        app_rgb565_dither_rgba(*out, *width, *height, rows, count);
        free(rows);
    }
    return error;
}
