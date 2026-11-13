#include <assert.h>
#include <stdlib.h>
#include "font_stream.h"

int main(void)
{
    FILE *file = tmpfile();
    assert(file);
    uint8_t original[10003], cache[127], output[701];
    for (unsigned i = 0; i < sizeof(original); ++i) original[i] = (i * 37 + i / 251) & 255;
    assert(fwrite(original, 1, sizeof(original), file) == sizeof(original));
    font_stream_t stream = {.file=file, .cache=cache, .size=sizeof(original), .capacity=sizeof(cache)};
    uint32_t read;
    /* Sequential reads crossing many windows, including partial EOF. */
    while (stream.position < stream.size) {
        unsigned start = stream.position;
        assert(font_stream_read(&stream, output, sizeof(output), &read));
        assert(read > 0 && !memcmp(output, original + start, read));
    }
    assert(font_stream_read(&stream, output, 10, &read) && read == 0);
    /* Deterministic backward/random seeks resemble the two-pass glyph loader. */
    for (unsigned i = 0; i < 1000; ++i) {
        unsigned start = (i * 4999) % sizeof(original);
        assert(font_stream_seek(&stream, start));
        assert(font_stream_read(&stream, output, 17, &read));
        assert(read == (sizeof(original) - start < 17 ? sizeof(original) - start : 17));
        assert(!memcmp(output, original + start, read));
    }
    uint32_t previous = stream.position;
    assert(!font_stream_seek(&stream, (uint64_t)UINT32_MAX + 1));
    assert(stream.position == previous);
    /* Truncated physical files must report an I/O failure, not serve stale cache. */
    stream.size += 20;
    assert(font_stream_seek(&stream, sizeof(original)));
    assert(!font_stream_read(&stream, output, 20, &read) && read == 0);
    fclose(file);
    return 0;
}
