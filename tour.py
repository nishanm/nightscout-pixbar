"""Live review tour: put every face, then the states that matter, then three
brightness levels, on the real panel with a dwell long enough to judge them.

Brightness is changed the safe way (Device.set_brightness: GET the whole
config, edit one key, POST it back) because this device's setConfig, like the
TC001's /api/save, stores what it is handed rather than merging. The level in
use when the tour starts is restored at the end, whatever happens.
"""

import sys
import time

import config as C
import faces as F
from device import Device, DeviceError

DWELL = 15


def stamp(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def show(dev, label, panel, dwell=DWELL):
    ms, size, reply = dev.send_panel(panel, duration=dwell + 30)
    stamp(f"{label:<34} {size:>4} B  {ms:>4.0f} ms  {reply}")
    time.sleep(dwell)


def main():
    cfg = C.load()
    dev = Device(cfg["host"], cfg["app"])
    hero_delta = F.face("hero-delta").fn
    started_level = dev.get_config()["brightness"]["level"]
    stamp(f"brightness at start: {started_level}")

    try:
        print("--- part 1: every face, in the state that shows it off", flush=True)
        for face in F.FACES:
            show(dev, f"face: {face.name}", face.fn(F.state(face.demo_state)))

        print("--- part 2: the states that must never be missed", flush=True)
        for name in ("urgent-low", "urgent-high", "stale"):
            show(dev, f"state: {name}", hero_delta(F.state(name)))

        print("--- part 3: brightness, on the urgent-low face", flush=True)
        dev.send_panel(hero_delta(F.state("urgent-low")), duration=300)
        for level in ("high", "mid", "low"):
            stamp(f"brightness -> {level:<5} (device says {dev.set_brightness(level)})")
            time.sleep(DWELL)

        print("--- part 4: the stale face at the lowest brightness", flush=True)
        show(dev, "stale @ low", hero_delta(F.state("stale")))
    finally:
        # Guarded: if the device is what failed, the restore fails too, and that
        # must be reported beside the original error rather than replace it.
        try:
            restored = dev.set_brightness(started_level)
            dev.send_panel(hero_delta(F.state("in-range")), duration=600)
            stamp(f"restored brightness to {restored} (was {started_level}); hero-delta/in-range left on screen")
            if restored != started_level:
                print("WARNING: brightness did not restore", file=sys.stderr)
        except DeviceError as exc:
            print(f"WARNING: could not restore brightness {started_level!r}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
