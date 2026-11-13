#include <assert.h>
#include <string.h>
#include "scaled_font.h"

static unsigned bits = 2, width = 2, height = 2;
static uint8_t bitmap[4096];
static bool descriptor(const lv_font_t *font, lv_font_glyph_dsc_t *out, uint32_t c, uint32_t next)
{
    (void)next;
    if (c == '?') return false;
    *out = (lv_font_glyph_dsc_t){.resolved_font=font, .adv_w=4, .box_w=width,
        .box_h=height, .ofs_x=-2, .ofs_y=2, .bpp=bits};
    return true;
}
static const uint8_t *glyph(const lv_font_t *font, uint32_t c) { (void)font; (void)c; return bitmap; }
bool lv_font_get_glyph_dsc(const lv_font_t *f, lv_font_glyph_dsc_t *d, uint32_t c, uint32_t n) { return f->get_glyph_dsc(f,d,c,n); }
const uint8_t *lv_font_get_glyph_bitmap(const lv_font_t *f, uint32_t c) { return f->get_glyph_bitmap(f,c); }
static unsigned pixel(const uint8_t *data, unsigned i) { return (data[i/2] >> (i%2 ? 0 : 4)) & 15; }

int main(void)
{
    lv_font_t base = {.get_glyph_dsc=descriptor, .get_glyph_bitmap=glyph, .line_height=32, .base_line=8};
    lv_font_t scaled;
    app_font_scale_150(&scaled, &base);
    assert(scaled.line_height == 48 && scaled.base_line == 12);
    lv_font_glyph_dsc_t d;
    assert(lv_font_get_glyph_dsc(&scaled, &d, 'A', 0));
    assert(d.adv_w==6 && d.box_w==3 && d.box_h==3 && d.ofs_x==-3 && d.ofs_y==3 && d.bpp==4);
    bitmap[0] = 0x3c; /* 2x2: black, white / white, black */
    const uint8_t *p = lv_font_get_glyph_bitmap(&scaled, 'A');
    const unsigned expected[] = {0,8,15,8,8,8,15,8,0};
    for (unsigned i=0;i<9;++i) assert(pixel(p,i)==expected[i]);
    assert(!lv_font_get_glyph_dsc(&scaled, &d, '?', 0));
    assert(!lv_font_get_glyph_bitmap(&scaled, '?'));
    /* Test packed rows of odd widths, all supported bpp, endpoints and buffer limit. */
    for (bits=1;bits<=8;bits*=2) {
        for (width=1;width<=64;++width) for (height=1;height<=64;++height) {
            for (int value=0;value<=255;value+=255) {
                memset(bitmap,value,sizeof(bitmap));
                assert(lv_font_get_glyph_dsc(&scaled,&d,'A',0));
                p=lv_font_get_glyph_bitmap(&scaled,'A'); assert(p);
                for (unsigned i=0;i<d.box_w*d.box_h;++i) assert(pixel(p,i)==(value?15:0));
            }
        }
    }
    bits=2; width=65; height=1;
    assert(!lv_font_get_glyph_dsc(&scaled,&d,'A',0));
    assert(!lv_font_get_glyph_bitmap(&scaled,'A'));
    width=0;
    assert(!lv_font_get_glyph_bitmap(&scaled,'A'));
    return 0;
}
