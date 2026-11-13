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
#include "display_geometry.h"
#include "app_runtime.h"
#include "board.h"
#include <string.h>
#include "waveshare_4inch_init.h"
#include "panel_config.h"
#include "nv3052c_wakeup.h"
#if CONFIG_DISPLAY_TEST_SRAM_ONLY
#include "esp_attr.h"
#include "esp_cpu.h"
#include "sram_gray.h"
static DRAM_ATTR atomic_uint sram_fills, sram_vsyncs, sram_frames, sram_max_fill_cycles;

static bool IRAM_ATTR sram_gray_bounce(esp_lcd_panel_handle_t panel, void *buffer,
                                      int pos_px, int len_bytes, void *context)
{
    unsigned start = esp_cpu_get_cycle_count();
    sram_gray_fill(buffer, (size_t)len_bytes / sizeof(uint16_t));
    unsigned elapsed = esp_cpu_get_cycle_count() - start;
    if (elapsed > atomic_load_explicit(&sram_max_fill_cycles, memory_order_relaxed))
        atomic_store_explicit(&sram_max_fill_cycles, elapsed, memory_order_relaxed);
    atomic_fetch_add_explicit(&sram_fills, 1, memory_order_relaxed);
    return false;
}

static bool IRAM_ATTR sram_gray_vsync(esp_lcd_panel_handle_t panel,
                                     const esp_lcd_rgb_panel_event_data_t *event, void *context)
{
    atomic_fetch_add_explicit(&sram_vsyncs, 1, memory_order_relaxed);
    return false;
}

static bool IRAM_ATTR sram_gray_frame(esp_lcd_panel_handle_t panel,
                                     const esp_lcd_rgb_panel_event_data_t *event, void *context)
{
    atomic_fetch_add_explicit(&sram_frames, 1, memory_order_relaxed);
    return false;
}
#endif

const display_geometry_t display_geometry = {LCD_WIDTH, LCD_HEIGHT};
#define NOTE_YELLOW_RGB565 0xFFB3 /* #FFF59D, quantized to RGB565 */
_Static_assert(LCD_HEIGHT % (2 * LCD_BOUNCE_LINES) == 0,
               "Each frame must contain complete pairs of RGB bounce buffers");

static const char *TAG = "ap24_display";
enum { DISPLAY_PENDING, DISPLAY_INITIALIZING, DISPLAY_INITIALIZED, DISPLAY_FAILED };
static atomic_int state = DISPLAY_PENDING;
static atomic_int last_error = ESP_OK;

#if CONFIG_DISPLAY_COLOR_TEST && !CONFIG_DISPLAY_TEST_SRAM_ONLY
static uint16_t color_test_pixel(int x, int y)
{
#if CONFIG_DISPLAY_TEST_MIDGRAY
    (void)x; (void)y;
    return 0x8410;
#else
    /* Static, full-scale RGB565 words bypass LVGL, PNG and font decoding.
       With the existing 180-degree panel rotation, bars/gray appear reversed.
       White border + alternating one-pixel marks make lost lines visible. */
    static const uint16_t bars[] = {0xf800, 0x07e0, 0x001f, 0xffff, 0x0000, 0x07ff, 0xf81f, 0xffe0};
    if (x < 2 || x >= LCD_WIDTH - 2 || y < 2 || y >= LCD_HEIGHT - 2) return 0xffff;
    if (y < 18) return (x & 1) ? 0xffff : 0;
    if (x < 18) return (y & 1) ? 0xffff : 0;
    if (y < LCD_HEIGHT - 100) return bars[x * 8 / LCD_WIDTH];
    unsigned level = (unsigned)x * 255 / (LCD_WIDTH - 1);
    return ((level >> 3) << 11) | ((level >> 2) << 5) | (level >> 3);
#endif
}
#endif

#if !CONFIG_PANEL_YX40006ACT
static const st7701_lcd_init_cmd_t *panel_init_commands(void)
{
#if CONFIG_BOARD_QUALIA_5800
    /* On Qualia every SPI edge is an I2C transaction. Keep the panel asleep
       while programming its analog/gate settings, then allow 120 ms after
       SLPOUT before DISPON, as in Adafruit's TL040WVS03 example. Preserve all
       Waveshare register values; do not substitute another panel's voltages.
       Storage must outlive this function because ST7701 retains the pointer. */
    enum { count = sizeof(waveshare_4inch_init) / sizeof(waveshare_4inch_init[0]) };
    static st7701_lcd_init_cmd_t commands[count];
    _Static_assert(count > 2, "Panel init requires SLPOUT, configuration and DISPON");
    memcpy(commands, waveshare_4inch_init + 1, (count - 2) * sizeof(commands[0]));
    commands[count - 2] = waveshare_4inch_init[0]; /* SLPOUT + 120 ms */
    commands[count - 1] = waveshare_4inch_init[count - 1]; /* DISPON */
    return commands;
#else
    return waveshare_4inch_init;
#endif
}
#endif

