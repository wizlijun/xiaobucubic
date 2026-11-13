#include <stdlib.h>
#include "qualia_expander.h"

/* PCA9554A register layout: input=0, output=1, polarity=2, direction=3.
 * Adapter for ESP-IDF's existing 3-wire SPI IO; uses the new I2C master
 * API so touch and LCD control can safely share one bus. */
typedef struct {
    esp_io_expander_t base;
    i2c_master_dev_handle_t device;
    uint8_t output, direction;
} qualia_expander_t;

static esp_err_t write_byte(qualia_expander_t *dev, uint8_t reg, uint8_t value)
{
    const uint8_t bytes[] = {reg, value};
    return i2c_master_transmit(dev->device, bytes, sizeof(bytes), 100);
}
static esp_err_t read_input(esp_io_expander_handle_t handle, uint32_t *value)
{
    qualia_expander_t *dev = (qualia_expander_t *)handle;
    uint8_t reg = 0, data = 0;
    esp_err_t err = i2c_master_transmit_receive(dev->device, &reg, 1, &data, 1, 100);
    if (err == ESP_OK) *value = data;
    return err;
}
static esp_err_t read_output(esp_io_expander_handle_t handle, uint32_t *value)
{
    *value = ((qualia_expander_t *)handle)->output;
    return ESP_OK;
}
static esp_err_t read_direction(esp_io_expander_handle_t handle, uint32_t *value)
{
    *value = ((qualia_expander_t *)handle)->direction;
    return ESP_OK;
}
static esp_err_t write_output(esp_io_expander_handle_t handle, uint32_t value)
{
    qualia_expander_t *dev = (qualia_expander_t *)handle;
    esp_err_t err = write_byte(dev, 1, value);
    if (err == ESP_OK) dev->output = value;
    return err;
}
static esp_err_t write_direction(esp_io_expander_handle_t handle, uint32_t value)
{
    qualia_expander_t *dev = (qualia_expander_t *)handle;
    esp_err_t err = write_byte(dev, 3, value);
    if (err == ESP_OK) dev->direction = value;
    return err;
}
static esp_err_t reset(esp_io_expander_handle_t handle)
{
    qualia_expander_t *dev = (qualia_expander_t *)handle;
    /* Release all outputs first, preload CS/reset high and BL/clock low,
     * then enable outputs. Keep touch IRQ and UP/DN button pins as inputs. */
    esp_err_t err = write_direction(handle, 0xff);
    if (err != ESP_OK) return err;
    err = write_output(handle, 0xe6);
    if (err != ESP_OK) return err;
    err = write_byte(dev, 2, 0);
    if (err != ESP_OK) return err;
    return write_direction(handle, 0x68);
}
static esp_err_t destroy(esp_io_expander_handle_t handle)
{
    qualia_expander_t *dev = (qualia_expander_t *)handle;
    esp_err_t err = i2c_master_bus_rm_device(dev->device);
    if (err == ESP_OK) free(dev);
    return err;
}
esp_err_t qualia_expander_init(i2c_master_bus_handle_t bus, esp_io_expander_handle_t *result)
{
    if (!bus || !result) return ESP_ERR_INVALID_ARG;
    *result = NULL;
    esp_err_t err = i2c_master_probe(bus, 0x3f, 100);
    if (err != ESP_OK) return err;
    qualia_expander_t *dev = calloc(1, sizeof(*dev));
    if (!dev) return ESP_ERR_NO_MEM;
    dev->base = (esp_io_expander_t) {
        .read_input_reg = read_input, .read_output_reg = read_output,
        .write_output_reg = write_output, .read_direction_reg = read_direction,
        .write_direction_reg = write_direction, .reset = reset, .del = destroy,
        .config = {.io_count = 8, .flags.dir_out_bit_zero = 1},
    };
    i2c_device_config_t config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = 0x3f,
        .scl_speed_hz = 400000,
    };
    err = i2c_master_bus_add_device(bus, &config, &dev->device);
    if (err != ESP_OK) { free(dev); return err; }
    err = reset(&dev->base);
    if (err != ESP_OK) { destroy(&dev->base); return err; }
    *result = &dev->base;
    return ESP_OK;
}
