"""Render the candidate 52x16 faces to PNG sheets and a self-contained gallery.

Outputs into mockups/:
  face-<slug>.png        one face, its six states stacked (phone-friendly)
  all-faces.png          every face in the state that shows it off
  brightness-floor.png   the legibility check: full / night / floor
  index.html             labelled gallery, no external files

Run: python make_mockups.py
"""

import os

import faces as F
import render as R

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mockups")
SCALE = 14

# Brightness levels to check. The TC001's floor is MIN_BRIGHTNESS = 1 and the
# device config here has brightness.low = 50 (%), so the middle column is the
# realistic night setting and the right one is the worst case.
LEVELS = [("full", 255), ("night", 60), ("floor", 12)]
NIGHT = 60


def sheet(panels, path, scale=SCALE):
    blocks = [R.leds_rows(p, scale=scale) for p in panels]
    rows, w, h = R.stack_rows(blocks)
    with open(os.path.join(OUT, path), "wb") as f:
        f.write(R.png_bytes(rows, w, h))


def main():
    os.makedirs(OUT, exist_ok=True)
    cells, dim_cells, by_face = {}, {}, {}
    # One render per face x state serves the sheet, the gallery and its night row.
    for face, state, _reading, p in F.every_frame():
        cells[(face.slug, state)] = R.data_uri(R.png_leds(p, scale=10))
        dim_cells[(face.slug, state)] = R.data_uri(R.png_leds(p.dimmed(NIGHT), scale=10))
        by_face.setdefault(face.slug, []).append(p)
    for face in F.FACES:
        sheet(by_face[face.slug], f"face-{face.slug}.png")

    sheet([face.fn(F.state(face.demo_state)) for face in F.FACES], "all-faces.png")

    # Legibility: the states that must never be missed, at three brightnesses.
    hero_delta = F.face("hero-delta").fn
    sheet([hero_delta(F.state(name)).dimmed(level)
           for name in ("in-range", "urgent-low", "stale") for _, level in LEVELS],
          "brightness-floor.png")

    html = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>TC002 52x16 face mockups</title><style>",
        "body{background:#0b0b0c;color:#e6e6e6;font:14px/1.5 system-ui,sans-serif;margin:0;padding:32px}",
        "h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 2px}",
        ".lede,.about{color:#9a9a9a;max-width:80ch}.about{margin:0 0 12px}",
        "table{border-collapse:collapse;margin:8px 0 4px}",
        "td,th{padding:6px 10px;text-align:left;vertical-align:top}",
        "th{font:12px/1.4 ui-monospace,monospace;color:#8a8a8a;font-weight:500}",
        "img{display:block;border-radius:3px}",
        ".note{color:#6ee7b7;font:12px/1.5 ui-monospace,monospace;margin-top:6px}",
        "</style></head><body>",
        "<h1>TC002 (Pixbar) - candidate faces, drawn native at 52&times;16</h1>",
        "<p class='lede'>Not ports of the 32&times;8 faces: each one puts the value, the trend, the "
        "history and the clock on screen together, which the old panel could not do. Colours are the "
        "firmware's own RGB565 constants, and the lower row of each pair is the same face at a night "
        "brightness, because a face that vanishes when dimmed is not a face we can ship.</p>",
    ]
    for face in F.FACES:
        html.append(f"<h2>{face.name}</h2><p class='about'>{face.about}</p><table><tr><th></th>")
        html += [f"<th>{s}</th>" for s in F.STATE_NAMES]
        html.append("</tr><tr><th>full</th>")
        html += [f"<td><img src='{cells[(face.slug, s)]}' alt='{face.name} {s}'></td>" for s in F.STATE_NAMES]
        html.append("</tr><tr><th>night</th>")
        html += [f"<td><img src='{dim_cells[(face.slug, s)]}' alt='{face.name} {s} dim'></td>" for s in F.STATE_NAMES]
        html.append("</tr></table>")
    html.append(
        "<p class='note'>Every frame here is a real 52&times;16 pixel buffer - the same buffer the "
        "device pusher sends as a base64 PNG (measured 41 fps end to end on 2026-09-25).</p>"
    )
    html.append("</body></html>")
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(html))

    print(f"wrote {len(F.FACES)} face sheets + all-faces + brightness-floor + index.html to {OUT}")


if __name__ == "__main__":
    main()
