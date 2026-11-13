#pragma once

#include "driver/i2c_master.h"
#include "esp_lcd_panel_io_additions.h"

typedef struct {
    const char *id;
    const char *name;
    int hsync, vsync, de, pclk;
    int data[16]; /* RGB565, least-significant blue bit first. */
    int touch_sda, touch_scl;
    int flash_mb;
    int pixel_clock_hz;
} board_profile_t;

extern const board_profile_t board_profile;

/* Board owns the shared I2C bus for the lifetime of the application.
 * Call from the display task; touch must not delete this bus. */
esp_err_t board_i2c_get(i2c_master_bus_handle_t *result);
esp_err_t board_display_prepare(spi_line_config_t *lines);
esp_err_t board_display_reset(void);
esp_err_t board_backlight(bool on);
