#pragma once

#include "cJSON.h"

/* Initialize the selected board's display on core 1; keep router alive on error. */
void display_start(void);
void display_add_status(cJSON *json);
