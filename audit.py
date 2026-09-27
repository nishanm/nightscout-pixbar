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
MUST_SURVIVE_FLOOR = ("urgent-low", "urgent-high", "stale")


def main():
    problems = []
    seen = 0
    for face, state, _reading, panel in F.every_frame():
        seen += 1
        where = f"{face.slug}/{state}"

        if panel.clipped:
            problems.append(("clipped", where, f"{panel.clipped} lit pixels off-panel"))

        if not face.full_bleed:
            cols = [c for c in (0, panel.w - 1)
                    if any(any(panel.px[y][c]) for y in range(panel.h))]
            if cols:
                problems.append(("edge", where, f"ink in column(s) {cols}"))

        n = R.lit_pixels(panel)
        if n < MIN_LIT:
            problems.append(("empty", where, f"only {n} lit pixels"))

        night = R.lit_pixels(panel.dimmed(NIGHT))
        if n and night < n * 0.5:
            problems.append(("contrast", where,
                             f"{n - night} of {n} pixels vanish at night level {NIGHT}"))
        # The state itself must survive the floor, whatever the decoration does.
        if state in MUST_SURVIVE_FLOOR and R.lit_pixels(panel.dimmed(FLOOR)) == 0:
            problems.append(("contrast", where, f"nothing visible at floor level {FLOOR}"))

    for kind, where, detail in problems:
        print(f"{kind:<9} {where:<22} {detail}")
    print(f"\n{len(problems)} problem(s) across {seen} face/state combinations")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
