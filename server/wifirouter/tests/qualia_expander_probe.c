#include <assert.h>
#include <stdint.h>
#include "qualia_expander.h"

static uint8_t regs[4];
static int writes, fail_write, live_devices;
static bool fail_probe, fail_read, fail_add;
static const int failed = 99;

esp_err_t i2c_master_probe(void *bus, uint16_t address, int timeout)
{
    assert(bus && address == 0x3f && timeout > 0);
    return fail_probe ? failed : ESP_OK;
}
esp_err_t i2c_master_bus_add_device(void *bus, const i2c_device_config_t *config, void **dev)
{
    assert(bus && config->device_address == 0x3f && config->scl_speed_hz == 400000);
    if (fail_add) return failed;
    *dev = regs; ++live_devices; return ESP_OK;
}
esp_err_t i2c_master_bus_rm_device(void *dev)
{
    assert(dev == regs && live_devices == 1);
    --live_devices; return ESP_OK;
}
esp_err_t i2c_master_transmit(void *dev, const uint8_t *data, size_t length, int timeout)
{
    assert(dev == regs && length == 2 && data[0] < 4 && timeout > 0);
    if (++writes == fail_write) return failed;
    /* First make all pins inputs before changing the output latch. */
    if (writes == 1) assert(data[0] == 3 && data[1] == 0xff);
    regs[data[0]] = data[1]; return ESP_OK;
}
esp_err_t i2c_master_transmit_receive(void *dev, const uint8_t *data, size_t length,
                                     uint8_t *out, size_t out_length, int timeout)
{
    assert(dev == regs && length == 1 && data[0] == 0 && out_length == 1 && timeout > 0);
    if (fail_read) return failed;
    *out = regs[0]; return ESP_OK;
}
int main(void)
{
    esp_io_expander_handle_t exp = NULL;
    assert(qualia_expander_init(NULL, &exp) == ESP_ERR_INVALID_ARG);
    assert(qualia_expander_init(regs, NULL) == ESP_ERR_INVALID_ARG);
    fail_probe = true;
    assert(qualia_expander_init(regs, &exp) == failed && exp == NULL && live_devices == 0);
    fail_probe = false; fail_add = true;
    assert(qualia_expander_init(regs, &exp) == failed && exp == NULL && live_devices == 0);
    fail_add = false;
    for (int i = 1; i <= 4; ++i) {
        writes = 0; fail_write = i;
        assert(qualia_expander_init(regs, &exp) == failed && exp == NULL && live_devices == 0);
    }
    writes = 0; fail_write = 0;
    assert(qualia_expander_init(regs, &exp) == ESP_OK && live_devices == 1);
    assert(regs[1] == 0xe6 && regs[2] == 0 && regs[3] == 0x68);
    /* BL is off; reset/CS are high; IRQ and both buttons remain inputs. */
    assert(!(regs[1] & 0x10) && (regs[1] & 6) == 6);
    uint32_t value = 0;
    fail_write = writes + 1;
    assert(exp->write_output_reg(exp, 0xf6) == failed);
    assert(exp->read_output_reg(exp, &value) == ESP_OK && value == 0xe6);
    assert(exp->write_output_reg(exp, 0xf6) == ESP_OK);
    assert(exp->read_output_reg(exp, &value) == ESP_OK && value == 0xf6 && regs[1] == 0xf6);
    fail_write = writes + 1;
    assert(exp->write_direction_reg(exp, 0xff) == failed);
    assert(exp->read_direction_reg(exp, &value) == ESP_OK && value == 0x68);
    fail_read = true; value = 1234;
    assert(exp->read_input_reg(exp, &value) == failed && value == 1234);
    fail_read = false; regs[0] = 0x20;
    assert(exp->read_input_reg(exp, &value) == ESP_OK && value == 0x20);
    assert(exp->del(exp) == ESP_OK && live_devices == 0);
    return 0;
}
