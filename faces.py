"""Glucose faces drawn native for the TC002's 52x16 panel.

Second pass. The first one was judged on the hardware and looked cheap, for three
reasons the vendor's own apps get right:

1. **Real letterforms.** Hand-rolled seven-segment digits read as a calculator.
   Ulanzi's reference renderer (apps/mqtt/nowplaying) bakes a proper pixel font
   with a 1 px inter-character gap for exactly this reason. We use Spleen.
2. **One hero element, filling the height.** Their nowplaying app gives the whole
   16 rows to one thing and puts a single icon beside it. The first pass had four
   elements at 5 px each, so nothing was legible across a room.
3. **Zones with margins,** not items dropped at hand-tuned coordinates.

Colour is not decoration here: the value's colour IS the glucose state
(BG_COLOR_NORMAL / _WARNING / _URGENT, src/globals.h:59-61), so everything else
stays white or dim and never competes with it.

What a reading is - thresholds, stale, delta, trend vocabulary - lives in
model.py. This file only decides how it looks.
"""

import time as _time
from collections import namedtuple

import render as R
from model import (STALE_MINUTES, URGENT_HIGH, URGENT_LOW, WARN_HIGH, WARN_LOW,
                   Reading, band)

PAD = 1  # left/right margin; nothing but a full-bleed graph touches the edge

_BAND_COLOR = {"normal": R.BG_NORMAL, "warning": R.BG_WARNING, "urgent": R.BG_URGENT}


def color_for(sgv):
    return _BAND_COLOR[band(sgv)]


def reading_color(r):
    return R.GRAY if r.stale else color_for(r.sgv)


# ------------------------------------------------------------------ trend mark
# Drawn, not bitmapped, so it scales with whatever it sits beside. A chevron
# stack reads as direction at a glance where a thin arrow turns to mush.
_SLOPE = {
    "DOUBLE_UP": 2, "SINGLE_UP": 2, "FORTY_FIVE_UP": 1, "FLAT": 0,
    "FORTY_FIVE_DOWN": -1, "SINGLE_DOWN": -2, "DOUBLE_DOWN": -2, "NONE": 0,
}


