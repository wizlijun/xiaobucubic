#pragma once
#include "driver/i2c_master.h"
#include "esp_io_expander.h"

/* PCA9554A, default Qualia address 0x3f. Pins 3/5/6 remain inputs.
 * The display task exclusively owns all output read/modify/write calls. */
esp_err_t qualia_expander_init(i2c_master_bus_handle_t bus, esp_io_expander_handle_t *result);
