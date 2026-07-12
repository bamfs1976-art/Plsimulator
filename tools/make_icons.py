"""Generate the PWA icons (icon-192.png, icon-512.png) without Pillow.

Draws the app mark — a white "PL" on the site's blue-violet gradient —
straight into an RGB PNG with zlib/struct only, so the icons are fully
reproducible from the repo with a bare Python. Full-bleed background
makes the same files valid for both "any" and "maskable" purposes.

    python3 tools/make_icons.py
"""

import struct
import zlib

# The site's --grad endpoints (#2456b8 -> #6c56c9), swept diagonally.
GRAD_A = (0x24, 0x56, 0xB8)
GRAD_B = (0x6C, 0x56, 0xC9)
WHITE = (0xFF, 0xFF, 0xFF)

# 5x7 block glyphs for "P" and "L", one column apart (11x7 overall).
GLYPHS = [
    "1111. 1....",
    "1...1 1....",
    "1...1 1....",
    "1111. 1....",
    "1.... 1....",
    "1.... 1....",
    "1.... 11111",
]
GLYPH_W, GLYPH_H = 11, 7


def _chunk(tag, data):
    payload = tag + data
    return (struct.pack(">I", len(data)) + payload +
            struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF))


def write_png(path, size):
    rows = []
    scale = int(size * 0.6) // GLYPH_W          # mark spans ~60% of the icon
    mark_w, mark_h = GLYPH_W * scale, GLYPH_H * scale
    x0, y0 = (size - mark_w) // 2, (size - mark_h) // 2
    for y in range(size):
        row = bytearray(b"\x00")                # filter type 0 (None)
        for x in range(size):
            t = (x + y) / (2 * size - 2)        # diagonal gradient position
            px = tuple(round(a + (b - a) * t) for a, b in zip(GRAD_A, GRAD_B))
            if x0 <= x < x0 + mark_w and y0 <= y < y0 + mark_h:
                gx = (x - x0) // scale
                gy = (y - y0) // scale
                cell = GLYPHS[gy].replace(" ", ".")[gx]
                if cell == "1":
                    px = WHITE
            row += bytes(px)
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(_chunk(b"IHDR", ihdr))
        fh.write(_chunk(b"IDAT", zlib.compress(b"".join(rows), 9)))
        fh.write(_chunk(b"IEND", b""))
    print(f"{path}: {size}x{size}")


if __name__ == "__main__":
    for size in (192, 512):
        write_png(f"icon-{size}.png", size)
