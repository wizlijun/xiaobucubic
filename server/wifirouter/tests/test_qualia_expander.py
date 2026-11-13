"""Exercise the actual PCA9554A adapter with a fault-injecting I2C device."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QualiaExpanderTest(unittest.TestCase):
    def test_register_setup_and_i2c_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            (temp / "driver").mkdir()
            (temp / "esp_err.h").write_text('''#pragma once
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_ERR_INVALID_ARG 1
#define ESP_ERR_NO_MEM 2
''')
            (temp / "driver/i2c_master.h").write_text('''#pragma once
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef void *i2c_master_bus_handle_t;
typedef void *i2c_master_dev_handle_t;
typedef struct { int dev_addr_length, device_address, scl_speed_hz; } i2c_device_config_t;
#define I2C_ADDR_BIT_LEN_7 0
esp_err_t i2c_master_probe(void *, uint16_t, int);
esp_err_t i2c_master_bus_add_device(void *, const i2c_device_config_t *, void **);
esp_err_t i2c_master_bus_rm_device(void *);
esp_err_t i2c_master_transmit(void *, const uint8_t *, size_t, int);
esp_err_t i2c_master_transmit_receive(void *, const uint8_t *, size_t, uint8_t *, size_t, int);
''')
            binary = temp / "probe"
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I" + str(temp), "-I" + str(ROOT / "main"),
                "-I" + str(ROOT / "managed_components/espressif__esp_io_expander/include"),
                str(ROOT / "main/qualia_expander.c"), str(ROOT / "tests/qualia_expander_probe.c"),
                "-o", str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)
