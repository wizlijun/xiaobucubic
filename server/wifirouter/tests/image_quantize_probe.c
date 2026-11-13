#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "image_quantize.h"

enum { WIDTH = 128, HEIGHT = 64 };
static uint8_t pixels[WIDTH * HEIGHT * 4], duplicate[sizeof(pixels)];

int main(void)
{
    size_t count = app_rgb565_error_count(WIDTH);
    int32_t *rows = malloc(count * sizeof(*rows)); assert(rows);
    double diffuse_error = 0, truncation_error = 0;
    for (unsigned level = 0; level < 256; ++level) {
        unsigned channels[] = {level, (level * 37) % 256, 255 - level};
        for (unsigned i = 0; i < WIDTH * HEIGHT; ++i) {
            for (unsigned c = 0; c < 3; ++c) pixels[i * 4 + c] = channels[c];
            pixels[i * 4 + 3] = 255;
        }
        memcpy(duplicate, pixels, sizeof(pixels));
        assert(app_rgb565_dither_rgba(pixels, WIDTH, HEIGHT, rows, count));
        assert(app_rgb565_dither_rgba(duplicate, WIDTH, HEIGHT, rows, count));
        assert(!memcmp(pixels, duplicate, sizeof(pixels)));
        for (unsigned c = 0; c < 3; ++c) {
            unsigned maximum = c == 1 ? 63 : 31, shift = c == 1 ? 2 : 3;
            unsigned sum = 0;
            for (unsigned i = 0; i < WIDTH * HEIGHT; ++i) {
                unsigned code = pixels[i * 4 + c] >> shift;
                assert(code == channels[c] * maximum / 255 || code == (channels[c] * maximum + 254) / 255);
                assert(pixels[i * 4 + 3] == 255);
                sum += code;
            }
            double error = fabs(sum * 255.0 / (WIDTH * HEIGHT * maximum) - channels[c]);
            assert(error < 0.4);
            diffuse_error += error;
            truncation_error += fabs((channels[c] >> shift) * 255.0 / maximum - channels[c]);
        }
    }
    assert(diffuse_error < truncation_error / 5);
    /* Odd widths, alpha values and both serpentine directions. */
    for (unsigned width = 1; width <= 17; ++width) {
        for (unsigned i = 0; i < width * 7; ++i) {
            pixels[i * 4] = i * 31; pixels[i * 4 + 1] = i * 73;
            pixels[i * 4 + 2] = i * 29; pixels[i * 4 + 3] = i * 17;
        }
        memcpy(duplicate, pixels, sizeof(pixels));
        assert(app_rgb565_dither_rgba(pixels, width, 7, rows, count));
        for (unsigned i = 0; i < width * 7; ++i) {
            assert(pixels[i * 4 + 3] == duplicate[i * 4 + 3]);
            if (!duplicate[i * 4 + 3]) assert(!memcmp(pixels + i * 4, duplicate + i * 4, 4));
        }
        assert(!memcmp(pixels + width * 7 * 4, duplicate + width * 7 * 4, sizeof(pixels) - width * 7 * 4));
    }
    assert(!app_rgb565_dither_rgba(pixels, WIDTH, HEIGHT, rows, count - 1));
    assert(!app_rgb565_dither_rgba(pixels, 0, HEIGHT, rows, count));
    assert(!app_rgb565_error_count(4097));
    printf("RGB565 mean channel error: diffusion=%.4f, truncation=%.4f; alpha and bounds passed\n",
           diffuse_error / 768, truncation_error / 768);
    free(rows);
    return 0;
}