static esp_err_t init_panel(esp_lcd_panel_handle_t *result)
{
    esp_err_t ret = ESP_OK;
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_handle_t panel = NULL;
#if !CONFIG_DISPLAY_TEST_SRAM_ONLY
    void *frame_buffer[2] = {NULL, NULL};
#endif
    ESP_RETURN_ON_FALSE(esp_psram_is_initialized(), ESP_ERR_INVALID_STATE, TAG, "PSRAM unavailable");

    /* Both profiles reserve GPIO19/20 for native USB. Qualia routes LCD
       control through PCA9554A; Waveshare retains direct GPIO control. */
    spi_line_config_t lines;
    ESP_GOTO_ON_ERROR(board_display_prepare(&lines), fail, TAG, "board control init failed");
    esp_lcd_panel_io_3wire_spi_config_t io_config = ST7701_PANEL_IO_3WIRE_SPI_CONFIG(lines, 0);
    ESP_GOTO_ON_ERROR(esp_lcd_new_panel_io_3wire_spi(&io_config, &io), fail, TAG, "3-wire SPI init failed");

    esp_lcd_rgb_panel_config_t rgb = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {
            .pclk_hz = LCD_PCLK_HZ, .h_res = LCD_WIDTH, .v_res = LCD_HEIGHT,
            .hsync_pulse_width = LCD_HSYNC, .hsync_back_porch = LCD_HBP, .hsync_front_porch = LCD_HFP,
            .vsync_pulse_width = LCD_VSYNC, .vsync_back_porch = LCD_VBP, .vsync_front_porch = LCD_VFP,
            .flags.pclk_active_neg = LCD_PCLK_ACTIVE_NEG,
        },
        .data_width = 16, .bits_per_pixel = 16,
#if CONFIG_DISPLAY_TEST_SRAM_ONLY
        .num_fbs = 0, .flags.no_fb = true,
#else
        .num_fbs = 2, .flags.fb_in_psram = true,
#endif
        /* Complete bounce-buffer pairs per frame at both 480 and 720 rows. */
        .bounce_buffer_size_px = LCD_WIDTH * LCD_BOUNCE_LINES, .dma_burst_size = 64,
        .hsync_gpio_num = board_profile.hsync, .vsync_gpio_num = board_profile.vsync,
        .de_gpio_num = board_profile.de, .pclk_gpio_num = board_profile.pclk, .disp_gpio_num = -1,
    };
    memcpy(rgb.data_gpio_nums, board_profile.data, sizeof(board_profile.data));
#if CONFIG_PANEL_YX40006ACT
    ESP_GOTO_ON_ERROR(esp_lcd_new_rgb_panel(&rgb, &panel), fail, TAG, "RGB init failed");
#else
    st7701_vendor_config_t vendor = {
        .rgb_config = &rgb,
        .init_cmds = panel_init_commands(),
        .init_cmds_size = sizeof(waveshare_4inch_init) / sizeof(waveshare_4inch_init[0]),
        .flags.mirror_by_cmd = true,
    };
    esp_lcd_panel_dev_config_t config = {
        .reset_gpio_num = -1, .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16, .vendor_config = &vendor,
    };
    ESP_GOTO_ON_ERROR(esp_lcd_new_panel_st7701(io, &config, &panel), fail, TAG, "ST7701 init failed");
#endif
    ESP_GOTO_ON_ERROR(board_display_reset(), fail, TAG, "board reset failed");
    ESP_GOTO_ON_ERROR(esp_lcd_panel_reset(panel), fail, TAG, "panel reset failed");
#if CONFIG_DISPLAY_TEST_SRAM_ONLY
    const esp_lcd_rgb_panel_event_callbacks_t callbacks = {
        .on_bounce_empty = sram_gray_bounce,
        .on_vsync = sram_gray_vsync,
        .on_frame_buf_complete = sram_gray_frame,
    };
    ESP_GOTO_ON_ERROR(esp_lcd_rgb_panel_register_event_callbacks(panel, &callbacks, NULL),
                      fail, TAG, "SRAM diagnostic callbacks failed");
