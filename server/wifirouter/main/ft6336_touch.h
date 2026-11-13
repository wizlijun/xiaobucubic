#pragma once
#include <stdint.h>
#include "display_geometry.h"

/* A coherent 5-byte read starting at TD_STATUS (0x02).
 * Return false for malformed/multi-touch frames; never invent a release. */
static inline bool ft6336_decode(const uint8_t data[5], display_geometry_t size,
                                 bool *down, int *x, int *y)
{
    unsigned count = data[0] & 0x0f;
    if (count > 2) return false;
    if (count == 0) { *down = false; return true; }
    if (count != 1) return false;
    unsigned event = data[1] >> 6;
    if (event == 3) return false;
    if (event == 1) { *down = false; return true; }
    int raw_x = ((data[1] & 0x0f) << 8) | data[2];
    int raw_y = ((data[3] & 0x0f) << 8) | data[4];
    if (raw_x >= size.width || raw_y >= size.height) return false;
    *down = true; *x = raw_x; *y = raw_y;
    return true;
}
