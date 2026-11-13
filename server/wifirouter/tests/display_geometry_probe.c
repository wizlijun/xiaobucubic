#include <assert.h>
#include "display_geometry.h"

int main(void)
{
    const display_geometry_t old = {480, 480}, large = {720, 720};
    /* Legacy layout and touch targets must remain pixel-for-pixel identical. */
    for (int x = 0; x <= 320; ++x)
        assert(display_layout_x(old, x) == (int)floor(x * 1.5 + .5));
    for (int y = 0; y <= 240; ++y)
        assert(display_layout_y(old, y) == y * 2);
    for (int x = 0; x < 480; ++x) for (int y = 0; y < 480; ++y)
        assert(display_tap_key(old, x, y) == (y > 430 ? 5 : x < 70 ? 2 : x > 410 ? 3 : 4));

    assert(display_layout_x(large, 320) == 720);
    assert(display_layout_y(large, 240) == 720);
    assert(display_layout_x(large, 160) == 360);
    assert(display_layout_y(large, 120) == 360);
    assert(display_frame_pixels(old) * sizeof(unsigned short) == 460800);
    assert(display_frame_pixels(large) * sizeof(unsigned short) == 1036800);
    assert(display_scale_480(large.width, 50) == 75);
    assert(display_tap_key(large, 104, 360) == 2);
    assert(display_tap_key(large, 105, 360) == 4);
    assert(display_tap_key(large, 615, 360) == 4);
    assert(display_tap_key(large, 616, 360) == 3);
    assert(display_tap_key(large, 360, 645) == 4);
    assert(display_tap_key(large, 360, 646) == 5);

    const display_geometry_t sizes[] = {old, large};
    for (unsigned i = 0; i < sizeof(sizes) / sizeof(sizes[0]); ++i) {
        display_geometry_t size = sizes[i];
        int x, y, rx, ry;
        for (int raw_x = 0; raw_x < size.width; ++raw_x)
            for (int raw_y = 0; raw_y < size.height; ++raw_y) {
                assert(display_touch_rotate_180(size, raw_x, raw_y, &x, &y));
                assert(x >= 0 && x < size.width && y >= 0 && y < size.height);
                assert(display_touch_rotate_180(size, x, y, &rx, &ry));
                assert(rx == raw_x && ry == raw_y);
            }
        assert(!display_touch_rotate_180(size, size.width, 0, &x, &y));
        assert(!display_touch_rotate_180(size, 0, size.height, &x, &y));
        assert(!display_touch_rotate_180(size, -1, 0, &x, &y));
        assert(!display_touch_rotate_180(size, 0, -1, &x, &y));
    }
    return 0;
}
