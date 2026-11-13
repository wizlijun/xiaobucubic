#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Workspace is two RGB error rows with padding at both ends. */
size_t app_rgb565_error_count(unsigned width);
/* In-place straight RGBA8 -> values that truncate exactly to RGB565.
 * Alpha is unchanged. No temporal changes or full-size extra bitmap. */
bool app_rgb565_dither_rgba(uint8_t *rgba, unsigned width, unsigned height,
                           int32_t *workspace, size_t error_count);
