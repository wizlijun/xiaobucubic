#pragma once
#include <stddef.h>
#include <stdint.h>

/* DMA bounce buffers are at least 4-byte aligned. Fill two RGB565 pixels per
 * write; volatile prevents conversion into a library call outside IRAM. */
typedef uint32_t __attribute__((__may_alias__)) sram_gray_word_t;
static inline __attribute__((always_inline)) void sram_gray_fill(void *buffer, size_t pixels)
{
    volatile sram_gray_word_t *out = buffer;
    for (size_t i = 0; i < pixels / 2; ++i) out[i] = 0x84108410U;
    if (pixels & 1) ((volatile uint16_t *)buffer)[pixels - 1] = 0x8410;
}
