#pragma once
#include "lvgl.h"

/* 3:2 raster scaling preserves the existing 7,215-character fonts and flash
 * partition. Drawing is serialized by the single LVGL task. */
void app_font_scale_150(lv_font_t *target, const lv_font_t *source);
