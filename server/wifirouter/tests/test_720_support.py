"""Host checks for packed glyph resampling and FT6336 coordinate decoding."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Panel720Test(unittest.TestCase):
    def test_frame_rotation_pixels_colors_and_bounds(self):
        self.compile_and_run("frame_rotate", ["tests/frame_rotate_probe.c"])

    def test_sram_gray_pixels_and_bounds(self):
        self.compile_and_run("sram_gray", ["tests/sram_gray_probe.c"])

    def compile_and_run(self, name, sources, headers=None):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            for filename, text in (headers or {}).items():
                (tmp / filename).write_text(text)
            binary = tmp / name
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                "-I" + str(tmp), "-I" + str(ROOT / "main"),
                *[str(ROOT / s) for s in sources], "-lm", "-o", str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)

    def test_ft6336_touch_frames(self):
        self.compile_and_run("touch", ["tests/ft6336_probe.c"])

    def test_font_stream_windows_and_seeks(self):
        self.compile_and_run("font_stream", ["tests/font_stream_probe.c"])

    def test_png_color_precision_alpha_and_bounds(self):
        self.compile_and_run("image_quantize", ["main/image_quantize.c", "tests/image_quantize_probe.c"])

    def test_font_metrics_and_packed_resampling(self):
        self.compile_and_run("font", ["main/scaled_font.c", "tests/scaled_font_probe.c"], {"lvgl.h": """
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef struct lv_font_t lv_font_t;
typedef struct { const lv_font_t *resolved_font; uint16_t adv_w,box_w,box_h;
    int16_t ofs_x,ofs_y; uint8_t bpp,is_placeholder; } lv_font_glyph_dsc_t;
struct lv_font_t {
    bool (*get_glyph_dsc)(const lv_font_t *,lv_font_glyph_dsc_t *,uint32_t,uint32_t);
    const uint8_t *(*get_glyph_bitmap)(const lv_font_t *,uint32_t);
    int16_t line_height,base_line; uint8_t subpx;
    int8_t underline_position,underline_thickness;
    const void *dsc; const lv_font_t *fallback;
};
bool lv_font_get_glyph_dsc(const lv_font_t *,lv_font_glyph_dsc_t *,uint32_t,uint32_t);
const uint8_t *lv_font_get_glyph_bitmap(const lv_font_t *,uint32_t);
"""})


if __name__ == "__main__":
    unittest.main()
