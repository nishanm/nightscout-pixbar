"""Live review tour: put every face, then the states that matter, then three
brightness levels, on the real panel with a dwell long enough to judge them.

Brightness is changed the safe way - GET the whole config, edit one key, POST it
back - because this device's setConfig, like the TC001's /api/save, stores what
it is handed rather than merging (see the nightscout-clock notes). The level
in use when the tour starts is restored at the end, whatever happens.
"""

import json
import sys
import time
import urllib.request

import faces as F
import push
import render as R

HOST = push.DEFAULT_HOST
APP = push.DEFAULT_APP
DWELL = 15


def get(path):
    with urllib.request.urlopen(f"http://{HOST}{path}", timeout=6) as r:
        return json.loads(r.read().decode())


def set_config(cfg):
    req = urllib.request.Request(
        f"http://{HOST}/setConfig",
        data=json.dumps(cfg).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=6) as r:
        return r.read().decode().strip()


def show(label, panel, dwell=DWELL):
    ms, size, body = push.send_panel(HOST, APP, panel, duration=dwell + 30)
    print(f"[{time.strftime('%H:%M:%S')}] {label:<34} {size:>4} B  {ms:>4.0f} ms  {body.strip()}",
          flush=True)
    time.sleep(dwell)


def main():
    in_range = dict(F.STATES)["in-range"]
    original = get("/getConfig")
    started_level = original["brightness"]["level"]
    print(f"brightness at start: {original['brightness']}", flush=True)

    try:
        print("--- part 1: the five faces, in range", flush=True)
        for slug, name, fn, _ in F.FACES:
            state = dict(F.STATES)["stale" if slug == "no-data" else "in-range"]
            show(f"face: {name}", fn(state))

        print("--- part 2: the states that must never be missed", flush=True)
        for state_name in ("urgent-low", "urgent-high", "stale"):
            show(f"state: {state_name}", F.face_hero_delta(dict(F.STATES)[state_name]))

        print("--- part 3: brightness, on the urgent-low face", flush=True)
        urgent = F.face_hero_delta(dict(F.STATES)["urgent-low"])
        push.send_panel(HOST, APP, urgent, duration=300)
        for level in ("high", "mid", "low"):
            cfg = get("/getConfig")
            cfg["brightness"]["level"] = level
            body = set_config(cfg)
            now = get("/getConfig")["brightness"]["level"]
            print(f"[{time.strftime('%H:%M:%S')}] brightness -> {level:<5} (device says {now})"
                  f"  {body[:60]}", flush=True)
            time.sleep(DWELL)

        print("--- part 4: the stale face at the lowest brightness", flush=True)
        show("stale @ low", F.face_hero_delta(dict(F.STATES)["stale"]))
    finally:
        cfg = get("/getConfig")
        cfg["brightness"]["level"] = started_level
        set_config(cfg)
        restored = get("/getConfig")["brightness"]["level"]
        push.send_panel(HOST, APP, F.face_hero_delta(in_range), duration=600)
        print(f"restored brightness to {restored} (was {started_level}); "
              f"Overview/in-range left on screen", flush=True)
        if restored != started_level:
            print("WARNING: brightness did not restore", file=sys.stderr)


if __name__ == "__main__":
    main()
