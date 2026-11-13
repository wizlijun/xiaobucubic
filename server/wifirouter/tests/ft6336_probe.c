#include <assert.h>
#include "ft6336_touch.h"

int main(void)
{
    display_geometry_t size = {720, 720};
    bool down = false;
    int x = -1, y = -1;
    uint8_t data[] = {1, 0x82, 0xcf, 0x32, 0xcf}; /* Contact, (719,719), ID 3 */
    assert(ft6336_decode(data, size, &down, &x, &y) && down && x == 719 && y == 719);
    assert(display_touch_rotate_180(size, x, y, &x, &y) && x == 0 && y == 0);
    data[2] = 0xd0; /* x=720 must be rejected, not wrapped to the next line. */
    assert(!ft6336_decode(data, size, &down, &x, &y));
    data[1] = 0; data[2] = 0; data[3] = 0; data[4] = 0;
    assert(ft6336_decode(data, size, &down, &x, &y) && down && x == 0 && y == 0);
    data[1] = 0x40; /* Explicit lift, even if TD_STATUS has not reached zero. */
    assert(ft6336_decode(data, size, &down, &x, &y) && !down);
    data[1] = 0xc0;
    assert(!ft6336_decode(data, size, &down, &x, &y));
    data[0] = 0;
    assert(ft6336_decode(data, size, &down, &x, &y) && !down);
    data[0] = 2;
    assert(!ft6336_decode(data, size, &down, &x, &y));
    data[0] = 0xff;
    assert(!ft6336_decode(data, size, &down, &x, &y));
    return 0;
}
