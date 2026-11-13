"""Check resolution-dependent buffer sizes, layout and touch bounds in C."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DisplayGeometryTest(unittest.TestCase):
    def test_480_and_720_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "display_geometry_probe"
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-I" + str(ROOT / "main"),
                str(ROOT / "tests/display_geometry_probe.c"), "-lm", "-o", str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
