"""The glucose model: what a reading IS, independent of where it came from or how
it is drawn.

One home for the facts that sources.py (the wire), faces.py (the pixels), the
daemon (the timing) and export_fonts.py (the firmware headers) all previously
carried their own copy of: the thresholds, the stale rule, the trend vocabulary,
the delta rule, and the reading itself. Track B's firmware is a port of this file
before it is a port of anything else.

Nothing here imports render or faces. Colour is a display decision, so this
module says which BAND a value is in and the face decides what colour a band is.
"""

import time

# mg/dL, the ones the owner's TC001 clocks run (src/globals.h thresholds).
URGENT_LOW, WARN_LOW, WARN_HIGH, URGENT_HIGH = 55, 70, 180, 250

# A reading older than this is a *state*, shown as such, never a frozen number.
STALE_MINUTES = 20

# src/enums.h BG_TREND - the vocabulary sources map into and faces dispatch on.
TRENDS = ("DOUBLE_UP", "SINGLE_UP", "FORTY_FIVE_UP", "FLAT",
          "FORTY_FIVE_DOWN", "SINGLE_DOWN", "DOUBLE_DOWN", "NONE")

# src/BGDisplayFaceValueAndDiff.cpp:37-91. Not "latest minus previous": Dexcom
# Share returns the same reading twice about 11 s apart, so the previous element
# is often the current one's twin and the delta comes out zero. The firmware
# takes everything inside a 6.5 minute window and works from its min and max,
# which is immune to that.
DIFF_WINDOW_SECONDS = 6 * 60 + 30


def band(sgv):
    """'urgent', 'warning' or 'normal' - the only three things a value can be."""
    if sgv <= URGENT_LOW or sgv >= URGENT_HIGH:
        return "urgent"
    if sgv < WARN_LOW or sgv > WARN_HIGH:
        return "warning"
    return "normal"


class Sample:
    """One reading as a source reports it: when, what, which way."""

    __slots__ = ("epoch", "sgv", "trend")

    def __init__(self, epoch, sgv, trend):
        self.epoch = int(epoch)
        self.sgv = int(sgv)
        self.trend = trend

    def __repr__(self):
        return f"Sample({self.sgv}, {self.trend}, {int(time.time()) - self.epoch}s ago)"


def delta_for(samples):
    """Change since the previous reading, or None when it cannot be stated.

    None means genuinely unknown - render it as "?", never as 0. A zero delta
    on a falling glucose is worse than no delta at all."""
    if len(samples) < 2:
        return None
    last = samples[-1]
    window = [s for s in samples if last.epoch - s.epoch <= DIFF_WINDOW_SECONDS]
    if len(window) > 5:  # Libre-style dense data: just the last two
        window = window[-2:]
    if len(window) < 2:
        return None
    lo = min(s.sgv for s in window)
    hi = max(s.sgv for s in window)
    base = last.sgv
    if lo != base and hi != base:
        return None  # moved both ways inside the window; no honest single number
    delta = base - hi if lo == base else base - lo
    return None if abs(delta) > 99 else delta


class Reading:
    """What a face is asked to draw: the newest value with its context, as of
    `now`. Built from samples by `from_samples`, or by hand for demo states.

    `minutes_ago` is stored rather than derived so a demo state can say exactly
    how old it is; `from_samples` derives it from the newest sample and `now`,
    and re-building from the same samples with a later `now` is how a reading
    ages when the source stops answering - no field is ever mutated."""

    def __init__(self, sgv, trend, delta, minutes_ago=3, time="14:32", history=None, now=None):
        self.sgv = sgv
        self.trend = trend
        self.delta = delta
        self.minutes_ago = minutes_ago
        self.time = time
        self.history = history or []
        self.now = now

    @classmethod
    def from_samples(cls, samples, now=None):
        """Newest sample, its delta by the firmware's window rule, and the
        history as (epoch, sgv) so a graph can plot against time."""
        now = time.time() if now is None else now
        latest = samples[-1]
        return cls(
            sgv=latest.sgv,
            trend=latest.trend,
            delta=delta_for(samples),
            minutes_ago=max(0, int((now - latest.epoch) / 60)),
            time=time.strftime("%H:%M", time.localtime(now)),
            history=[(s.epoch, s.sgv) for s in samples],
            now=now,
        )

    @property
    def stale(self):
        return self.minutes_ago >= STALE_MINUTES

    @property
    def trend_shown(self):
        """A stale reading has no direction worth drawing."""
        return "NONE" if self.stale else self.trend

    def value_text(self):
        return "---" if self.stale else str(self.sgv)

    def delta_text(self):
        # None means "cannot be stated honestly" (see delta_for) and must render
        # as "?", never as +0.
        if self.stale:
            return ""
        return "?" if self.delta is None else f"{self.delta:+d}"
