#!/usr/bin/env python3
"""从 LXGW WenKai Regular v1.530 生成便签正文字体子集 StandItNote-Regular.ttf。

完整字库约 25 MB，小组件进程内存上限只有几十 MB，所以只保留 ASCII、GB2312 汉字和常用标点；
缺字由系统字体自动补上。OFL 的保留字体名不允许用于修改版，子集改名为 “StandIt Note”，
版权与许可字段原样保留。

用法（需要 fontTools）：
    python3 tools/make_note_font.py LXGWWenKai-Regular.ttf Shared/Fonts/StandItNote-Regular.ttf
"""
import hashlib
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

SOURCE_SHA256 = "2d73eea94ad808999d90c0000c239a84a33b09d4bc6ab6c5b8bbf1eda8a7fc8b"
FAMILY = "StandIt Note"
POSTSCRIPT = "StandItNote-Regular"


def charset() -> set[int]:
    chars = set(range(0x20, 0x7F))
    for hi in range(0xA1, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.update(ord(c) for c in bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    chars.update(range(0x3000, 0x3040))  # CJK 标点
    chars.update(range(0xFF00, 0xFFF0))  # 全角字符
    chars.update(range(0x2010, 0x2070))  # 破折号、引号、省略号等
    chars.update(map(ord, "·°×÷●○■□▲△★☆→←↑↓√✓✗"))
    return chars


def main(src: str, dst: str) -> None:
    digest = hashlib.sha256(open(src, "rb").read()).hexdigest()
    if digest != SOURCE_SHA256:
        sys.exit(f"源字体 SHA-256 不符：{digest}")
    font = TTFont(src)
    options = subset.Options()
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.layout_features = ["*"]
    options.notdef_outline = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=charset())
    sub.subset(font)
    names = {1: FAMILY, 3: f"{POSTSCRIPT};subset of LXGW WenKai 1.530", 4: f"{FAMILY} Regular",
             6: POSTSCRIPT, 16: FAMILY, 17: "Regular"}
    for record in list(font["name"].names):
        if record.nameID in names:
            font["name"].removeNames(nameID=record.nameID)
    for name_id, value in names.items():
        font["name"].setName(value, name_id, 3, 1, 0x409)
        font["name"].setName(value, name_id, 1, 0, 0)
    font.save(dst)
    print(f"{dst}: {len(charset())} 个码位")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
