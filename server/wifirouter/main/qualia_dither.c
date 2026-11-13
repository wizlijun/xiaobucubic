/* Scoped linker replacement for LVGL 8.3.11's vertical ordered dither.
 * Its stock +/-32-channel noise is much larger than an RGB565 color step.
 * Quantize each high-precision channel to its two neighboring 5/6-bit levels
 * instead. An unchanging 8x8 Bayer pattern provides spatial, not temporal,
 * dithering. Only Qualia's gradient styles opt in; no extra frame copy.
 */
#include "lvgl.h"
#include "src/draw/sw/lv_draw_sw_gradient.h"

static unsigned quantize(unsigned channel, unsigned green, unsigned threshold)
{
    unsigned maximum = green ? 63 : 31;
    return (channel * maximum * 128 + (2 * threshold + 1) * 255) / (255 * 128);
}

_Static_assert(LV_COLOR_DEPTH == 16 && !LV_COLOR_16_SWAP,
               "Qualia dither requires native RGB565");

static const uint8_t thresholds[64] = {
     0, 48, 12, 60,  3, 51, 15, 63,
    32, 16, 44, 28, 35, 19, 47, 31,
     8, 56,  4, 52, 11, 59,  7, 55,
    40, 24, 36, 20, 43, 27, 39, 23,
     2, 50, 14, 62,  1, 49, 13, 61,
    34, 18, 46, 30, 33, 17, 45, 29,
    10, 58,  6, 54,  9, 57,  5, 53,
    42, 26, 38, 22, 41, 25, 37, 21,
};

void __wrap_lv_dither_ordered_ver(lv_grad_t *gradient, lv_coord_t x, lv_coord_t y, lv_coord_t width)
{
    if (!gradient || gradient->size <= 0 || width <= 0) return;
    lv_color32_t color = gradient->hmap[LV_CLAMP(0, y, gradient->size - 1)];
    lv_color_t tile[8];
    for (unsigned i = 0; i < 8; ++i) {
        unsigned threshold = thresholds[((unsigned)y & 7) * 8 + (((unsigned)x + i) & 7)];
        tile[i].full = (quantize(color.ch.red, 0, threshold) << 11)
                     | (quantize(color.ch.green, 1, threshold) << 5)
                     | quantize(color.ch.blue, 0, threshold);
    }
    for (lv_coord_t i = 0; i < width; ++i) gradient->map[i] = tile[i & 7];
}
