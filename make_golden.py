"""The golden frame corpus: every face in every state, rendered once, kept forever.

    python make_golden.py            # (re)write golden/
    python make_golden.py --check    # re-render and compare; exit 1 on any difference
    python make_golden.py --self-test  # prove --check can fail: plant one wrong pixel

Why this exists: Track B (our own firmware for the TC002) must draw the same faces
as this renderer, and "the same" has to mean byte-for-byte or it means nothing. So
every face x state is rendered here to a 1:1 PNG plus the raw RGB888 bytes' SHA-256,
with the exact inputs that produced it, and a firmware renderer passes when it
reproduces every hash. A face change on this side regenerates the corpus in the same
commit, so the diff shows exactly which frames moved.

Determinism: faces plot history against wall-clock time, so `time.time` is pinned to
FIXED_NOW *before* faces.py is imported (its demo STATES build their timestamps at
import). Anything that still varies between runs is a bug in a face, and --check
catches it.
"""

import hashlib
import json
import os
import sys
import time

FIXED_NOW = 1790510400  # 2026-09-27 12:00:00 UTC, arbitrary and permanent
time.time = lambda: FIXED_NOW  # noqa: E305 - must precede the faces import

import faces as F  # noqa: E402
import render as R  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "golden")
MANIFEST = os.path.join(OUT, "manifest.json")


def raw_rgb(panel):
    return bytes(v for row in panel.px for px in row for v in px)


def entry(slug, state, reading, panel):
    raw = raw_rgb(panel)
    return {
        "face": slug,
        "state": state,
        "file": f"{slug}--{state}.png",
        "width": panel.w,
        "height": panel.h,
        "sha256_rgb888": hashlib.sha256(raw).hexdigest(),
        "lit_pixels": sum(1 for row in panel.px for c in row if any(c)),
        "clipped": panel.clipped,
        "inputs": {
            "sgv": reading.sgv,
            "trend": reading.trend,
            "delta": reading.delta,
            "minutes_ago": reading.minutes_ago,
            "time": reading.time,
            "stale": reading.stale,
            "history": [[int(e), int(v)] for e, v in reading.history],
        },
    }


def render_all():
    for slug, _name, fn, _desc in F.FACES:
        for state, reading in F.STATES:
            yield slug, state, reading, fn(reading)


def write():
    os.makedirs(OUT, exist_ok=True)
    entries = []
    for slug, state, reading, panel in render_all():
        e = entry(slug, state, reading, panel)
        with open(os.path.join(OUT, e["file"]), "wb") as fh:
            fh.write(R.png_raw(panel))
        entries.append(e)
    manifest = {
        "generator": "make_golden.py",
        "fixed_now": FIXED_NOW,
        "panel": {"width": R.W, "height": R.H, "pixel_format": "RGB888 row-major, top-left origin"},
        "thresholds_mgdl": {"urgent_low": F.URGENT_LOW, "warn_low": F.WARN_LOW,
                             "warn_high": F.WARN_HIGH, "urgent_high": F.URGENT_HIGH},
        "stale_minutes": F.STALE_MINUTES,
        "colors_rgb888": {"normal": R.BG_NORMAL, "warning": R.BG_WARNING, "urgent": R.BG_URGENT,
                          "stale": R.GRAY, "white": R.WHITE},
        "dim_rule": "FastLED scale8 fixed: c * (factor + 1) >> 8, per channel",
        "frames": entries,
    }
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=False)
        fh.write("\n")
    print(f"wrote {len(entries)} frames + manifest to {OUT}")
    return 0


def check(tamper=None):
    with open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)
    want = {(e["face"], e["state"]): e for e in manifest["frames"]}
    bad, seen = [], 0
    for slug, state, reading, panel in render_all():
        seen += 1
        if tamper == (slug, state):
            panel.px[0][0] = R.WHITE  # a planted fault; the check must notice
        e = want.get((slug, state))
        if e is None:
            bad.append(f"{slug}/{state}: not in manifest")
            continue
        got = hashlib.sha256(raw_rgb(panel)).hexdigest()
        if got != e["sha256_rgb888"]:
            bad.append(f"{slug}/{state}: rendered {got[:12]} != golden {e['sha256_rgb888'][:12]}")
    if seen != len(want):
        bad.append(f"manifest has {len(want)} frames, renderer produced {seen}")
    for line in bad:
        print("DIFF", line)
    print(f"{len(bad)} difference(s) across {seen} frames")
    return 1 if bad else 0


def self_test():
    """The check is worth something only if it can fail."""
    clean = check()
    planted = check(tamper=("hero", "in-range"))
    ok = clean == 0 and planted == 1
    print("self-test:", "PASS - clean corpus passes, one planted pixel fails" if ok
          else f"FAIL - clean={clean} planted={planted}")
    return 0 if ok else 1


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"--check": check, "--self-test": self_test}.get(arg, write)())
