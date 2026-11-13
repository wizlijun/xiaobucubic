"""Exercise the hardware check CLI against representative status responses."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class RouterCheckTest(unittest.TestCase):
    def status(self, size):
        large = size == 720
        return {
            "dhcp_running": True, "usb_attached": True, "nat_ready": True, "subnet_conflict": False,
            "display": {
                "state": "initialized", "error": "ESP_OK", "board": "qualia_5800",
                "panel_id": "yx40006act" if large else "waveshare_st7701",
                "width": size, "height": size, "psram_bytes": 8388608,
                "pixel_clock_hz": 35000000 if large else 8000000, "bounce_lines": 20,
                "cache_line_bytes": 64, "isr_iram_safe": True, "data_cache_bytes": 65536,
                "restart_policy": "on_underflow", "frame_buffers": 2,
                "hsync_pulse_width": 6, "hsync_back_porch": 25, "hsync_front_porch": 25,
                "vsync_pulse_width": 2, "vsync_back_porch": 17, "vsync_front_porch": 20,
            },
            "app": {
                "state": "running", "implementation": "native_c", "fonts_loaded": 4,
                "typography": "720px_scaled_27_36_48" if large else "480px_adaptive_18_24_32",
                "message_font_family": "LXGW WenKai", "http_status": 200, "connection": "已同步",
                "has_snapshot": True, "cache_available": True, "refresh_mode": "whole_frame_double_buffer",
                "presented_frames": 10, "frame_wait_timeouts": 0, "rgb_vsyncs": 100, "rgb_frame_completions": 100,
                "touch_available": True, "touch_controller": "FT6336U" if large else "GT911",
            },
        }

    def check(self, data, panel, clock=None, timing="text"):
        argv = ["check_router.py", "http://device.invalid", "--require-display", "--require-app",
                "--require-buffered-display", "--require-stable-rgb", "--require-touch",
                "--expect-board", "qualia_5800", "--expect-panel", panel]
        if clock is not None: argv += ["--expect-pclk", str(clock)]
        if timing is not None: argv += ["--expect-timing", timing]
        with patch("sys.argv", argv), patch("urllib.request.build_opener") as factory, contextlib.redirect_stdout(io.StringIO()):
            factory.return_value.open.return_value = io.StringIO(json.dumps(data))
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(ROOT / "scripts/check_router.py"), run_name="__main__")
            return result.exception.code

    def test_both_panels_and_incorrect_firmware(self):
        for size, panel in [(480, "waveshare_st7701"), (720, "yx40006act")]:
            with self.subTest(size=size):
                self.assertEqual(self.check(self.status(size), panel), 0)
        self.assertEqual(self.check(self.status(480), "yx40006act"), 1)
        fast_480 = self.status(480)
        fast_480["display"]["pixel_clock_hz"] = 16407120
        self.assertEqual(self.check(fast_480, "waveshare_st7701", 16407120), 0)
        self.assertEqual(self.check(fast_480, "waveshare_st7701"), 1)
        bad = self.status(720); bad["display"]["width"] = 480
        self.assertEqual(self.check(bad, "yx40006act"), 1)
        bad = self.status(720); bad["app"]["touch_controller"] = "GT911"
        self.assertEqual(self.check(bad, "yx40006act"), 1)
        bad = self.status(720); bad["display"]["hsync_back_porch"] = 44
        self.assertEqual(self.check(bad, "yx40006act"), 1)
        bad = self.status(720); bad["display"]["pixel_clock_hz"] = 16000000
        self.assertEqual(self.check(bad, "yx40006act"), 1)
        experiment = self.status(720); experiment["display"]["pixel_clock_hz"] = 30000000
        self.assertEqual(self.check(experiment, "yx40006act"), 1)
        self.assertEqual(self.check(experiment, "yx40006act", 30000000), 0)
        reference = self.status(720)
        reference["display"].update(hsync_pulse_width=2, hsync_back_porch=44,
                                    hsync_front_porch=46, vsync_back_porch=18, vsync_front_porch=16)
        self.assertEqual(self.check(reference, "yx40006act"), 1)
        self.assertEqual(self.check(reference, "yx40006act", timing="reference"), 0)
        self.assertEqual(self.check(reference, "yx40006act", timing=None), 0)
        self.assertEqual(self.check(self.status(720), "yx40006act", timing=None), 1)


if __name__ == "__main__":
    unittest.main()
