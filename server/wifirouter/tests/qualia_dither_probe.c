#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "lvgl.h"
#include "src/draw/sw/lv_draw_sw_gradient.h"

void __wrap_lv_dither_ordered_ver(lv_grad_t *, lv_coord_t, lv_coord_t, lv_coord_t);

static void check_component(unsigned source, unsigned code, unsigned maximum)
{
    double ideal = source * maximum / 255.0;
    assert(code == (unsigned)floor(ideal) || code == (unsigned)ceil(ideal));
}

int main(int argc, char **argv)
{
    lv_color32_t high[256] = {0};
    lv_color_t output[20], repeat[8];
    lv_grad_t gradient = {.hmap = high, .map = output, .size = 8, .alloc_size = 20};
    for (unsigned level = 0; level <= 255; ++level) {
        unsigned red = level, green = (level * 37) % 256, blue = 255 - level;
        for (int y = 0; y < 8; ++y)
            high[y].full = (red << 16) | (green << 8) | blue;
        unsigned sums[3] = {0};
        for (int y = 0; y < 8; ++y) {
            __wrap_lv_dither_ordered_ver(&gradient, 0, y, 8);
            memcpy(repeat, output, sizeof(repeat));
            __wrap_lv_dither_ordered_ver(&gradient, 0, y, 8);
            assert(!memcmp(repeat, output, sizeof(repeat))); /* no temporal change */
            for (int x = 0; x < 8; ++x) {
                unsigned r = output[x].full >> 11, g = (output[x].full >> 5) & 63, b = output[x].full & 31;
                check_component(red, r, 31); check_component(green, g, 63); check_component(blue, b, 31);
                sums[0] += r; sums[1] += g; sums[2] += b;
            }
        }
        assert(fabs(sums[0] * 255.0 / (64 * 31) - red) < .07);
        assert(fabs(sums[1] * 255.0 / (64 * 63) - green) < .07);
        assert(fabs(sums[2] * 255.0 / (64 * 31) - blue) < .07);
    }
    for (int width = 1; width <= 17; ++width) {
        for (int i = 0; i < 20; ++i) output[i].full = 0x1234;
        __wrap_lv_dither_ordered_ver(&gradient, 3, 4, width);
        for (int i = width; i < 20; ++i) assert(output[i].full == 0x1234);
    }
    high[0].full = 0;
    high[7].full = 0xffffff;
    __wrap_lv_dither_ordered_ver(&gradient, 0, 0, 8);
    for (int i = 0; i < 8; ++i) assert(output[i].full == 0);
    __wrap_lv_dither_ordered_ver(&gradient, 0, 7, 8);
    for (int i = 0; i < 8; ++i) assert(output[i].full == 0xffff);
    __wrap_lv_dither_ordered_ver(&gradient, 0, 8, 8); /* clamp at final gradient entry */
    for (int i = 0; i < 8; ++i) assert(output[i].full == 0xffff);

    /* Optional dark-ramp preview: plain RGB565 on left, dither on right. */
    if (argc == 2) {
        FILE *image = fopen(argv[1], "wb"); assert(image);
        fprintf(image, "P6\n256 256\n255\n");
        for (int y = 0; y < 256; ++y) {
            unsigned value = 5 + y / 4;
            high[y].full = (value << 16) | (value << 8) | value;
        }
        gradient.size = 256;
        for (int y = 0; y < 256; ++y) {
            __wrap_lv_dither_ordered_ver(&gradient, 0, y, 8);
            for (int x = 0; x < 256; ++x) {
                lv_color_t pixel = x < 128 ? lv_color_hex(high[y].full) : output[x & 7];
                lv_color32_t expanded = {.full = lv_color_to32(pixel)};
                fputc(expanded.ch.red, image); fputc(expanded.ch.green, image); fputc(expanded.ch.blue, image);
            }
        }
        fclose(image);
    }
    puts("RGB565 adjacent levels, tile means, endpoints, determinism and bounds passed");
    return 0;
}
