# Third-party assets

`package/font/ui12.bin` and `ui16.bin` are Noto Sans CJK based LVGL fonts copied from
`weather/package/font/weather_ui_zh_cn_12.bin` and `weather_ui_zh_cn_16.bin` in
https://github.com/clocteck/holocubic-apps (retrieved 2026-10-22).

These fonts are redistributed under SIL Open Font License 1.1. The original license and
copyright notice are included in `package/font/OFL-NotoSansCJK.txt`.

All xiaobucubic Lua code and the icon were created for this application; no upstream app
implementation was copied.

`package/font/ui22.bin` was generated at 22px / 2bpp with lv_font_conv from
`netease/src/vendor/fonts/NotoSansCJKsc-Regular.otf` in the same upstream repository,
using the same 7,215 codepoints as `ui16.bin`, without kerning. It uses the same OFL license.
