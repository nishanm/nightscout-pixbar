"""Push one rendered frame to the TC002 from the command line.

    python push.py                          # default face, in range
    python push.py --face big-graph --state urgent-low
    python push.py --switch                 # ...and bring the app on screen
    python push.py --delete                 # remove the custom app

Host and app come from config.py (so PIXBAR_HOST works here too); the device
protocol lives in device.py. Measured 2026-09-25: a full 52x16 base64 PNG
round-trips in ~24 ms, so the whole panel is redrawn from the host rather than
described in the vendor's text/draw primitives.
"""

import argparse

import config as C
import faces as F
from device import Device


def main():
    cfg = C.load()
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=cfg["host"])
    ap.add_argument("--app", default=cfg["app"])
    ap.add_argument("--face", default=cfg["face"], choices=F.SLUGS)
    ap.add_argument("--state", default="in-range", choices=F.STATE_NAMES)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--switch", action="store_true", help="also select the app on the device")
    ap.add_argument("--delete", action="store_true", help="remove the custom app and exit")
    args = ap.parse_args()
    dev = Device(args.host, args.app)

    if args.delete:
        print(f"deleted {args.app}: {dev.delete_app()}")
        return

    panel = F.face(args.face).fn(F.state(args.state))
    ms, size, reply = dev.send_panel(panel, args.duration)
    print(f"{args.face}/{args.state} -> {dev}: {reply} ({size} B, {ms:.0f} ms)")
    if args.switch:
        print(f"switch: {dev.switch_to()}")


if __name__ == "__main__":
    main()