#else
    ESP_GOTO_ON_ERROR(esp_lcd_rgb_panel_get_frame_buffer(panel, 2, &frame_buffer[0], &frame_buffer[1]), fail, TAG, "framebuffers unavailable");
    /* Both buffers start yellow. The UI paints the inactive one and submits
       it only after a whole frame is ready; RGB swaps at the frame boundary. */
    for (int buffer = 0; buffer < 2; ++buffer) {
        uint16_t *pixels = frame_buffer[buffer];
        for (size_t i = 0; i < LCD_WIDTH * LCD_HEIGHT; ++i) {
#if CONFIG_DISPLAY_COLOR_TEST
            pixels[i] = color_test_pixel(i % LCD_WIDTH, i / LCD_WIDTH);
#else
            pixels[i] = NOTE_YELLOW_RGB565;
#endif
        }
    }
#endif
    ESP_GOTO_ON_ERROR(esp_lcd_panel_init(panel), fail, TAG, "panel initialization failed");
#if CONFIG_PANEL_YX40006ACT
    for (size_t i = 0; i < sizeof(nv3052c_factory_wakeup) / sizeof(nv3052c_factory_wakeup[0]); ++i) {
        const nv3052c_command_t *cmd = &nv3052c_factory_wakeup[i];
        ESP_GOTO_ON_ERROR(esp_lcd_panel_io_tx_param(io, cmd->command,
                          cmd->size ? &cmd->value : NULL, cmd->size), fail, TAG, "NV3052C wake failed");
        if (cmd->delay_ms) vTaskDelay(pdMS_TO_TICKS(cmd->delay_ms));
    }
    ESP_LOGW(TAG, "YX40006ACT uses factory settings; panel-specific init table was not supplied");
#else
    /* Reverse both panel scan axes in ST7701 hardware: 180 degrees without
       rotating/copying the RGB framebuffers or changing LVGL coordinates. */
    ESP_GOTO_ON_ERROR(esp_lcd_panel_mirror(panel, true, true), fail, TAG, "panel rotation failed");
#endif
    ESP_GOTO_ON_ERROR(board_backlight(true), fail, TAG, "backlight enable failed");
    ESP_LOGI(TAG, "Board: %s", board_profile.name);
    ESP_LOGI(TAG, "%s %dx%d initialized; PSRAM=%u bytes", LCD_PANEL_NAME, LCD_WIDTH, LCD_HEIGHT, (unsigned)esp_psram_get_size());
    *result = panel;
    /* The panel and its control IO live for the lifetime of the firmware. */
    return ESP_OK;

fail:
    board_backlight(false);
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
    else {
#if CONFIG_DISPLAY_COLOR_TEST
#if CONFIG_DISPLAY_TEST_SRAM_ONLY
        ESP_LOGI(TAG, "Static gray generated in internal SRAM; no PSRAM framebuffer; app disabled");
#else
        ESP_LOGI(TAG, "Static RGB565 diagnostic: buffers remain immutable, app rendering disabled");
#endif
#else
        app_runtime_run(panel);
#endif
    }
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
    cJSON_AddStringToObject(display, "board", board_profile.id);
    cJSON_AddStringToObject(display, "board_name", board_profile.name);
    cJSON_AddNumberToObject(display, "board_flash_mb", board_profile.flash_mb);
#if CONFIG_BOARD_QUALIA_5800
    cJSON_AddNumberToObject(display, "rgb_independent_data_bits", 16);
    cJSON_AddNumberToObject(display, "rgb_connector_data_bits", 18);
    cJSON_AddStringToObject(display, "rgb_wire_mapping", "rgb565_to_rgb666_rb_lsb_duplicated");
#endif
#if CONFIG_QUALIA_BACKLIGHT_PWM
    cJSON_AddStringToObject(display, "backlight_control", "gpio16_pwm_requires_sj7");
    cJSON_AddNumberToObject(display, "backlight_pwm_hz", 20000);
    cJSON_AddNumberToObject(display, "backlight_requested_percent", CONFIG_QUALIA_BACKLIGHT_PERCENT);
#elif CONFIG_BOARD_QUALIA_5800
    cJSON_AddStringToObject(display, "backlight_control", "expander_on_off");
#endif
#if CONFIG_PANEL_YX40006ACT
    cJSON_AddStringToObject(display, "init_sequence", "nv3052c_factory_settings_dcs_wakeup");
    cJSON_AddBoolToObject(display, "requires_factory_panel_settings", true);
#elif CONFIG_BOARD_QUALIA_5800
    cJSON_AddStringToObject(display, "init_sequence", "configure_then_sleep_out");
