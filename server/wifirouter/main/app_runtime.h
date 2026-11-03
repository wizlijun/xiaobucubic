#pragma once
#include "esp_lcd_panel_ops.h"
#include "cJSON.h"

/* Native C port of ../apps/xiaobucubic; runs on the display task. */
void app_runtime_run(esp_lcd_panel_handle_t panel);
void app_runtime_add_status(cJSON *json);
