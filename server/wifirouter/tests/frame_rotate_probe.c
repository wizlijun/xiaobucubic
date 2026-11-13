#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "frame_rotate.h"

static void check_size(size_t width, size_t height)
{
    size_t count = width * height;
    uint16_t *storage = malloc((count + 2) * sizeof(*storage));
    uint16_t *original = malloc((count ? count : 1) * sizeof(*original));
    assert(storage && original);
    storage[0] = 0x1357; storage[count + 1] = 0x2468;
    uint16_t *image = storage + 1;
    for (size_t y = 0; y < height; ++y)
        for (size_t x = 0; x < width; ++x)
            original[y * width + x] = image[y * width + x] = (uint16_t)(y * 7919 + x * 31);
    frame_rotate_rgb565_180(image, count);
    for (size_t y = 0; y < height; ++y)
        for (size_t x = 0; x < width; ++x)
            assert(image[y * width + x] == original[(height - 1 - y) * width + width - 1 - x]);
    assert(storage[0] == 0x1357 && storage[count + 1] == 0x2468);
    frame_rotate_rgb565_180(image, count);
    assert(memcmp(image, original, count * sizeof(*image)) == 0);
    free(original); free(storage);
}

int main(void)
{
    /* A labeled 3x2 rectangle checks both axes, not a mirror/transpose.
       The colors also expose channel or byte swapping. */
    uint16_t image[] = {0xf800, 0x07e0, 0x001f, 0x0000, 0x8410, 0xffff};
    const uint16_t expected[] = {0xffff, 0x8410, 0x0000, 0x001f, 0x07e0, 0xf800};
    frame_rotate_rgb565_180(image, 6);
    assert(memcmp(image, expected, sizeof(image)) == 0);
    frame_rotate_rgb565_180(NULL, 0);
    check_size(0, 0); check_size(1, 1); check_size(1, 7); check_size(7, 1);
    check_size(3, 5); check_size(480, 480); check_size(720, 720);
    return 0;
}
