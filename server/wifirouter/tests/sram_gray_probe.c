#include <assert.h>
#include <stdlib.h>
#include "sram_gray.h"

int main(void)
{
    const size_t sizes[] = {0, 1, 3, 720, 720 * 20};
    for (size_t t = 0; t < sizeof(sizes) / sizeof(sizes[0]); ++t) {
        size_t n = sizes[t];
        uint16_t *p = malloc((n + 3) * sizeof(*p));
        assert(p);
        for (size_t i = 0; i < n + 3; ++i) p[i] = 0x1234;
        sram_gray_fill(p + 2, n);
        assert(p[0] == 0x1234 && p[1] == 0x1234 && p[n + 2] == 0x1234);
        for (size_t i = 2; i < n + 2; ++i) assert(p[i] == 0x8410);
        free(p);
    }
    return 0;
}