def trend_mark(panel, x, y, trend, color, w=9, h=15):
    """Up/down: stacked chevrons on a stem. Flat: a bar with a head. 45s: a
    diagonal. Doubles get two chevrons. NONE: a question mark that fits the box."""
    if trend == "NONE":
        # Largest glyph that fits the height given; below every Spleen size
        # (the clock face offers 6 rows) the 3x5 font is the honest fallback.
        for font in (R.MID, R.SMALL):
            gh = R.font_height(font, "?")
            if gh <= h:
                R.font_text(panel, x, y + (h - gh) // 2, "?", font, color)
                return
        R.tiny(panel, x, y + max(0, (h - R.TINY_H) // 2), "?", color)
        return
    slope = _SLOPE.get(trend, 0)
    mid = y + h // 2
    if slope == 0:
        panel.rect(x, mid - 1, w - 3, 2, color)          # shaft
        for i in range(3):                                # head, 5 -> 1 tall
            panel.rect(x + w - 3 + i, mid - 2 + i, 1, 5 - 2 * i, color)
        return
    if abs(slope) == 1:
        span = min(w, h)
        for i in range(span):
            yy = y + (h - 2 - i) if slope > 0 else y + i
            panel.rect(x + i, yy, 2, 2, color)
        head_y = y if slope > 0 else y + h - 2
        panel.rect(x + w - 6, head_y, 6, 2, color)
        panel.rect(x + w - 2, head_y if slope > 0 else head_y - 4, 2, 6, color)
        return
    count = 2 if trend in ("DOUBLE_UP", "DOUBLE_DOWN") else 1
    stem = x + w // 2 - 1
    panel.rect(stem, y, 2, h, color)
    reach = w // 2
    for n in range(count):
        base = (y + n * (h // 2 - 1)) if slope > 0 else (y + h - 2 - n * (h // 2 - 1))
        for i in range(reach):
            yy = base + i if slope > 0 else base - i
            panel.rect(stem - i, yy, 2, 1, color)
            panel.rect(stem + i, yy, 2, 1, color)


# ------------------------------------------------------------------------ graph
def _bands(top, bottom):
    """Fixed row ranges per band, like BGDisplayFaceGraphBase.cpp: the reader sees
    "in the red zone" without reading an axis."""
    h = bottom - top + 1
    urgent = 1 if h < 10 else 2
    warn = 1 if h < 8 else 2
    return [
        (URGENT_HIGH, 10**6, top, top + urgent - 1),
        (WARN_HIGH, URGENT_HIGH, top + urgent, top + urgent + warn - 1),
        (WARN_LOW, WARN_HIGH, top + urgent + warn, bottom - urgent - warn),
        (URGENT_LOW, WARN_LOW, bottom - urgent - warn + 1, bottom - urgent),
        (0, URGENT_LOW, bottom - urgent + 1, bottom),
    ]


def row_for(sgv, bands, bottom):
    for lo, hi, first, last in bands:
        if lo <= sgv < hi:
            frac = min(1.0, max(0.0, (sgv - lo) / max(1, hi - lo)))
            return int(round(last - frac * (last - first)))
    return bottom


def draw_graph(panel, x, y, w, h, history, rails=True, span_minutes=180, now=None):
    """history is [(epoch, sgv)]. Plotted against TIME, not array position:
    Dexcom Share repeats a reading ~11 s later and drops others entirely, so an
    index-based x axis silently stretches and squeezes the timeline."""
    top, bottom = y, y + h - 1
    now = now if now is not None else _time.time()
    bands = _bands(top, bottom)
    if rails:
        # The in-range band gets a dim floor and ceiling so the trace has a frame
        # of reference. Marking the urgent rows instead (first pass) painted red
        # across a perfectly healthy panel.
        _, _, in_first, in_last = bands[2]
        rail = R.dim(R.WHITE, 34)
        for gx in range(x, x + w, 3):
            panel.set(gx, in_first, rail)
            panel.set(gx, in_last, rail)
    for epoch, sgv in history:
        age_minutes = (now - epoch) / 60.0
        if age_minutes < 0 or age_minutes > span_minutes:
            continue
        col = x + w - 1 - int(round(age_minutes / span_minutes * (w - 1)))
        panel.set(col, row_for(sgv, bands, bottom), color_for(sgv))


def age_pips(panel, x, y, minutes_ago, color, count=4, gap=2):
    """How stale, as pips that go out one by one. Four steps is all a glance can
    carry; the first pass used an 8 px bar and it read as decoration."""
    lit = count - min(count, int(minutes_ago / (STALE_MINUTES / count)))
    for i in range(count):
        panel.set(x + i * (1 + gap), y, color if i < lit else R.dim(color, 14))


# ------------------------------------------------------------------------ faces
def hero_value(panel, r, color):
    """Draw the value as large as it goes, vertically centred, and report the
    first free column. 48 and 287 are different widths, so nothing downstream
    may assume a fixed one - that assumption is what made the first pass collide."""
    text = r.value_text()
    h = R.font_height(R.HERO, text)
    y = (16 - h) // 2
    end = R.font_text(panel, PAD, y, text, R.HERO, color)
    return end + 1


def face_hero(r):
    """One number, as big as the panel allows, plus direction. Nothing else."""
    p = R.Panel()
    c = reading_color(r)
    free = hero_value(p, r, c)
    mark_w = 9
    trend_mark(p, max(free + 2, 52 - mark_w - PAD), 1, r.trend_shown, c, w=mark_w)
    return p


def face_hero_delta(r):
    """Hero value, direction, and the small facts that still fit beside them."""
    p = R.Panel()
    c = reading_color(r)
    free = hero_value(p, r, c) + 2
    mark_w = 7
    trend_mark(p, free, 1, r.trend_shown, c, w=mark_w, h=15)
    right = free + mark_w + 2
    delta = r.delta_text()
    # Only claim the right column when the value actually left one - a 3-digit
    # reading plus a mark is already 48 of the 52 columns.
    last = 51 - PAD
    if delta and right + R.font_width(R.SMALL, delta) - 1 <= last:
        R.font_text(p, right, 1, delta, R.SMALL, R.dim(R.WHITE, 150))
        age_pips(p, right, 13, r.minutes_ago, c)
    else:
        age_pips(p, last - 9, 14, r.minutes_ago, c)
    return p


def face_hero_graph(r):
    """Hero value on the left, three and a half hours of history on the right."""
    p = R.Panel()
    c = reading_color(r)
    free = hero_value(p, r, c)
    gx = max(free + 2, 31)
    draw_graph(p, gx, 0, 52 - gx, 16, r.history, now=r.now)
    return p


def face_clock(r):
    """Bedside: time and value side by side, both at one readable size."""
    p = R.Panel()
    c = reading_color(r)
    # Time is secondary, so it takes the small font; the value stays MID and
    # right-aligned. 23 + 18 + margins fits 52 with room to breathe.
    R.font_text(p, PAD, 1, r.time, R.SMALL, R.dim(R.WHITE, 110))
    R.font_text_right(p, 51 - PAD, 3, r.value_text(), R.MID, c)
    trend_mark(p, PAD, 10, r.trend_shown, c, w=7, h=6)
    age_pips(p, 12, 13, r.minutes_ago, c)
    return p


def face_big_graph(r):
    """The panel is history. The value rides on the right over a cleared box."""
    p = R.Panel()
    c = reading_color(r)
    draw_graph(p, 0, 0, 52, 16, r.history, now=r.now)
    label = r.value_text()
    w = R.font_width(R.MID, label)
    p.rect(52 - w - 3, 2, w + 3, 12, R.BLACK)
    R.font_text_right(p, 51, 3, label, R.MID, c)
    return p


def face_no_data(r):
    """Not a blank value - a statement, with how long it has been that way."""
    p = R.Panel()
    # Two stacked 8-row lines exactly fill 16 rows, so they touch and read as
    # mush. The red "?" already says "no reading"; the only other fact worth
    # the space is how long, so it gets one line at a size that can be read.
    R.font_text(p, PAD, (16 - R.font_height(R.HERO, "?")) // 2, "?", R.HERO, R.BG_URGENT)
    label = f"{r.minutes_ago}M"
    R.font_text_right(p, 51 - PAD, (16 - R.font_height(R.MID, label)) // 2, label,
                      R.MID, R.dim(R.WHITE, 150))
    return p


# --------------------------------------------------------------------- registry
# Everything a tool needs to know about a face lives on the face: which demo
# state shows it off, and whether it may touch the panel's edge columns (the
# graphs are full-bleed by design; anything else touching column 0 or 51 is one
# pixel from being clipped). Tools ask the record instead of keeping their own
# lists of exceptions.
Face = namedtuple("Face", "slug name fn about full_bleed demo_state")

FACES = [
    Face("hero", "Hero", face_hero, "One number filling the panel, plus direction", False, "in-range"),
    Face("hero-delta", "Hero + delta", face_hero_delta, "Hero value, direction, delta and age pips", False, "in-range"),
    Face("hero-graph", "Hero + graph", face_hero_graph, "Hero value left, history right", True, "in-range"),
    Face("clock", "Clock + value", face_clock, "Time and value side by side, bedside face", False, "in-range"),
    Face("big-graph", "Big graph", face_big_graph, "Full-panel history, value riding on the right", True, "in-range"),
    Face("no-data", "No data", face_no_data, "Explicit stale state with minutes since last reading", False, "stale"),
]
SLUGS = [f.slug for f in FACES]
_BY_SLUG = {f.slug: f for f in FACES}


def face(slug):
    """The Face record for a slug, or None."""
    return _BY_SLUG.get(slug)


# ------------------------------------------------------------------ demo states
def _history(base, drift, now, n=36, jitter=(0, 3, -2, 5, -4, 2, -1, 4), newest_age_min=3):
    """[(epoch, sgv)] on the real 5-minute CGM cadence, newest last."""
    out, v = [], base - drift * n * 0.6
    for i in range(n):
        v += drift + jitter[i % len(jitter)] * 0.5
        age = (n - 1 - i) * 5 + newest_age_min
        out.append((int(now - age * 60), int(max(40, min(320, v)))))
    out[-1] = (out[-1][0], base)
    return out


STATE_NAMES = ["in-range", "warn-high", "urgent-high", "warn-low", "urgent-low", "stale"]


def demo_states(now=None):
    """The six readings every face is judged in, as of `now` (default: the
    wall clock). Pass a fixed `now` for a reproducible corpus - the histories
    and the graphs both hang off it, so one value pins everything."""
    now = _time.time() if now is None else now

    def r(sgv, trend, delta, minutes_ago, clock, drift, cut=None):
        history = _history(sgv, drift, now)
        return Reading(sgv, trend, delta, minutes_ago, clock, history[:cut], now=now)

    return [
        ("in-range", r(118, "FLAT", 2, 3, "14:32", 0.2)),
        ("warn-high", r(210, "SINGLE_UP", 12, 4, "21:07", 0.9)),
        ("urgent-high", r(287, "DOUBLE_UP", 21, 2, "22:15", 1.6)),
        ("warn-low", r(66, "SINGLE_DOWN", -9, 3, "03:41", -0.8)),
        ("urgent-low", r(48, "DOUBLE_DOWN", -15, 2, "03:58", -1.4)),
        ("stale", r(104, "FLAT", 0, 27, "07:12", 0.1, cut=-5)),
    ]


def state(name, now=None):
    """One demo reading by name."""
    return dict(demo_states(now))[name]


def every_frame(now=None):
    """Every face in every demo state, rendered: (face, state_name, reading,
    panel). FACES outer, states inner - the golden manifest's order."""
    states = demo_states(now)
    for f in FACES:
        for name, reading in states:
            yield f, name, reading, f.fn(reading)
