#pragma once
#include "esp_heap_caps.h"

/* Fonts, PNG decoding and widgets must not exhaust the router/DMA SRAM heap. */
static inline void *app_lv_malloc(size_t size)
{
    return heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
}
static inline void *app_lv_realloc(void *pointer, size_t size)
{
    return heap_caps_realloc(pointer, size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
}
static inline void app_lv_free(void *pointer) { heap_caps_free(pointer); }
