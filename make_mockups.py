"""Render the candidate 52x16 faces to PNG sheets and a self-contained gallery.

Outputs into mockups/:
  face-<slug>.png        one face, its six states stacked (phone-friendly)
  all-faces.png          every face in range, for comparing layouts
  brightness-floor.png   the legibility check: full / dim / floor
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


def render_png(panel, path, scale=SCALE):
    with open(os.path.join(OUT, path), "wb") as f:
        f.write(R.png_leds(panel, scale=scale))


def sheet(panels, path, scale=SCALE):
    blocks = [R.leds_rows(p, scale=scale) for p in panels]
    rows, w, h = R.stack_rows(blocks)
    with open(os.path.join(OUT, path), "wb") as f:
        f.write(R.png_bytes(rows, w, h))


def main():
    os.makedirs(OUT, exist_ok=True)
    cells = {}

    for slug, name, fn, about in F.FACES:
        panels = []
        for state, reading in F.STATES:
            p = fn(reading)
            cells[(slug, state)] = R.data_uri(R.png_leds(p, scale=10))
            panels.append(p)
        sheet(panels, f"face-{slug}.png")

    in_range = F.STATES[0][1]
    stale_reading = dict(F.STATES)["stale"]
    # The no-data face only says anything in its own state, so show it that way.
    sheet(
        [fn(stale_reading if slug == "no-data" else in_range) for slug, _, fn, _ in F.FACES],
        "all-faces.png",
    )

    # Legibility: the states that must never be missed, at three brightnesses.
    urgent_low = dict(F.STATES)["urgent-low"]
    stale = dict(F.STATES)["stale"]
    bright = []
    for reading in (in_range, urgent_low, stale):
        for _, level in LEVELS:
            bright.append(F.face_hero_delta(reading).dimmed(level))
    sheet(bright, "brightness-floor.png")

    dim_cells = {}
    for slug, name, fn, about in F.FACES:
        for state, reading in F.STATES:
            p = fn(reading).dimmed(60)
            dim_cells[(slug, state)] = R.data_uri(R.png_leds(p, scale=10))

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
    state_names = [s for s, _ in F.STATES]
    for slug, name, fn, about in F.FACES:
        html.append(f"<h2>{name}</h2><p class='about'>{about}</p><table><tr><th></th>")
        html += [f"<th>{s}</th>" for s in state_names]
        html.append("</tr><tr><th>full</th>")
        html += [f"<td><img src='{cells[(slug, s)]}' alt='{name} {s}'></td>" for s in state_names]
        html.append("</tr><tr><th>night</th>")
        html += [f"<td><img src='{dim_cells[(slug, s)]}' alt='{name} {s} dim'></td>" for s in state_names]
        html.append("</tr></table>")
    html.append(
        "<p class='note'>Every frame here is a real 52&times;16 pixel buffer - the same buffer the "
        "device pusher would send as a base64 PNG (measured 41 fps end to end on 2026-09-25).</p>"
    )
    html.append("</body></html>")
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(html))

    print(f"wrote {len(F.FACES)} face sheets + all-faces + brightness-floor + index.html to {OUT}")


if __name__ == "__main__":
    main()
