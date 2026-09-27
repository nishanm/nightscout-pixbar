"""Check every face in every state for the faults that only show on hardware.

    python audit.py

Catches:
  clipped   lit pixels drawn outside the 52x16 panel (how "3 MIN" lost its
            bottom row - Panel.set drops them silently)
  edge      ink in column 0 or 51 when the face is not a full-bleed graph, i.e.
            something is about to be clipped by a pixel
  empty     a face that draws almost nothing in some state
  contrast  ink that is invisible once the panel is dimmed to the night level

Exit code is non-zero if anything is found, so this can gate a push.
"""

import sys

import faces as F
import render as R

NIGHT = 60          # the dim level a night-time panel realistically runs at
FLOOR = 12          # worst case
MIN_LIT = 12        # fewer lit pixels than this is a face saying nothing
FULL_BLEED = {"big-graph", "hero-graph"}


def lit(panel):
    return sum(1 for row in panel.px for c in row if any(c))


def visible_at(panel, level):
    return sum(1 for row in panel.dimmed(level).px for c in row if any(c))


def main():
    problems = []
    for slug, name, fn, _ in F.FACES:
        for state, reading in F.STATES:
            panel = fn(reading)
            where = f"{slug}/{state}"

            if panel.clipped:
                problems.append(("clipped", where, f"{panel.clipped} lit pixels off-panel"))

            if slug not in FULL_BLEED:
                cols = [c for c in (0, panel.w - 1)
                        if any(any(panel.px[y][c]) for y in range(panel.h))]
                if cols:
                    problems.append(("edge", where, f"ink in column(s) {cols}"))

            n = lit(panel)
            if n < MIN_LIT:
                problems.append(("empty", where, f"only {n} lit pixels"))

            night, floor = visible_at(panel, NIGHT), visible_at(panel, FLOOR)
            if n and night < n * 0.5:
                problems.append(("contrast", where,
                                 f"{n - night} of {n} pixels vanish at night level {NIGHT}"))
            # The state itself must survive the floor, whatever the decoration does.
            if state in ("urgent-low", "urgent-high", "stale") and floor == 0:
                problems.append(("contrast", where, f"nothing visible at floor level {FLOOR}"))

    for kind, where, detail in problems:
        print(f"{kind:<9} {where:<22} {detail}")
    faces_x_states = len(F.FACES) * len(F.STATES)
    print(f"\n{len(problems)} problem(s) across {faces_x_states} face/state combinations")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
