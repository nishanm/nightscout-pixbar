"""Poll the glucose source, render a face, push it to the TC002. Run forever.

    python daemon.py                 # uses config.py resolution
    python daemon.py --once          # one cycle, then exit
    python daemon.py --face hero     # override the face

Behaviours that exist because of things measured on the hardware, not guessed:

* **The custom app is re-created when it disappears.** A restart clears custom
  apps (measured 2026-09-26), so a pusher that assumes its app still exists
  goes quietly blank after a device reboot. Every cycle checks /api/customList.
* **The app is brought on screen after it is (re)created.** `POST
  /api/switchDiyApp` (firmware 1.1.0+, measured on 1.1.3) puts the glucose page
  back after a reboot instead of leaving the weather up. It is NOT re-asserted
  every cycle by default - that would fight the knob - but PIXBAR_PIN_SECONDS=n
  re-asserts every n seconds for a panel nobody is meant to turn away from.
* **A failure draws a face, it does not skip a frame.** The last good samples
  are re-read as of now, so the reading ages honestly into the stale state; a
  glucose display frozen on an old number is worse than one that says so.
* **A fatal source error backs off** (5 -> 30 min) instead of retrying every
  minute: unattended for weeks against Dexcom Share, a wrong password polled
  in a tight loop is how the account gets locked.
"""

import argparse
import sys
import time
import traceback

import config as C
import faces as F
import sources
from device import Device, DeviceError
from model import Reading

FATAL_BACKOFF_MIN = 300
FATAL_BACKOFF_MAX = 1800


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def face_for(configured, reading):
    """Which face draws this reading. The configured one until the reading is
    stale - however it got stale: source down, uploader stopped, sensor in
    warm-up - then the explicit no-data face, because a grey `---` on the hero
    face says less than `? 27M`. Staleness is a property of the reading, not
    of the transport."""
    return F.face_no_data if reading.stale else configured


def cycle(cfg, source, dev, configured_face, last_samples, ask_source=True):
    """One poll-render-push. Returns (last_samples, fatal); fatal means the
    source said retrying will not help, and the caller backs off the SOURCE
    while this keeps running every period, so the panel keeps ageing."""
    now = time.time()
    fatal = False
    try:
        if not ask_source:
            raise sources.SourceError("source in backoff", "BACKOFF")
        samples = source.fetch()
        if not samples:
            raise sources.SourceError("source returned no readings", "NO DATA")
        last_samples = samples
        reading = Reading.from_samples(samples, now)
        log(f"{reading.sgv} {reading.trend} delta={reading.delta_text() or '-'} "
            f"age={reading.minutes_ago}m points={len(samples)} "
            f"[{'stale' if reading.stale else 'ok'}]")
    except sources.SourceError as exc:
        if exc.reason != "BACKOFF":
            log(f"source error: {exc} ({exc.reason}){' FATAL' if exc.fatal else ''}")
        fatal = exc.fatal
        if last_samples:
            reading = Reading.from_samples(last_samples, now)   # same data, older
        else:
            reading = Reading(0, "NONE", None, 999, time.strftime("%H:%M"), [], now=now)

    panel = face_for(configured_face, reading)(reading)
    if panel.clipped:
        log(f"WARNING: {panel.clipped} pixels drawn off-panel (run audit.py)")

    missing = not dev.app_exists()
    if missing:
        log(f"custom app {dev.app!r} was missing - re-creating it (device restart?)")
    try:
        _, _, reply = dev.send_panel(panel, duration=300)
        if reply.get("code") != 200:
            log(f"device refused the frame: {reply}")
        elif missing:
            # It exists again; now put it on screen, or the reboot leaves the
            # panel on whatever app the device woke up showing.
            log(f"switch to {dev.app!r}: {dev.switch_to()}")
    except DeviceError as exc:
        log(f"push failed: {exc}")
    return last_samples, fatal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--face")
    ap.add_argument("--host")
    ap.add_argument("--poll", type=int)
    ap.add_argument("--switch", action="store_true",
                    help="bring the app on screen at start (always done after a re-create)")
    args = ap.parse_args()

    cfg = C.load()
    for key, value in (("face", args.face), ("host", args.host), ("poll_seconds", args.poll)):
        if value:
            cfg[key] = value
    log(C.describe(cfg))

    try:
        source = sources.build(cfg)
    except sources.SourceError as exc:
        log(f"cannot build source: {exc}")
        return 2

    face = F.face(cfg["face"])
    if face is None:
        log(f"unknown face {cfg['face']!r}; known: {F.SLUGS}")
        return 2

    dev = Device(cfg["host"], cfg["app"])
    period = cfg["poll_seconds"]
    pin = int(cfg.get("pin_seconds") or 0)

    def switch(why):
        try:
            log(f"{why}: switch to {dev.app!r}: {dev.switch_to()}")
        except DeviceError as exc:
            log(f"{why}: switch failed: {exc}")

    last_samples, fatal_streak, last_pin, source_ok_after = None, 0, 0.0, 0.0
    if args.switch or pin:
        switch("start")
        last_pin = time.time()
    while True:
        started = time.time()
        try:
            last_samples, fatal = cycle(cfg, source, dev, face.fn, last_samples,
                                        ask_source=started >= source_ok_after)
            if pin and time.time() - last_pin >= pin:
                switch("pin")
                last_pin = time.time()
        except Exception:  # noqa: BLE001 - a daemon that dies leaves a live-looking number up
            log("cycle crashed; continuing:\n" + traceback.format_exc().rstrip())
            fatal = False
        if args.once:
            return 0
        # The panel is re-rendered EVERY period so a reading keeps ageing into
        # the stale face; only the source call is held back after a fatal error.
        if fatal:
            fatal_streak += 1
            hold = min(FATAL_BACKOFF_MAX, max(FATAL_BACKOFF_MIN, period) * 2 ** (fatal_streak - 1))
            source_ok_after = time.time() + hold
            log(f"credentials or config look wrong ({fatal_streak} in a row) - "
                f"not asking the source again for {hold}s")
        elif started >= source_ok_after:
            fatal_streak = 0
        # Deadline, not "sleep after the work": the period is the period, not
        # the period plus however long the network took this time.
        time.sleep(max(0.0, period - (time.time() - started)))


if __name__ == "__main__":
    sys.exit(main())
