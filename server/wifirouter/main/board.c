#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_check.h"
#include "board.h"
#include "qualia_expander.h"
#if CONFIG_QUALIA_BACKLIGHT_PWM
#include "driver/ledc.h"
static bool backlight_pwm_ready;

static esp_err_t prepare_backlight_pwm(esp_io_expander_handle_t expander)
{
    /* SJ7 joins GPIO16 and PCA9554A P4 to the same CTRL net. Release P4
     * BEFORE driving GPIO16; never drive these two outputs against each other.
     * The physical SJ7 connection cannot be verified by software. */
    ESP_RETURN_ON_ERROR(esp_io_expander_set_dir(expander, IO_EXPANDER_PIN_NUM_4,
                        IO_EXPANDER_INPUT), "backlight", "release P4 failed");
    const ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE, .timer_num = LEDC_TIMER_0,
        .duty_resolution = LEDC_TIMER_10_BIT, .freq_hz = 20000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_RETURN_ON_ERROR(ledc_timer_config(&timer), "backlight", "PWM timer failed");
    const ledc_channel_config_t channel = {
        .gpio_num = 16, .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0, .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER_0, .duty = 0, .hpoint = 0,
    };
    ESP_RETURN_ON_ERROR(ledc_channel_config(&channel), "backlight", "PWM output failed");
    backlight_pwm_ready = true;
    return ESP_OK;
}
#endif

static const char *TAG = "board";
static i2c_master_bus_handle_t shared_bus;

/* Pin mapping sources:
 * Waveshare LCD Driver Board: original project configuration.
 * Qualia: Adafruit CircuitPython ports/espressif/boards/
 * adafruit_qualia_s3_rgb666/{pins.c,mpconfigboard.h}.
 * The Qualia RGB666 connector is driven with 16 RGB565 GPIOs, as in
 * Adafruit's Arduino demo; red/blue low bits are wired on the PCB. */
#if CONFIG_BOARD_QUALIA_5800
const board_profile_t board_profile = {
    .id = "qualia_5800", .name = "Adafruit Qualia ESP32-S3 RGB666 (5800)",
    .hsync = 41, .vsync = 42, .de = 2, .pclk = 1,
    .data = {40, 39, 38, 0, 45, 48, 47, 21, 14, 13, 12, 11, 10, 9, 46, 3},
    .touch_sda = 8, .touch_scl = 18, .flash_mb = 16,
    .pixel_clock_hz = 8000000,
};
static esp_io_expander_handle_t expander;
#else
const board_profile_t board_profile = {
    .id = "waveshare_lcd", .name = "Waveshare ESP32-S3-LCD-Driver-Board",
    .hsync = 38, .vsync = 39, .de = 40, .pclk = 41,
    .data = {5, 45, 48, 47, 21, 14, 13, 12, 11, 10, 9, 46, 3, 8, 18, 17},
    .touch_sda = 15, .touch_scl = 7, .flash_mb = 8,
    .pixel_clock_hz = 8000000,
};
#endif

esp_err_t board_i2c_get(i2c_master_bus_handle_t *result)
{
    if (!result) return ESP_ERR_INVALID_ARG;
    if (!shared_bus) {
        i2c_master_bus_config_t config = {
            .i2c_port = I2C_NUM_0,
            .sda_io_num = board_profile.touch_sda,
            .scl_io_num = board_profile.touch_scl,
            .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
            .flags.enable_internal_pullup = true,
        };
        ESP_RETURN_ON_ERROR(i2c_new_master_bus(&config, &shared_bus), TAG, "I2C init failed");
    }
    *result = shared_bus;
    return ESP_OK;
}

esp_err_t board_display_prepare(spi_line_config_t *lines)
{
    if (!lines) return ESP_ERR_INVALID_ARG;
#if CONFIG_BOARD_QUALIA_5800
    i2c_master_bus_handle_t bus;
    ESP_RETURN_ON_ERROR(board_i2c_get(&bus), TAG, "Qualia I2C unavailable");
    ESP_RETURN_ON_ERROR(qualia_expander_init(bus, &expander), TAG, "PCA9554A at 0x3f unavailable");
#if CONFIG_QUALIA_BACKLIGHT_PWM
    ESP_RETURN_ON_ERROR(prepare_backlight_pwm(expander), TAG, "backlight PWM init failed");
#endif
    *lines = (spi_line_config_t) {
        .cs_io_type = IO_TYPE_EXPANDER, .cs_expander_pin = IO_EXPANDER_PIN_NUM_1,
        .scl_io_type = IO_TYPE_EXPANDER, .scl_expander_pin = IO_EXPANDER_PIN_NUM_0,
        .sda_io_type = IO_TYPE_EXPANDER, .sda_expander_pin = IO_EXPANDER_PIN_NUM_7,
        .io_expander = expander,
    };
#else
    *lines = (spi_line_config_t) {
        .cs_io_type = IO_TYPE_GPIO, .cs_gpio_num = 42,
        .scl_io_type = IO_TYPE_GPIO, .scl_gpio_num = 2,
        .sda_io_type = IO_TYPE_GPIO, .sda_gpio_num = 1,
    };
#endif
    return ESP_OK;
}

esp_err_t board_display_reset(void)
{
#if CONFIG_BOARD_QUALIA_5800
    ESP_RETURN_ON_ERROR(esp_io_expander_set_level(expander, IO_EXPANDER_PIN_NUM_2, 0), TAG, "reset assert failed");
    vTaskDelay(pdMS_TO_TICKS(20));
    ESP_RETURN_ON_ERROR(esp_io_expander_set_level(expander, IO_EXPANDER_PIN_NUM_2, 1), TAG, "reset release failed");
    vTaskDelay(pdMS_TO_TICKS(120));
#endif
    return ESP_OK;
}

esp_err_t board_backlight(bool on)
{
#if CONFIG_BOARD_QUALIA_5800
    if (!expander) return ESP_ERR_INVALID_STATE;
#if CONFIG_QUALIA_BACKLIGHT_PWM
    if (!backlight_pwm_ready) return ESP_ERR_INVALID_STATE;
    if (!on || CONFIG_QUALIA_BACKLIGHT_PERCENT == 100) {
        return ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, on ? 1 : 0);
    }
    ESP_RETURN_ON_ERROR(ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0,
        (1024U * CONFIG_QUALIA_BACKLIGHT_PERCENT + 50) / 100), TAG, "PWM duty failed");
    return ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
#else
    return esp_io_expander_set_level(expander, IO_EXPANDER_PIN_NUM_4, on);
#endif
#else
    (void)on; /* Original Waveshare configuration has no direct BL control. */
    return ESP_OK;
#endif
}
