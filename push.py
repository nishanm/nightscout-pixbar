"""Push a rendered 52x16 frame to a TC002 over the official custom-app API.

    python push.py --face overview --state in-range
    python push.py --delete

Measured on our unit (appVer 1.0.8, mcuVer V1.0.17) on 2026-09-25: a full
52x16 base64 PNG round-trips in a median 24 ms, i.e. ~41 fps sustained, so the
whole panel can be redrawn from a host instead of being described with the
vendor's text/draw primitives.

Known constraint on 1.0.8: /api/switchDiyApp and /switchApp do not exist (both
301 to the settings UI), so the app has to be selected on the device. Content
only renders while that custom app is the one on screen.
"""

import argparse
import json
import time
import urllib.request

import faces as F
import render as R

DEFAULT_HOST = "192.0.2.68"  # placeholder (RFC 5737); set PIXBAR_HOST or --host
DEFAULT_APP = "nightscout"


def post(host, app, payload, timeout=6):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://{host}/api/custom?name={app}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
    return (time.perf_counter() - started) * 1000, len(data), body


def send_panel(host, app, panel, duration=60):
    return post(
        host,
        app,
        {"duration": duration, "image": [{"data": R.data_uri(R.png_raw(panel)), "x": 0, "y": 0}]},
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--app", default=DEFAULT_APP)
    ap.add_argument("--face", default="overview", choices=[s for s, _, _, _ in F.FACES])
    ap.add_argument("--state", default="in-range", choices=[s for s, _ in F.STATES])
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--delete", action="store_true", help="remove the custom app and exit")
    args = ap.parse_args()

    if args.delete:
        ms, size, body = post(args.host, args.app, {})
        print(f"deleted {args.app}: {body.strip()} ({ms:.0f} ms)")
        return

    fn = dict((slug, f) for slug, _, f, _ in F.FACES)[args.face]
    reading = dict(F.STATES)[args.state]
    ms, size, body = send_panel(args.host, args.app, fn(reading), args.duration)
    print(f"{args.face}/{args.state} -> {args.host}/{args.app}: {body.strip()} "
          f"({size} B, {ms:.0f} ms)")


if __name__ == "__main__":
    main()
