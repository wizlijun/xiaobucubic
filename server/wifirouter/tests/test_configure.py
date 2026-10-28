import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("configure", Path(__file__).parents[1] / "scripts/configure.py")
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class ConfigTest(unittest.TestCase):
    def test_c_string_escaping(self):
        result = configure.render({"ssid": 'ap"\\24', "password": 'some"\\password'})
        self.assertIn(r'#define ROUTER_SSID "ap\"\\24"', result)

    def test_ssid_limit_is_bytes(self):
        with self.assertRaises(ValueError):
            configure.render({"ssid": "热" * 11, "password": "longpassword"})

    def test_reject_invalid_security_and_radio_settings(self):
        for override in ({"password": "short"}, {"password": "abcdefgh\n"}, {"password": "密" * 8},
                         {"channel": 14}, {"channel": True}, {"max_clients": 5}, {"ssid": "a\0b"}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                configure.render({"password": "longpassword", **override})


if __name__ == "__main__":
    unittest.main()
