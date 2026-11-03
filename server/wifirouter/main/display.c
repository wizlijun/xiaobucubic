#include <stdatomic.h>
#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_lcd_panel_io_additions.h"
#include "esp_lcd_st7701.h"
#include "esp_psram.h"
#include "display.h"
#include "app_runtime.h"
#include "waveshare_4inch_init.h"

#define LCD_WIDTH 480
#define LCD_HEIGHT 480
#define LCD_PCLK_HZ (8 * 1000 * 1000)
#define LCD_BOUNCE_LINES 20
#define NOTE_YELLOW_RGB565 0xFFB3 /* #FFF59D, quantized to RGB565 */

static const char *TAG = "ap24_display";
enum { DISPLAY_PENDING, DISPLAY_INITIALIZING, DISPLAY_INITIALIZED, DISPLAY_FAILED };
static atomic_int state = DISPLAY_PENDING;
static atomic_int last_error = ESP_OK;

static esp_err_t init_panel(esp_lcd_panel_handle_t *result)
{
    esp_err_t ret = ESP_OK;
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_handle_t panel = NULL;
    void *frame_buffer[2] = {NULL, NULL};
    ESP_RETURN_ON_FALSE(esp_psram_is_initialized(), ESP_ERR_INVALID_STATE, TAG, "PSRAM unavailable");

    /* Waveshare 40-pin RGB connector; GPIO19/20 stay reserved for native USB.
       No direct backlight/reset GPIO in the official 4-inch configuration. */
    spi_line_config_t lines = {
        .cs_io_type = IO_TYPE_GPIO, .cs_gpio_num = 42,
        .scl_io_type = IO_TYPE_GPIO, .scl_gpio_num = 2,
        .sda_io_type = IO_TYPE_GPIO, .sda_gpio_num = 1,
    };
    esp_lcd_panel_io_3wire_spi_config_t io_config = ST7701_PANEL_IO_3WIRE_SPI_CONFIG(lines, 0);
    ESP_GOTO_ON_ERROR(esp_lcd_new_panel_io_3wire_spi(&io_config, &io), fail, TAG, "3-wire SPI init failed");

    esp_lcd_rgb_panel_config_t rgb = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {
            .pclk_hz = LCD_PCLK_HZ, .h_res = LCD_WIDTH, .v_res = LCD_HEIGHT,
            .hsync_pulse_width = 8, .hsync_back_porch = 10, .hsync_front_porch = 50,
            .vsync_pulse_width = 3, .vsync_back_porch = 8, .vsync_front_porch = 8,
            .flags.pclk_active_neg = false,
        },
        .data_width = 16, .bits_per_pixel = 16, .num_fbs = 2,
        /* More time to refill SRAM during font/PNG reads and USB traffic.
           8 MHz still scans the full panel at about 29 frames/second. */
        .bounce_buffer_size_px = LCD_WIDTH * LCD_BOUNCE_LINES, .dma_burst_size = 64,
        .hsync_gpio_num = 38, .vsync_gpio_num = 39, .de_gpio_num = 40,
        .pclk_gpio_num = 41, .disp_gpio_num = -1,
        .data_gpio_nums = {5, 45, 48, 47, 21, 14, 13, 12, 11, 10, 9, 46, 3, 8, 18, 17},
        .flags.fb_in_psram = true,
    };
    st7701_vendor_config_t vendor = {
        .rgb_config = &rgb,
        .init_cmds = waveshare_4inch_init,
        .init_cmds_size = sizeof(waveshare_4inch_init) / sizeof(waveshare_4inch_init[0]),
        .flags.mirror_by_cmd = true,
    };
    esp_lcd_panel_dev_config_t config = {
        .reset_gpio_num = -1, .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16, .vendor_config = &vendor,
    };
    ESP_GOTO_ON_ERROR(esp_lcd_new_panel_st7701(io, &config, &panel), fail, TAG, "ST7701 init failed");
    ESP_GOTO_ON_ERROR(esp_lcd_panel_reset(panel), fail, TAG, "panel reset failed");
    ESP_GOTO_ON_ERROR(esp_lcd_rgb_panel_get_frame_buffer(panel, 2, &frame_buffer[0], &frame_buffer[1]), fail, TAG, "framebuffers unavailable");
    /* Both buffers start yellow. The UI paints the inactive one and submits
       it only after a whole frame is ready; RGB swaps at the frame boundary. */
    for (int buffer = 0; buffer < 2; ++buffer) {
        uint16_t *pixels = frame_buffer[buffer];
        for (size_t i = 0; i < LCD_WIDTH * LCD_HEIGHT; ++i) pixels[i] = NOTE_YELLOW_RGB565;
    }
    ESP_GOTO_ON_ERROR(esp_lcd_panel_init(panel), fail, TAG, "panel initialization failed");
    /* Reverse both panel scan axes in ST7701 hardware: 180 degrees without
       rotating/copying the RGB framebuffers or changing LVGL coordinates. */
    ESP_GOTO_ON_ERROR(esp_lcd_panel_mirror(panel, true, true), fail, TAG, "panel rotation failed");
    ESP_LOGI(TAG, "ST7701 480x480 initialized, #FFF59D; PSRAM=%u bytes", (unsigned)esp_psram_get_size());
    *result = panel;
    /* The panel and its control IO live for the lifetime of the firmware. */
    return ESP_OK;

