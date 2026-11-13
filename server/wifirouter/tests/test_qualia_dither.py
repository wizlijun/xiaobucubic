"""Check the compiled dither against quantization/mean-color invariants."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QualiaDitherTest(unittest.TestCase):
    def test_color_accuracy_and_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "probe"
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-DLV_CONF_SKIP",
                "-DLV_COLOR_DEPTH=16", "-DLV_DITHER_GRADIENT=1",
                "-I" + str(ROOT / "managed_components/lvgl__lvgl"),
                str(ROOT / "main/qualia_dither.c"), str(ROOT / "tests/qualia_dither_probe.c"),
                "-lm", "-o", str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)
