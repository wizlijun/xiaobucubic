#pragma once

#include "cJSON.h"

/* Initialize the Waveshare 4-inch ST7701 on core 1; never stop the router on error. */
void display_start(void);
void display_add_status(cJSON *json);