fail:
    if (panel) esp_lcd_panel_del(panel);
    if (io) esp_lcd_panel_io_del(io);
    return ret;
}

static void display_task(void *arg)
{
    atomic_store(&state, DISPLAY_INITIALIZING);
    esp_lcd_panel_handle_t panel = NULL;
    esp_err_t err = init_panel(&panel);
    atomic_store(&last_error, err);
    atomic_store(&state, err == ESP_OK ? DISPLAY_INITIALIZED : DISPLAY_FAILED);
    if (err != ESP_OK) ESP_LOGE(TAG, "Display unavailable (%s); router continues", esp_err_to_name(err));
    else app_runtime_run(panel);
    vTaskDelete(NULL);
}

void display_start(void)
{
    /* Allocate the RGB DMA interrupt on core 1, separate from Wi-Fi on core 0. */
    if (xTaskCreatePinnedToCore(display_task, "display_app", 12288, NULL, 3, NULL, 1) != pdPASS) {
        atomic_store(&last_error, ESP_ERR_NO_MEM);
        atomic_store(&state, DISPLAY_FAILED);
        ESP_LOGE(TAG, "Cannot start display task; router continues");
    }
}

void display_add_status(cJSON *json)
{
    static const char *const names[] = {"pending", "initializing", "initialized", "failed"};
    cJSON *display = cJSON_AddObjectToObject(json, "display");
    if (!display) return;
    cJSON_AddStringToObject(display, "state", names[atomic_load(&state)]);
    cJSON_AddStringToObject(display, "error", esp_err_to_name(atomic_load(&last_error)));
    cJSON_AddStringToObject(display, "panel", "Waveshare 4inch ST7701");
    cJSON_AddNumberToObject(display, "width", LCD_WIDTH);
    cJSON_AddNumberToObject(display, "height", LCD_HEIGHT);
    cJSON_AddNumberToObject(display, "rotation_degrees", 180);
    cJSON_AddNumberToObject(display, "frame_buffers", 2);
    cJSON_AddNumberToObject(display, "pixel_clock_hz", LCD_PCLK_HZ);
    cJSON_AddNumberToObject(display, "bounce_lines", LCD_BOUNCE_LINES);
    cJSON_AddNumberToObject(display, "cache_line_bytes", CONFIG_ESP32S3_DATA_CACHE_LINE_SIZE);
#if CONFIG_LCD_RGB_ISR_IRAM_SAFE
    cJSON_AddBoolToObject(display, "isr_iram_safe", true);
#else
    cJSON_AddBoolToObject(display, "isr_iram_safe", false);
#endif
    cJSON_AddStringToObject(display, "startup_color", "#FFF59D");
    cJSON_AddNumberToObject(display, "psram_bytes", esp_psram_get_size());
    cJSON_AddNumberToObject(display, "free_internal_heap", heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
}
