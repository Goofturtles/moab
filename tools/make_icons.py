"""Draw the Chrome extension's icons (16, 32, 48 and 128 px PNGs) from MOAB's bot logo (logo.svg), with the standard library only.

Run:  tks-spotify/.venv/Scripts/python.exe -I tks-spotify/centralize/tools/make_icons.py

The logo's shapes (48 x 48 units) are copied from logo.svg: the indigo head (one closed path of cubic curves) with a round
cut-out at the top right, two white eyes (rounded rectangles) and the green dot. Each pixel is sampled 8 x 8 times.
"""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "extension" / "icons"
INDIGO, WHITE, GREEN = (0x4F, 0x46, 0xE5), (0xFF, 0xFF, 0xFF), (0x22, 0xC5, 0x5E)

# M24 5 c11 0 19 4.2 19 17.5 S36 43 24 43 5 35.8 5 22.5 13 5 24 5z, with every curve's control points written out
CURVES = [((24, 5), (35, 5), (43, 9.2), (43, 22.5)),
          ((43, 22.5), (43, 35.8), (36, 43), (24, 43)),
          ((24, 43), (12, 43), (5, 35.8), (5, 22.5)),
          ((5, 22.5), (5, 9.2), (13, 5), (24, 5))]


def head_polygon(steps=120):
    pts = []
    for p0, p1, p2, p3 in CURVES:
        for i in range(steps):
            t = i / steps
            a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
            pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


HEAD = head_polygon()


def inside(poly, x, y):
    hit, j = False, len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def in_circle(x, y, cx, cy, r):
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def in_round_rect(x, y, rx, ry, w, h, rad):
    if not (rx <= x <= rx + w and ry <= y <= ry + h):
        return False
    cx = min(max(x, rx + rad), rx + w - rad)
    cy = min(max(y, ry + rad), ry + h - rad)
    return (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad


def color_at(x, y):
    """The logo's colour at (x, y) in its 48-unit space, or None where it is transparent."""
    if in_circle(x, y, 38.5, 9.5, 5):
        return GREEN
    if in_round_rect(x, y, 15.5, 18, 5.5, 11, 2.75) or in_round_rect(x, y, 27, 18, 5.5, 11, 2.75):
        return WHITE
    if inside(HEAD, x, y) and not in_circle(x, y, 38.5, 9.5, 8):
        return INDIGO
    return None


def render(size, n=8):
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filter type 0 for each row
        for px in range(size):
            r = g = b = a = 0
            for sy in range(n):
                for sx in range(n):
                    c = color_at((px + (sx + 0.5) / n) * 48 / size, (py + (sy + 0.5) / n) * 48 / size)
                    if c:
                        r, g, b, a = r + c[0], g + c[1], b + c[2], a + 1
            row += bytes([r // a, g // a, b // a, round(255 * a / (n * n))] if a else [0, 0, 0, 0])
        rows.append(bytes(row))
    return png(size, size, b"".join(rows))


def png(w, h, raw):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        (OUT / ("icon%d.png" % size)).write_bytes(render(size))
        print("wrote", OUT / ("icon%d.png" % size))


if __name__ == "__main__":
    main()
