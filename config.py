"""Configuration and credential loading.

Credentials never live in this repo. Resolution order:

1. `$NIGHTSCOUT_PIXBAR_CONFIG` - path to a JSON config.
2. `pixbar-config.json` beside these scripts (gitignored).
3. The TC001 clocks' own standard config, which already holds working Dexcom
   credentials: Desktop/Claude Dev/clock-standard-config.json. Reusing it means
   there is exactly one copy of the password on this machine instead of two.
   (the clock stack's own notes - that file lives outside every repo
   deliberately, because it holds the WiFi PSK and Dexcom login.)

Nothing here ever prints a credential. `describe()` returns booleans and lengths.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, "pixbar-config.json")
CLOCK_STANDARD = os.path.join(os.path.dirname(HERE), "clock-standard-config.json")

DEFAULTS = {
    "host": "192.0.2.68",
    "app": "nightscout",
    "face": "hero-delta",
    "poll_seconds": 60,        # cheap; the source itself only moves every 5 min
    "source": "dexcom",
    "units": "mgdl",
}


def _from_clock_config(path):
    """Translate the TC001 config into ours. Only the keys we need."""
    with open(path, encoding="utf-8") as fh:
        clock = json.load(fh)
    return {
        "source": clock.get("data_source", "dexcom"),
        "units": clock.get("units", "mgdl"),
        "dexcom": {
            "username": clock.get("dexcom_username"),
            "password": clock.get("dexcom_password"),
            "server": clock.get("dexcom_server", "us"),
        },
        "nightscout": {
            "url": clock.get("nightscout_url", ""),
            "token": clock.get("nightscout_token"),
        },
    }


def load():
    cfg = dict(DEFAULTS)
    explicit = os.environ.get("NIGHTSCOUT_PIXBAR_CONFIG")
    for path, reader in ((explicit, json.load), (LOCAL, json.load), (CLOCK_STANDARD, None)):
        if not path or not os.path.exists(path):
            continue
        if reader is None:
            cfg.update(_from_clock_config(path))
            cfg["_credentials_from"] = os.path.basename(path)
        else:
            with open(path, encoding="utf-8") as fh:
                cfg.update(reader(fh))
            cfg["_credentials_from"] = os.path.basename(path)
        break
    else:
        cfg["_credentials_from"] = None
    return cfg


def describe(cfg):
    """A loggable summary with no secrets in it."""
    dex = cfg.get("dexcom", {})
    ns = cfg.get("nightscout", {})
    return (f"source={cfg.get('source')} units={cfg.get('units')} "
            f"host={cfg.get('host')} app={cfg.get('app')} face={cfg.get('face')} "
            f"creds_from={cfg.get('_credentials_from')} "
            f"dexcom_user_set={bool(dex.get('username'))} "
            f"dexcom_pass_set={bool(dex.get('password'))} server={dex.get('server')} "
            f"ns_url_set={bool(ns.get('url'))}")