#else
    cJSON_AddStringToObject(display, "init_sequence", "waveshare_original");
#endif
    cJSON_AddStringToObject(display, "panel", LCD_PANEL_NAME);
    cJSON_AddStringToObject(display, "panel_id", LCD_PANEL_ID);
    cJSON_AddStringToObject(display, "timing_source", LCD_TIMING_SOURCE);
    cJSON_AddNumberToObject(display, "width", LCD_WIDTH);
    cJSON_AddNumberToObject(display, "height", LCD_HEIGHT);
    cJSON_AddNumberToObject(display, "rotation_degrees", LCD_ROTATION_DEGREES);
    cJSON_AddNumberToObject(display, "hsync_pulse_width", LCD_HSYNC);
    cJSON_AddNumberToObject(display, "hsync_back_porch", LCD_HBP);
    cJSON_AddNumberToObject(display, "hsync_front_porch", LCD_HFP);
    cJSON_AddNumberToObject(display, "vsync_pulse_width", LCD_VSYNC);
    cJSON_AddNumberToObject(display, "vsync_back_porch", LCD_VBP);
    cJSON_AddNumberToObject(display, "vsync_front_porch", LCD_VFP);
    cJSON_AddBoolToObject(display, "pclk_active_neg", LCD_PCLK_ACTIVE_NEG);
#if CONFIG_DISPLAY_TEST_SRAM_ONLY
    cJSON_AddNumberToObject(display, "frame_buffers", 0);
    cJSON_AddNumberToObject(display, "framebuffer_bytes", 0);
    cJSON_AddStringToObject(display, "pixel_source", "internal_sram_generated_gray");
    cJSON_AddBoolToObject(display, "app_disabled_for_diagnostic", true);
    cJSON_AddNumberToObject(display, "sram_bounce_bytes", 2 * LCD_WIDTH * LCD_BOUNCE_LINES * sizeof(uint16_t));
    cJSON_AddNumberToObject(display, "sram_fill_callbacks", atomic_load(&sram_fills));
    cJSON_AddNumberToObject(display, "rgb_vsyncs", atomic_load(&sram_vsyncs));
    cJSON_AddNumberToObject(display, "rgb_frame_completions", atomic_load(&sram_frames));
    cJSON_AddNumberToObject(display, "max_sram_fill_us",
        (double)atomic_load(&sram_max_fill_cycles) / CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ);
#else
    cJSON_AddNumberToObject(display, "frame_buffers", 2);
    cJSON_AddStringToObject(display, "pixel_source", "psram_framebuffer");
#endif
    cJSON_AddNumberToObject(display, "pixel_clock_hz", LCD_PCLK_HZ);
    cJSON_AddNumberToObject(display, "configured_refresh_hz", (double)LCD_PCLK_HZ /
        ((LCD_WIDTH + LCD_HSYNC + LCD_HBP + LCD_HFP) *
         (LCD_HEIGHT + LCD_VSYNC + LCD_VBP + LCD_VFP)));
    cJSON_AddNumberToObject(display, "bounce_lines", LCD_BOUNCE_LINES);
    cJSON_AddNumberToObject(display, "cache_line_bytes", CONFIG_ESP32S3_DATA_CACHE_LINE_SIZE);
    cJSON_AddNumberToObject(display, "data_cache_bytes", CONFIG_ESP32S3_DATA_CACHE_SIZE);
#if CONFIG_LCD_RGB_RESTART_IN_VSYNC
    cJSON_AddStringToObject(display, "restart_policy", "every_vsync");
#else
    cJSON_AddStringToObject(display, "restart_policy", "on_underflow");
#endif
#if CONFIG_LCD_RGB_ISR_IRAM_SAFE
    cJSON_AddBoolToObject(display, "isr_iram_safe", true);
#else
    cJSON_AddBoolToObject(display, "isr_iram_safe", false);
#endif
#if CONFIG_DISPLAY_COLOR_TEST
#if CONFIG_DISPLAY_TEST_MIDGRAY
    cJSON_AddStringToObject(display, "test_pattern", "static_rgb565_midgray_8410");
#else
    cJSON_AddStringToObject(display, "test_pattern", "static_rgb565_bars_gray_grid");
#endif
#else
    cJSON_AddStringToObject(display, "startup_color", "#FFF59D");
#endif
    cJSON_AddNumberToObject(display, "framebuffer_bits_per_pixel", 16);
    cJSON_AddNumberToObject(display, "psram_bytes", esp_psram_get_size());
    cJSON_AddNumberToObject(display, "free_internal_heap", heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
}
