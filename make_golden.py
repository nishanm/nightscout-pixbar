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

Determinism: the demo states and the graphs both hang off one `now`, which
`faces.every_frame(now=FIXED_NOW)` pins. Anything that still varies between runs
is a bug in a face, and --check catches it.
"""

import hashlib
import json
import os
import sys

import faces as F
import model as M
import render as R

FIXED_NOW = 1790510400  # 2026-09-27 12:00:00 UTC, arbitrary and permanent

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "golden")
MANIFEST = os.path.join(OUT, "manifest.json")


def entry(face, state, reading, panel):
    return {
        "face": face.slug,
        "state": state,
        "file": f"{face.slug}--{state}.png",
        "width": panel.w,
        "height": panel.h,
        "sha256_rgb888": hashlib.sha256(R.raw_rgb(panel)).hexdigest(),
        "lit_pixels": R.lit_pixels(panel),
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


def write():
    os.makedirs(OUT, exist_ok=True)
    entries = []
    for face, state, reading, panel in F.every_frame(now=FIXED_NOW):
        e = entry(face, state, reading, panel)
        with open(os.path.join(OUT, e["file"]), "wb") as fh:
            fh.write(R.png_raw(panel))
        entries.append(e)
    manifest = {
        "generator": "make_golden.py",
        "fixed_now": FIXED_NOW,
        "panel": {"width": R.W, "height": R.H, "pixel_format": "RGB888 row-major, top-left origin"},
        "thresholds_mgdl": {"urgent_low": M.URGENT_LOW, "warn_low": M.WARN_LOW,
                             "warn_high": M.WARN_HIGH, "urgent_high": M.URGENT_HIGH},
        "stale_minutes": M.STALE_MINUTES,
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
    for face, state, _reading, panel in F.every_frame(now=manifest["fixed_now"]):
        seen += 1
        if tamper == (face.slug, state):
            panel.px[0][0] = R.WHITE  # a planted fault; the check must notice
        e = want.get((face.slug, state))
        if e is None:
            bad.append(f"{face.slug}/{state}: not in manifest")
            continue
        got = hashlib.sha256(R.raw_rgb(panel)).hexdigest()
        if got != e["sha256_rgb888"]:
            bad.append(f"{face.slug}/{state}: rendered {got[:12]} != golden {e['sha256_rgb888'][:12]}")
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
