"""Poll the glucose source, render a face, push it to the TC002. Run forever.

    python daemon.py                 # uses config.py resolution
    python daemon.py --once          # one cycle, then exit
    python daemon.py --face hero     # override the face

Two behaviours exist because of things measured on the hardware, not guessed:

* **The custom app is re-created when it disappears.** A restart clears custom
  apps (measured 2026-09-26), so a pusher that assumes its app still exists
  goes quietly blank after a device reboot. Every cycle checks /api/customList.
* **A failure draws a face, it does not skip a frame.** A glucose display that
  freezes on an old number is worse than one that says it has no data, because
  a stale reading still looks like a reading.

Still unsolved, and not solvable from here: nothing in the device API can bring
an app on screen (verified on 1.0.8 and 1.1.3), so if the knob is turned away
this keeps updating a page nobody is looking at.
"""

import argparse
import json
import sys
import time
import urllib.request

import config as C
import faces as F
import push
import render as R
import sources

STALE_AFTER = F.STALE_MINUTES * 60


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def app_exists(host, app):
    try:
        with urllib.request.urlopen(f"http://{host}/api/customList", timeout=5) as r:
            return app in (json.loads(r.read().decode()).get("apps") or [])
    except Exception:
        return False  # unreachable counts as "assume not there", and we re-push


def to_reading(readings, units="mgdl"):
    """Newest reading, its delta by the firmware's window rule, and the history
    as (epoch, sgv) so the graph can plot against time."""
    latest = readings[-1]
    delta = sources.delta_for(readings)
    minutes_ago = max(0, int((time.time() - latest.epoch) / 60))
    history = [(r.epoch, r.sgv) for r in readings]
    return F.Reading(
        sgv=latest.sgv,
        trend=latest.trend,
        delta=delta,
        minutes_ago=minutes_ago,
        time=time.strftime("%H:%M"),
        history=history,
    )


def error_reading(reason, minutes_ago=999):
    """A Reading that renders as the no-data state, carrying why."""
    r = F.Reading(0, "NONE", 0, minutes_ago, time.strftime("%H:%M"), [])
    r.reason = reason
    return r


def cycle(cfg, source, face_fn, last_good):
    host, app = cfg["host"], cfg["app"]
    try:
        readings = source.fetch()
        if not readings:
            raise sources.SourceError("source returned no readings", "NO DATA")
        reading = to_reading(readings, cfg.get("units", "mgdl"))
        last_good = reading
        age = int(time.time() - readings[-1].epoch)
        state = "stale" if age > STALE_AFTER else "ok"
        shown = "?" if reading.delta is None else f"{reading.delta:+d}"
        log(f"{reading.sgv} {reading.trend} delta={shown} "
            f"age={reading.minutes_ago}m points={len(reading.history)} [{state}]")
    except sources.SourceError as exc:
        # Keep showing the last good reading, ageing, so the panel degrades into
        # the stale face by itself rather than jumping straight to an error.
        log(f"source error: {exc} ({exc.reason}){' FATAL' if exc.fatal else ''}")
        if last_good is not None:
            last_good.minutes_ago += max(1, cfg["poll_seconds"] // 60)  # age it honestly
            reading = last_good
            face_fn = F.face_no_data if last_good.minutes_ago >= F.STALE_MINUTES else face_fn
        else:
            reading = error_reading(exc.reason)
            face_fn = F.face_no_data
        if exc.fatal:
            log("credentials or config are wrong - not retrying in a tight loop")

    panel = face_fn(reading)
    if panel.clipped:
        log(f"WARNING: {panel.clipped} pixels drawn off-panel (run audit.py)")
    if not app_exists(host, app):
        log(f"custom app {app!r} was missing - re-creating it (device restart?)")
    try:
        ms, size, body = push.send_panel(host, app, panel, duration=300)
        if '"code":200' not in body:
            log(f"device refused the frame: {body.strip()}")
    except Exception as exc:
        log(f"push failed: {exc}")
    return last_good


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--face")
    ap.add_argument("--host")
    ap.add_argument("--poll", type=int)
    args = ap.parse_args()

    cfg = C.load()
    if args.face:
        cfg["face"] = args.face
    if args.host:
        cfg["host"] = args.host
    if args.poll:
        cfg["poll_seconds"] = args.poll
    log(C.describe(cfg))

    try:
        source = sources.build(cfg)
    except sources.SourceError as exc:
        log(f"cannot build source: {exc}")
        return 2

    face_fn = dict((s, f) for s, _, f, _ in F.FACES).get(cfg["face"])
    if face_fn is None:
        log(f"unknown face {cfg['face']!r}; known: {[s for s, _, _, _ in F.FACES]}")
        return 2

    last_good = None
    while True:
        last_good = cycle(cfg, source, face_fn, last_good)
        if args.once:
            return 0
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    sys.exit(main())
