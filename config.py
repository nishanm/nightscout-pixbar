"""Configuration and credential loading.

Credentials never live in this repo. Resolution order:

1. `$NIGHTSCOUT_PIXBAR_CONFIG` - path to a JSON config.
2. `pixbar-config.json` beside these scripts (gitignored).
3. The TC001 clocks' own standard config, which already holds working Dexcom
   credentials: `clock-standard-config.json`, one directory up. Reusing it means
   there is exactly one copy of the password on this machine instead of two.
   That file lives outside every repo deliberately, because it holds the WiFi
   PSK and the Dexcom login; the clock stack's own notes say so.
4. `PIXBAR_*` environment variables, applied LAST so they win over any file.

Step 4 is what lets this run as a container with no config file at all: every
other stack on the NAS is configured by an `env_file`, and a JSON secret bind-
mounted into a read-only container would have been a second pattern for no gain.
Env wins over file so a deployed container cannot be silently reconfigured by a
stale file that happens to be in its working copy.

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

# env var -> (config key path, coercion). Flat keys and nested credential keys.
ENV_MAP = {
    "PIXBAR_HOST": (("host",), str),
    "PIXBAR_APP": (("app",), str),
    "PIXBAR_FACE": (("face",), str),
    "PIXBAR_POLL_SECONDS": (("poll_seconds",), int),
    "PIXBAR_SOURCE": (("source",), str),
    "PIXBAR_UNITS": (("units",), str),
    "PIXBAR_DEXCOM_USERNAME": (("dexcom", "username"), str),
    "PIXBAR_DEXCOM_PASSWORD": (("dexcom", "password"), str),
    "PIXBAR_DEXCOM_SERVER": (("dexcom", "server"), str),
    "PIXBAR_NIGHTSCOUT_URL": (("nightscout", "url"), str),
    "PIXBAR_NIGHTSCOUT_TOKEN": (("nightscout", "token"), str),
    "PIXBAR_NIGHTSCOUT_API_SECRET": (("nightscout", "api_secret"), str),
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


def _apply_env(cfg, environ=None):
    """Overlay PIXBAR_* variables. An empty value is ignored, not applied: an
    env_file that carries `PIXBAR_DEXCOM_PASSWORD=` to mean "unset" must not
    blank out a password that a config file supplied."""
    environ = os.environ if environ is None else environ
    applied = []
    for name, (path, coerce) in ENV_MAP.items():
        raw = environ.get(name)
        if raw is None or raw.strip() == "":
            continue
        try:
            value = coerce(raw.strip())
        except (TypeError, ValueError):
            raise ValueError(f"{name} is not a valid {coerce.__name__}")
        target = cfg
        for key in path[:-1]:
            target = target.setdefault(key, {})
            if not isinstance(target, dict):
                raise ValueError(f"{name} cannot be applied: {key!r} is not a section")
        target[path[-1]] = value
        applied.append(name)
    return applied


def load(environ=None):
    cfg = dict(DEFAULTS)
    explicit = (os.environ if environ is None else environ).get("NIGHTSCOUT_PIXBAR_CONFIG")
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
    applied = _apply_env(cfg, environ)
    if applied:
        cfg["_credentials_from"] = "env" if not cfg.get("_credentials_from") \
            else f"{cfg['_credentials_from']}+env"
        cfg["_env_applied"] = sorted(applied)
    return cfg


def describe(cfg):
    """A loggable summary with no secrets in it."""
    dex = cfg.get("dexcom", {})
    ns = cfg.get("nightscout", {})
    return (f"source={cfg.get('source')} units={cfg.get('units')} "
            f"host={cfg.get('host')} app={cfg.get('app')} face={cfg.get('face')} "
            f"poll={cfg.get('poll_seconds')}s "
            f"creds_from={cfg.get('_credentials_from')} "
            f"dexcom_user_set={bool(dex.get('username'))} "
            f"dexcom_pass_set={bool(dex.get('password'))} server={dex.get('server')} "
            f"ns_url_set={bool(ns.get('url'))} "
            f"ns_token_set={bool(ns.get('token'))} "
            f"ns_api_secret_set={bool(ns.get('api_secret'))}")
