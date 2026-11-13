#pragma once
#include "sdkconfig.h"

/* The supplier confirmed timing.png on 2026-11-13; this is the default.
 * The differing text-file timing remains available for explicit comparison. */
#if CONFIG_PANEL_YX40006ACT
#if CONFIG_YX40006ACT_ROTATE_180
#define LCD_ROTATION_DEGREES 180
#else
#define LCD_ROTATION_DEGREES 0
#endif
#define LCD_WIDTH 720
#define LCD_HEIGHT 720
#define LCD_PANEL_ID "yx40006act"
#define LCD_PANEL_NAME "Yousee YX40006ACT NV3052C"
#define LCD_PCLK_HZ CONFIG_YX40006ACT_PCLK_HZ
#if CONFIG_YX40006ACT_REFERENCE_TIMING
#define LCD_TIMING_SOURCE "supplier_reference_png"
#define LCD_HSYNC 2
#define LCD_HBP 44
#define LCD_HFP 46
#define LCD_VSYNC 2
#define LCD_VBP 18
#define LCD_VFP 16
#else
#define LCD_TIMING_SOURCE "40006a_timing_txt"
#define LCD_HSYNC 6
#define LCD_HBP 25
#define LCD_HFP 25
#define LCD_VSYNC 2
#define LCD_VBP 17
#define LCD_VFP 20
#endif
#ifdef CONFIG_YX40006ACT_PCLK_ACTIVE_NEG
#define LCD_PCLK_ACTIVE_NEG true
#else
#define LCD_PCLK_ACTIVE_NEG false
#endif
#else
#define LCD_ROTATION_DEGREES 180
#define LCD_WIDTH 480
#define LCD_HEIGHT 480
#define LCD_PANEL_ID "waveshare_st7701"
#define LCD_PANEL_NAME "Waveshare 4inch ST7701"
#define LCD_TIMING_SOURCE "original_st7701"
#define LCD_PCLK_HZ CONFIG_ST7701_PCLK_HZ
#define LCD_HSYNC 8
#define LCD_HBP 10
#define LCD_HFP 50
#define LCD_VSYNC 3
#define LCD_VBP 8
#define LCD_VFP 8
#define LCD_PCLK_ACTIVE_NEG false
#endif
#define LCD_BOUNCE_LINES 20
