"""52x16 pixel renderer for the Ulanzi TC002 (Pixbar).

Deliberately dependency-free: the PNG encoder is in here, so this runs on .98 with
stock Python 3.12 and can later be reused as the frame source for the device's
custom-app API (POST /api/custom?name=<app> with a base64 PNG), which measured
~41 fps for a full 52x16 frame on 2026-09-25.

Colours are the firmware's own RGB565 constants (src/enums.h:76-86) expanded to
RGB888, so a mockup is comparable with what the TC001 actually lights up.
"""

import base64
import functools as _functools
import struct
import zlib

W, H = 52, 16


def rgb565_to_rgb(v):
    r, g, b = (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


# src/enums.h:76-86
BLACK = rgb565_to_rgb(0x0000)
BLUE = rgb565_to_rgb(0x001F)
GREEN = rgb565_to_rgb(0x07E0)
CYAN = rgb565_to_rgb(0x07FF)
GRAY = rgb565_to_rgb(0xA514)
RED = rgb565_to_rgb(0xF800)
MAGENTA = rgb565_to_rgb(0xF81F)
YELLOW = rgb565_to_rgb(0xFFE0)
WHITE = rgb565_to_rgb(0xFFFF)

# src/globals.h:59-61
BG_NORMAL, BG_WARNING, BG_URGENT = GREEN, YELLOW, RED


def dim(color, factor):
    """FastLED scale8 with FASTLED_SCALE8_FIXED, as the emulator does it."""
    return tuple((c * (factor + 1)) >> 8 for c in color)


class Panel:
    def __init__(self, w=W, h=H):
        self.w, self.h = w, h
        self.px = [[BLACK] * w for _ in range(h)]
        # Lit pixels that fell outside the panel. Silent clipping is how a face
        # loses the bottom row of its text and nobody notices until it is on the
        # hardware, so every face is checked against this (see audit.py).
        self.clipped = 0

    def clear(self):
        self.px = [[BLACK] * self.w for _ in range(self.h)]
        self.clipped = 0

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = color
        elif any(color):
            self.clipped += 1

    def rect(self, x, y, w, h, color):
        for dy in range(h):
            for dx in range(w):
                self.set(x + dx, y + dy, color)

    def blit(self, x, y, rows, color, dark=None):
        """rows is a list of '0'/'1' strings; 1 paints color, 0 paints dark if given."""
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch == "1":
                    self.set(x + dx, y + dy, color)
                elif dark is not None:
                    self.set(x + dx, y + dy, dark)

    def dimmed(self, factor):
        p = Panel(self.w, self.h)
        p.px = [[dim(c, factor) for c in row] for row in self.px]
        p.clipped = self.clipped
        return p


def lit_pixels(panel):
    """How many pixels are on at all - the number every gate is built from."""
    return sum(1 for row in panel.px for c in row if any(c))


def raw_rgb(panel):
    """The frame as RGB888 bytes, row-major from the top-left: the format the
    golden manifest hashes and a firmware renderer is compared against."""
    return b"".join(bytes(px) for row in panel.px for px in row)


# --------------------------------------------------------------- 3x5 pixel font
# The fallback for the one place no Spleen glyph fits (a 6-row trend box).
_T = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("111", "101", "111", "101", "101"),
    "B": ("111", "101", "110", "101", "111"),
    "C": ("111", "100", "100", "100", "111"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "111", "100", "111"),
    "F": ("111", "100", "111", "100", "100"),
    "G": ("111", "100", "101", "101", "111"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "111"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("110", "101", "101", "101", "101"),
    "O": ("111", "101", "101", "101", "111"),
    "P": ("111", "101", "111", "100", "100"),
    "Q": ("111", "101", "101", "111", "011"),
    "R": ("111", "101", "111", "110", "101"),
    "S": ("111", "100", "111", "001", "111"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "111", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    "-": ("000", "000", "111", "000", "000"),
    "+": ("000", "010", "111", "010", "000"),
    "?": ("111", "001", "011", "000", "010"),
    "/": ("001", "001", "010", "100", "100"),
    "%": ("101", "001", "010", "100", "101"),
    ".": ("0", "0", "0", "0", "1"),
    ",": ("0", "0", "0", "1", "1"),
    ":": ("0", "1", "0", "1", "0"),
    "'": ("1", "1", "0", "0", "0"),
    " ": ("00", "00", "00", "00", "00"),
}
TINY_H = 5


def tiny(panel, x, y, text, color):
    """Top-left anchored 3x5 text. Returns the x of the last lit column."""
    for ch in text.upper():
        g = _T.get(ch)
        if g is None:
            continue
        panel.blit(x, y, g, color)
        x += len(g[0]) + 1
    return x - 1


# ------------------------------------------------- real pixel fonts (Spleen)
# Baked by make_fonts.py from Spleen BDFs (BSD-2, (c) Frederic Cambus). Chosen
# over hand-rolled seven-segment digits, which read as a calculator: the vendor's
# own reference renderer makes the point that proper letterforms with a 1 px
# inter-character gap are what stops a pixel panel looking cheap, and it is right.
import fonts as _F  # noqa: E402

HERO = (_F.SPLEEN_12X24, _F.SPLEEN_12X24_W, _F.SPLEEN_12X24_H)   # digits 12x15
MID = (_F.SPLEEN_8X16, _F.SPLEEN_8X16_W, _F.SPLEEN_8X16_H)       # caps 8x10
SMALL = (_F.SPLEEN_6X12, _F.SPLEEN_6X12_W, _F.SPLEEN_6X12_H)     # caps 6x7

# Layout rules, shared with the firmware through export_fonts.py: glyphs are
# trimmed to their ink and separated by TRACKING px; a blank glyph advances SPACE.
TRACKING = 1
SPACE = 3


@_functools.lru_cache(maxsize=None)
def ink_box(rows):
    """(first_col, last_col, first_row, last_row) of a glyph's ink. A blank glyph
    is (0, -1, 0, -1), so `last < first` is the test for "nothing to draw".
    Cached: the tables are constant and every frame asks the same questions."""
    cols = [c for c in range(len(rows[0])) if any(r[c] == "1" for r in rows)]
    inked = [i for i, r in enumerate(rows) if "1" in r]
    if not cols:
        return (0, -1, 0, -1)
    return (cols[0], cols[-1], inked[0], inked[-1])


def _glyphs(font, text):
    table = font[0]
    return [table[c] for c in text.upper() if c in table]


def _ink_rows(font, text):
    """(first, last) inked row across the glyphs of `text`, or None."""
    boxes = [ink_box(g) for g in _glyphs(font, text)]
    boxes = [b for b in boxes if b[1] >= b[0]]
    if not boxes:
        return None
    return min(b[2] for b in boxes), max(b[3] for b in boxes)


def _ink_top(font, text):
    """First inked row of `text` - so the drawn string sits exactly at the y it
    asked for, instead of being pushed down by whichever glyph in the font
    reaches highest."""
    rows = _ink_rows(font, text)
    return rows[0] if rows else 0


def glyph_boxes(font, text):
    """[(rows, first_col, last_col)] for each drawable character."""
    return [(g,) + ink_box(g)[:2] for g in _glyphs(font, text)]


def font_width(font, text):
    total = 0
    for rows, c0, c1 in glyph_boxes(font, text):
        total += (SPACE if c1 < c0 else c1 - c0 + 1) + TRACKING
    return max(0, total - TRACKING)


def font_height(font, text):
    """Ink height of `text` in `font`."""
    rows = _ink_rows(font, text)
    return (rows[1] - rows[0] + 1) if rows else 0


def font_text(panel, x, y, text, font, color):
    """Draw text with its ink box starting at (x, y). Glyphs are trimmed to their
    own ink and separated by TRACKING px, so spacing is even and strokes never
    touch - Spleen's built-in side bearings would otherwise double up."""
    top = _ink_top(font, text)
    for rows, c0, c1 in glyph_boxes(font, text):
        if c1 < c0:
            x += SPACE + TRACKING
            continue
        for dy, row in enumerate(rows[top:]):
            for dx in range(c0, c1 + 1):
                if row[dx] == "1":
                    panel.set(x + dx - c0, y + dy, color)
        x += (c1 - c0 + 1) + TRACKING
    return x - TRACKING


def font_text_right(panel, x_right, y, text, font, color):
    font_text(panel, x_right - font_width(font, text) + 1, y, text, font, color)


# ------------------------------------------------------------- trend arrows
# 7x7 and 5x5 bitmaps, one per BG_TREND in src/enums.h. No face draws these -
# faces.trend_mark draws chevrons that scale with their box - but they are part
# of the firmware header contract (export_fonts.py), so they stay as data.
ARROWS = {
    "DOUBLE_UP": ("0001000", "0011100", "0111110", "0001000", "0011100", "0111110", "0001000"),
    "SINGLE_UP": ("0001000", "0011100", "0111110", "0011100", "0001000", "0001000", "0001000"),
    "FORTY_FIVE_UP": ("0011111", "0000111", "0001011", "0010001", "0100000", "1000000", "0000000"),
    "FLAT": ("0000000", "0001000", "0000100", "1111110", "0000100", "0001000", "0000000"),
    "FORTY_FIVE_DOWN": ("0000000", "1000000", "0100000", "0010001", "0001011", "0000111", "0011111"),
    "SINGLE_DOWN": ("0001000", "0001000", "0001000", "0011100", "0111110", "0011100", "0001000"),
    "DOUBLE_DOWN": ("0001000", "0111110", "0011100", "0001000", "0111110", "0011100", "0001000"),
    "NONE": ("0011100", "0100010", "0000010", "0000100", "0001000", "0000000", "0001000"),
}
ARROW_W = 7

# 5x5 set, for the strip layouts where a 7x7 arrow will not fit.
ARROWS5 = {
    "DOUBLE_UP": ("00100", "01110", "00100", "01110", "00100"),
    "SINGLE_UP": ("00100", "01110", "11111", "00100", "00100"),
    "FORTY_FIVE_UP": ("01111", "00011", "00101", "01001", "10000"),
    "FLAT": ("00000", "00100", "11111", "00100", "00000"),
    "FORTY_FIVE_DOWN": ("10000", "01001", "00101", "00011", "01111"),
    "SINGLE_DOWN": ("00100", "00100", "11111", "01110", "00100"),
    "DOUBLE_DOWN": ("00100", "01110", "00100", "01110", "00100"),
    "NONE": ("01110", "10001", "00010", "00100", "00100"),
}
ARROW5_W = 5


# ------------------------------------------------------------- PNG encoding
def _chunk(tag, data):
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def png_bytes(rows, w, h):
    # A review render has a few dozen distinct colours over ~250k pixels, so
    # encode each colour once rather than unpacking every tuple.
    enc = {}
    raw = b"".join(b"\x00" + b"".join(enc.get(px) or enc.setdefault(px, bytes(px)) for px in row)
                   for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def png_raw(panel):
    """1:1 PNG - this is what would go to the device."""
    return png_bytes(panel.px, panel.w, panel.h)


@_functools.lru_cache(maxsize=None)
def _led_stamp(scale, radius, glow):
    """The dot geometry is the same for every one of the 832 cells: which
    in-cell offsets are inside the dot, and which are in the glow with what
    weight. Computed once per (scale, radius, glow) instead of per cell."""
    r = radius * scale
    inside, halo = [], []
    for ly in range(scale):
        for lx in range(scale):
            d = ((lx + 0.5 - scale / 2) ** 2 + (ly + 0.5 - scale / 2) ** 2) ** 0.5
            if d <= r:
                inside.append((lx, ly))
            elif glow and d <= r * 2.0:
                halo.append((lx, ly, max(0.0, 1.0 - (d - r) / r) * 0.35))
    return inside, halo


def leds_rows(panel, scale=14, bg=(6, 6, 6), off=(22, 22, 22), radius=0.36, glow=True):
    """Review render as a pixel-row array: round LED dots on a dark board, so a
    mockup can be judged the way the panel is judged - including whether a dim
    colour disappears. Returns (rows, w, h) for composing several panels."""
    w, h = panel.w * scale, panel.h * scale
    rows = [[bg] * w for _ in range(h)]
    inside, halo = _led_stamp(scale, radius, glow)
    for cy in range(panel.h):
        oy = cy * scale
        for cx in range(panel.w):
            ox = cx * scale
            color = panel.px[cy][cx]
            lit = any(color)
            base = color if lit else off
            for lx, ly in inside:
                rows[oy + ly][ox + lx] = base
            if lit:
                for lx, ly, f in halo:
                    rows[oy + ly][ox + lx] = tuple(min(255, int(bg[i] + base[i] * f)) for i in range(3))
    return rows, w, h


def png_leds(panel, **kw):
    rows, w, h = leds_rows(panel, **kw)
    return png_bytes(rows, w, h)


def stack_rows(blocks, gap=12, pad=10, bg=(6, 6, 6)):
    """Compose several (rows, w, h) blocks vertically into one image."""
    width = max(w for _, w, _ in blocks) + pad * 2
    height = sum(h for _, _, h in blocks) + gap * (len(blocks) - 1) + pad * 2
    out = [[bg] * width for _ in range(height)]
    y = pad
    for rows, w, h in blocks:
        for dy, row in enumerate(rows):
            out[y + dy][pad:pad + w] = row
        y += h + gap
    return out, width, height


def data_uri(png):
    return "data:image/png;base64," + base64.b64encode(png).decode()
