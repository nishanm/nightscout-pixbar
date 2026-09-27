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

Thresholds are the ones our clocks run: 55 / 70 / 180 / 250 mg/dL.
"""

import time as _time

import render as R

URGENT_LOW, WARN_LOW, WARN_HIGH, URGENT_HIGH = 55, 70, 180, 250
STALE_MINUTES = 20

PAD = 1  # left/right margin; nothing but a full-bleed graph touches the edge


class Reading:
    def __init__(self, sgv, trend, delta, minutes_ago=3, time="14:32", history=None):
        self.sgv = sgv
        self.trend = trend
        self.delta = delta
        self.minutes_ago = minutes_ago
        self.time = time
        self.history = history or []

    @property
    def stale(self):
        return self.minutes_ago >= STALE_MINUTES

    def value_text(self):
        return "---" if self.stale else str(self.sgv)

    def delta_text(self):
        # None means "cannot be stated honestly" (see sources.delta_for) and must
        # render as "?", never as +0 - a zero delta on a falling glucose is worse
        # than no delta at all.
        if self.stale:
            return ""
        return "?" if self.delta is None else f"{self.delta:+d}"


def color_for(sgv):
    if sgv <= URGENT_LOW or sgv >= URGENT_HIGH:
        return R.BG_URGENT
    if sgv < WARN_LOW or sgv > WARN_HIGH:
        return R.BG_WARNING
    return R.BG_NORMAL


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
    diagonal. Doubles get two chevrons."""
    if trend == "NONE":
        # Fit the question mark to the box the caller gave us. The clock face
        # allows 6 rows, which is smaller than any Spleen glyph, so fall back to
        # the 3x5 font rather than spilling off the panel.
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


def row_for(sgv, top, bottom):
    for lo, hi, first, last in _bands(top, bottom):
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
    if rails:
        # The in-range band gets a dim floor and ceiling so the trace has a frame
        # of reference. Marking the urgent rows instead (first pass) painted red
        # across a perfectly healthy panel.
        _, _, in_first, in_last = _bands(top, bottom)[2]
        for gx in range(x, x + w, 3):
            panel.set(gx, in_first, R.dim(R.WHITE, 34))
            panel.set(gx, in_last, R.dim(R.WHITE, 34))
    for point in history:
        epoch, sgv = point if isinstance(point, (tuple, list)) else (None, point)
        if sgv is None:
            continue
        if epoch is None:      # no timestamps: fall back to even spacing
            continue
        age_minutes = (now - epoch) / 60.0
        if age_minutes < 0 or age_minutes > span_minutes:
            continue
        col = x + w - 1 - int(round(age_minutes / span_minutes * (w - 1)))
        panel.set(col, row_for(sgv, top, bottom), color_for(sgv))


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
    trend_mark(p, max(free + 2, 52 - mark_w - PAD), 1, "NONE" if r.stale else r.trend, c, w=mark_w)
    return p


def face_hero_delta(r):
    """Hero value, direction, and the small facts that still fit beside them."""
    p = R.Panel()
    c = reading_color(r)
    free = hero_value(p, r, c) + 2
    mark_w = 7
    trend_mark(p, free, 1, "NONE" if r.stale else r.trend, c, w=mark_w, h=15)
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
    draw_graph(p, max(free + 2, 31), 0, 52 - max(free + 2, 31), 16, r.history)
    return p


def face_clock(r):
    """Bedside: time and value side by side, both at one readable size."""
    p = R.Panel()
    c = reading_color(r)
    # Time is secondary, so it takes the small font; the value stays MID and
    # right-aligned. 23 + 18 + margins fits 52 with room to breathe.
    R.font_text(p, PAD, 1, r.time, R.SMALL, R.dim(R.WHITE, 110))
    R.font_text_right(p, 51 - PAD, 3, r.value_text(), R.MID, c)
    trend_mark(p, PAD, 10, "NONE" if r.stale else r.trend, c, w=7, h=6)
    age_pips(p, 12, 13, r.minutes_ago, c)
    return p


def face_big_graph(r):
    """The panel is history. The value rides on the right over a cleared box."""
    p = R.Panel()
    c = reading_color(r)
    draw_graph(p, 0, 0, 52, 16, r.history)
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


FACES = [
    ("hero", "Hero", face_hero, "One number filling the panel, plus direction"),
    ("hero-delta", "Hero + delta", face_hero_delta, "Hero value, direction, delta and age pips"),
    ("hero-graph", "Hero + graph", face_hero_graph, "Hero value left, history right"),
    ("clock", "Clock + value", face_clock, "Time and value side by side, bedside face"),
    ("big-graph", "Big graph", face_big_graph, "Full-panel history, value riding on the right"),
    ("no-data", "No data", face_no_data, "Explicit stale state with minutes since last reading"),
]


# ------------------------------------------------------------------ demo states
def _history(base, drift, n=36, jitter=(0, 3, -2, 5, -4, 2, -1, 4), newest_age_min=3):
    """[(epoch, sgv)] on the real 5-minute CGM cadence, newest last."""
    out, v = [], base - drift * n * 0.6
    now = _time.time()
    for i in range(n):
        v += drift + jitter[i % len(jitter)] * 0.5
        age = (n - 1 - i) * 5 + newest_age_min
        out.append((int(now - age * 60), int(max(40, min(320, v))))) 
    out[-1] = (out[-1][0], base)
    return out


STATES = [
    ("in-range", Reading(118, "FLAT", 2, 3, "14:32", _history(118, 0.2))),
    ("warn-high", Reading(210, "SINGLE_UP", 12, 4, "21:07", _history(210, 0.9))),
    ("urgent-high", Reading(287, "DOUBLE_UP", 21, 2, "22:15", _history(287, 1.6))),
    ("warn-low", Reading(66, "SINGLE_DOWN", -9, 3, "03:41", _history(66, -0.8))),
    ("urgent-low", Reading(48, "DOUBLE_DOWN", -15, 2, "03:58", _history(48, -1.4))),
    ("stale", Reading(104, "FLAT", 0, 27, "07:12", _history(104, 0.1)[:-5])),
]
