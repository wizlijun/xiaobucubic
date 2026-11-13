#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <math.h>

/* Physical panel dimensions; the application retains its 320x240 layout. */
typedef struct { int width, height; } display_geometry_t;
extern const display_geometry_t display_geometry;

static inline int display_layout_x(display_geometry_t size, double x)
{
    return (int)floor(x * size.width / 320.0 + .5);
}

static inline int display_layout_y(display_geometry_t size, double y)
{
    return (int)floor(y * size.height / 240.0 + .5);
}

static inline size_t display_frame_pixels(display_geometry_t size)
{
    return (size_t)size.width * size.height;
}

/* Preserve the physical proportions of pixel-based styling on a 480px UI. */
static inline int display_scale_480(int extent, int pixels)
{
    return (pixels * extent + 240) / 480;
}

static inline bool display_touch_rotate_180(display_geometry_t size,
                                           int raw_x, int raw_y, int *x, int *y)
{
    if (raw_x < 0 || raw_y < 0 || raw_x >= size.width || raw_y >= size.height) return false;
    *x = size.width - 1 - raw_x;
    *y = size.height - 1 - raw_y;
    return true;
}

/* Keep the existing edge-tap targets at the same fraction of the panel. */
static inline int display_tap_key(display_geometry_t size, int x, int y)
{
    return y > display_scale_480(size.height, 430) ? 5 :
           x < display_scale_480(size.width, 70) ? 2 :
           x > display_scale_480(size.width, 410) ? 3 : 4;
}
