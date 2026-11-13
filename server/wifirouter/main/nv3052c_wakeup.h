#pragma once
#include <stdint.h>
#include "panel_config.h"

typedef struct { uint8_t command, value, size; uint16_t delay_ms; } nv3052c_command_t;

/* Standard commands only, from the supplier's NV3052C V0.1 datasheet:
 * pp.43 (Sleep Out), 48 (Display On), 53 (MADCTR), 56 (COLMOD), 73 (page).
 * No unverified analog, gamma or GIP register values from another panel.
 * Sleep Out loads factory settings; that factory configuration must be valid.
 * The Qualia connector presents RGB666 with red/blue LSBs replicated from
 * RGB565, so the physical interface is 18-bit (0x60), NOT 16-bit (0x50).
 * MADCTR uses bits 1/0 for scan reversal, not ST7701's MADCTL bit layout. */
static const nv3052c_command_t nv3052c_factory_wakeup[] = {
    {0xff, 0x30, 1, 0}, {0xff, 0x52, 1, 0}, {0xff, 0x00, 1, 0},
    {0x11, 0x00, 0, 120},
    {0x3a, 0x60, 1, 0},
    {0x36, LCD_ROTATION_DEGREES == 180 ? 0x03 : 0x00, 1, 0},
    {0x29, 0x00, 0, 20},
};
