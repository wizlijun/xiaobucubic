#include <string.h>
#include "scaled_font.h"

#define GLYPH_LIMIT 96
/* LVGL consumes a glyph bitmap synchronously before requesting the next one. */
static uint8_t scaled_bitmap[GLYPH_LIMIT * GLYPH_LIMIT / 2];

static int scale(int value) { return (value * 3 + (value < 0 ? -1 : 1)) / 2; }

static bool glyph_descriptor(const lv_font_t *font, lv_font_glyph_dsc_t *out,
                             uint32_t letter, uint32_t next)
{
    const lv_font_t *source = font->dsc;
    if (!lv_font_get_glyph_dsc(source, out, letter, next)) return false;
    if (scale(out->box_w) > GLYPH_LIMIT || scale(out->box_h) > GLYPH_LIMIT) return false;
    if (out->bpp != 1 && out->bpp != 2 && out->bpp != 4 && out->bpp != 8) return false;
    out->adv_w = scale(out->adv_w);
    out->box_w = scale(out->box_w); out->box_h = scale(out->box_h);
    out->ofs_x = scale(out->ofs_x); out->ofs_y = scale(out->ofs_y);
    out->bpp = 4; out->resolved_font = font;
    return true;
}

static unsigned sample(const uint8_t *data, unsigned width, unsigned bpp, unsigned x, unsigned y)
{
    unsigned bit = (y * width + x) * bpp;
    unsigned mask = (1u << bpp) - 1;
    unsigned value = (data[bit / 8] >> (8 - bpp - bit % 8)) & mask;
    return value * 255 / mask;
}

static const uint8_t *glyph_bitmap(const lv_font_t *font, uint32_t letter)
{
    const lv_font_t *source = font->dsc;
    lv_font_glyph_dsc_t d = {0};
    if (!lv_font_get_glyph_dsc(source, &d, letter, 0) || !d.box_w || !d.box_h) return NULL;
    unsigned width = scale(d.box_w), height = scale(d.box_h);
    if (width > GLYPH_LIMIT || height > GLYPH_LIMIT) return NULL;
    if (d.bpp != 1 && d.bpp != 2 && d.bpp != 4 && d.bpp != 8) return NULL;
    const uint8_t *data = lv_font_get_glyph_bitmap(d.resolved_font ? d.resolved_font : source, letter);
    if (!data) return NULL;
    memset(scaled_bitmap, 0, (width * height + 1) / 2);
    for (unsigned y = 0; y < height; ++y) {
        unsigned sy = height > 1 ? y * (d.box_h - 1) * 256 / (height - 1) : 0;
        unsigned y0 = sy / 256, y1 = y0 + 1 < d.box_h ? y0 + 1 : y0, fy = sy % 256;
        for (unsigned x = 0; x < width; ++x) {
            unsigned sx = width > 1 ? x * (d.box_w - 1) * 256 / (width - 1) : 0;
            unsigned x0 = sx / 256, x1 = x0 + 1 < d.box_w ? x0 + 1 : x0, fx = sx % 256;
            unsigned top = sample(data, d.box_w, d.bpp, x0, y0) * (256 - fx) + sample(data, d.box_w, d.bpp, x1, y0) * fx;
            unsigned bottom = sample(data, d.box_w, d.bpp, x0, y1) * (256 - fx) + sample(data, d.box_w, d.bpp, x1, y1) * fx;
            unsigned gray = ((top * (256 - fy) + bottom * fy + 32768) / 65536 + 8) / 17;
            unsigned pixel = y * width + x;
            scaled_bitmap[pixel / 2] |= gray << (pixel % 2 ? 0 : 4);
        }
    }
    return scaled_bitmap;
}

void app_font_scale_150(lv_font_t *target, const lv_font_t *source)
{
    *target = *source;
    target->get_glyph_dsc = glyph_descriptor;
    target->get_glyph_bitmap = glyph_bitmap;
    target->line_height = scale(source->line_height);
    target->base_line = scale(source->base_line);
    target->underline_position = scale(source->underline_position);
    target->underline_thickness = scale(source->underline_thickness);
    target->dsc = source;
    target->fallback = NULL;
}
