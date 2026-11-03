#!/usr/bin/env python3
"""Regenerate 480px-screen fonts using lv_font_conv 1.5.3.

Usage: python3 scripts/generate_fonts.py NotoSansCJKsc-Regular.otf LXGWWenKai-Regular.ttf
The converter is installed separately in .tools/fontgen (see README).
"""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "../../apps/xiaobucubic/package/font"


def codepoints(path):
    data = path.read_bytes()
    start = struct.unpack_from("<I", data)[0]
    assert data[start + 4:start + 8] == b"cmap"
    count = struct.unpack_from("<I", data, start + 8)[0]
    result = set()
    for i in range(count):
        offset, first, length, _, entries, kind, _ = struct.unpack_from("<IIHHHBB", data, start + 12 + 16 * i)
        if kind == 2:
            result.update(range(first, first + length))
        elif kind == 0:
            # Zero offsets after the first character are absent glyphs.
            result.update(first + j for j in range(entries) if j == 0 or data[start + offset + j])
        elif kind in (1, 3):
            result.update(first + x for x in struct.unpack_from(f"<{entries}H", data, start + offset))
        else:
            raise ValueError(f"Unknown cmap type {kind}")
    return sorted(result)


def main():
    font = Path(sys.argv[1]).resolve()
    wenkai = Path(sys.argv[2]).resolve()
    converter = ROOT / ".tools/fontgen/node_modules/lv_font_conv/lv_font_conv.js"
    output = ROOT / "assets/fonts"
    output.mkdir(parents=True, exist_ok=True)
    chars = codepoints(SOURCE / "ui16.bin")
    assert len(chars) == 7215, "Upstream character set changed; review font coverage"
    symbols = "".join(map(chr, chars))
    hashes = {}
    for name, size, source in (("ui18", 18, font), ("ui24", 24, font),
                               ("wenkai24", 24, wenkai), ("wenkai32", 32, wenkai)):
        target = output / f"{name}.bin"
        subprocess.run(["node", str(converter), "--font", str(source), "--symbols", symbols,
                        "--size", str(size), "--bpp", "2", "--format", "bin", "--no-kerning", "-o", str(target)], check=True)
        assert codepoints(target) == chars, "Generated font lost characters"
        hashes[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
        print(f"{target.name}: {target.stat().st_size} bytes, {len(chars)} characters")
    (output / "OFL-NotoSansCJK.txt").write_bytes((SOURCE / "OFL-NotoSansCJK.txt").read_bytes())
    (output / "OFL-LXGWWenKai.txt").write_text("\n".join(
        line.rstrip() for line in (wenkai.parent / "OFL-LXGWWenKai.txt").read_text().splitlines()) + "\n")
    for old in output.glob("*.bin"):
        if old.name not in hashes:
            old.unlink()
    (output / "manifest.json").write_text(json.dumps({
        "converter": "lv_font_conv@1.5.3",
        "sources": {
            font.name: {"sha256": hashlib.sha256(font.read_bytes()).hexdigest(),
                        "url": "https://github.com/clocteck/holocubic-apps/tree/main/netease/src/vendor/fonts"},
            wenkai.name: {"sha256": hashlib.sha256(wenkai.read_bytes()).hexdigest(),
                          "url": "https://github.com/lxgw/LxgwWenKai/releases/tag/v1.530"},
        },
        "codepoints": len(chars), "bpp": 2, "sha256": hashes,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
