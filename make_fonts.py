"""Bake the glyphs we need out of Spleen BDF files into fonts.py.

Spleen (https://github.com/fcambus/spleen, BSD-2-Clause, (c) Frederic Cambus) is a
bitmap font family whose 8x16 cell is exactly the height of this panel, so a value
can fill all 16 rows with real letterforms instead of hand-rolled segments. We bake
only the characters a glucose face can show, which keeps the runtime dependency-free
and fonts.py small.

    python make_fonts.py <dir containing spleen-*.bdf>
"""

import os
import sys

WANTED = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ:.,-+%?/ "
SOURCES = [
    ("SPLEEN_12X24", "spleen-12x24.bdf"),  # hero: digits crop to 15 rows, 2px strokes
    ("SPLEEN_8X16", "spleen-8x16.bdf"),
    ("SPLEEN_6X12", "spleen-6x12.bdf"),
]


def parse_bdf(path, wanted):
    """Return {char: (rows, width, height)} with rows as '0'/'1' strings."""
    glyphs = {}
    with open(path, encoding="latin-1") as fh:
        lines = fh.read().splitlines()

    i, font_bbx = 0, None
    while i < len(lines):
        line = lines[i]
        if line.startswith("FONTBOUNDINGBOX"):
            font_bbx = [int(v) for v in line.split()[1:]]
        elif line.startswith("STARTCHAR"):
            encoding, bbx, bitmap = None, None, []
            while not lines[i].startswith("ENDCHAR"):
                i += 1
                cur = lines[i]
                if cur.startswith("ENCODING"):
                    encoding = int(cur.split()[1])
                elif cur.startswith("BBX"):
                    bbx = [int(v) for v in cur.split()[1:]]
                elif cur == "BITMAP":
                    j = i + 1
                    while not lines[j].startswith("ENDCHAR"):
                        bitmap.append(lines[j].strip())
                        j += 1
                    i = j - 1
            char = chr(encoding) if encoding and 0 <= encoding < 0x110000 else None
            if char in wanted and bbx:
                gw, gh, gx, gy = bbx
                fw, fh, fx, fy = font_bbx
                rows = []
                for hexrow in bitmap:
                    bits = bin(int(hexrow, 16))[2:].zfill(len(hexrow) * 4)[:gw]
                    rows.append(bits)
                # Place the glyph box inside the full font cell, so every glyph in a
                # font shares one origin and text lines up without per-char fiddling.
                top_pad = (fh + fy) - (gh + gy)
                left_pad = gx - fx
                cell = []
                for _ in range(max(0, top_pad)):
                    cell.append("0" * fw)
                for r in rows:
                    cell.append(("0" * left_pad + r).ljust(fw, "0")[:fw])
                while len(cell) < fh:
                    cell.append("0" * fw)
                glyphs[char] = (cell[:fh], fw, fh)
        i += 1
    return glyphs


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "."
    out = [
        '"""Pixel fonts baked from Spleen BDFs by make_fonts.py - do not hand-edit.',
        "",
        "Spleen (c) 2018-2026 Frederic Cambus, BSD-2-Clause. Only the glyphs a glucose",
        "face can show are included. See THIRD_PARTY_NOTICES.md.",
        '"""',
        "",
    ]
    for name, filename in SOURCES:
        path = os.path.join(src, filename)
        glyphs = parse_bdf(path, set(WANTED))
        missing = sorted(set(WANTED) - set(glyphs))
        w, h = next(iter(glyphs.values()))[1:3]
        print(f"{filename}: {len(glyphs)} glyphs at {w}x{h}"
              + (f" (missing {missing})" if missing else ""))
        out.append(f"{name}_W, {name}_H = {w}, {h}")
        out.append(f"{name} = {{")
        for ch in WANTED:
            if ch not in glyphs:
                continue
            rows = glyphs[ch][0]
            out.append(f"    {ch!r}: (" + ", ".join(repr(r) for r in rows) + "),")
        out.append("}")
        out.append("")
    dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts.py")
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out))
    print("wrote", dest)


if __name__ == "__main__":
    main()
