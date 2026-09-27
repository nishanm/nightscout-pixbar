"""Glucose sources, ported from the ktomy firmware's BGSource* classes.

Deliberately a port and not a fresh design: the endpoints, the application IDs,
the two-step account -> session login, the 3-hour backfill window and the trend
vocabulary all match src/BGSourceDexcom.cpp and src/BGSourceNightscout.cpp, so a
reading shown here means the same thing as one shown on the TC001 clocks.

stdlib only (urllib + ssl), so this runs anywhere Python does.

Credentials are never held in this file. See config.py.
"""

import hashlib
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

# src/BGSourceDexcom.h:6-14
DEXCOM_APPLICATION_ID = "d89443d2-327c-4a6f-89e5-496bbb0317db"
DEXCOM_APPLICATION_ID_JAPAN = "d8665ade-9673-4e27-9ff6-92db4ce13d13"
DEXCOM_SERVERS = {
    "us": "https://share1.dexcom.com",
    "non_us": "https://shareous1.dexcom.com",
    "japan": "https://share.dexcom.jp",
}
ACCOUNT_PATH = "/ShareWebServices/Services/General/AuthenticatePublisherAccount"
SESSION_PATH = "/ShareWebServices/Services/General/LoginPublisherAccountById"
READINGS_PATH = "/ShareWebServices/Services/Publisher/ReadPublisherLatestGlucoseValues"

# src/BGSource.h:15 - how much history to ask for, and what the faces graph.
BACKFILL_SECONDS = 3 * 60 * 60

# src/BGSource.cpp:103-128. Values are the names our faces and the firmware share.
TRENDS = {
    "doubleup": "DOUBLE_UP",
    "singleup": "SINGLE_UP",
    "fortyfiveup": "FORTY_FIVE_UP",
    "flat": "FLAT",
    "fortyfivedown": "FORTY_FIVE_DOWN",
    "singledown": "SINGLE_DOWN",
    "doubledown": "DOUBLE_DOWN",
    "not_computable": "NONE",
    "rate_out_of_range": "NONE",
    "none": "NONE",
}
# Nightscout sends the same set with different spelling.
TRENDS.update({"doubleup": "DOUBLE_UP", "fortyfiveup": "FORTY_FIVE_UP", "nonecomputable": "NONE"})


class SourceError(Exception):
    """Anything that stops us getting a reading. Carries a short reason the face
    can show - a display that goes blank is worse than one that says why."""

    def __init__(self, message, reason="ERROR", fatal=False):
        super().__init__(message)
        self.reason = reason
        self.fatal = fatal  # credentials are wrong: retrying will not help


class Reading:
    __slots__ = ("epoch", "sgv", "trend")

    def __init__(self, epoch, sgv, trend):
        self.epoch = int(epoch)
        self.sgv = int(sgv)
        self.trend = trend

    def __repr__(self):
        return f"Reading({self.sgv}, {self.trend}, {int(time.time()) - self.epoch}s ago)"


def parse_trend(value):
    if value is None:
        return "NONE"
    if isinstance(value, (int, float)):  # Nightscout sometimes sends an index
        order = ["NONE", "DOUBLE_UP", "SINGLE_UP", "FORTY_FIVE_UP", "FLAT",
                 "FORTY_FIVE_DOWN", "SINGLE_DOWN", "DOUBLE_DOWN", "NONE", "NONE"]
        idx = int(value)
        return order[idx] if 0 <= idx < len(order) else "NONE"
    return TRENDS.get(str(value).strip().lower().replace(" ", ""), "NONE")


def _post_json(url, payload, timeout=15):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        # The firmware identifies itself; keep doing so rather than pretending
        # to be the Dexcom app.
        "User-Agent": "nightscout-pixbar",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return json.loads(r.read().decode() or "null")


class DexcomShare:
    """Two-step login (account id, then session id), exactly as the firmware does.
    A session that has expired comes back as a 500 mentioning 'Session'; that
    clears the session and retries once (src/BGSourceDexcom.cpp:198-203)."""

    def __init__(self, username, password, server="us"):
        if server not in DEXCOM_SERVERS:
            raise SourceError(f"unknown Dexcom server {server!r}", "CONFIG", fatal=True)
        self.base = DEXCOM_SERVERS[server]
        self.app_id = DEXCOM_APPLICATION_ID_JAPAN if server == "japan" else DEXCOM_APPLICATION_ID
        self._username = username
        self._password = password
        self.account_id = None
        self.session_id = None

    def _login(self):
        if not self.account_id:
            self.account_id = _post_json(self.base + ACCOUNT_PATH, {
                "accountName": self._username,
                "password": self._password,
                "applicationId": self.app_id,
            })
        if not self.session_id:
            self.session_id = _post_json(self.base + SESSION_PATH, {
                "accountId": self.account_id,
                "password": self._password,
                "applicationId": self.app_id,
            })

    def fetch(self, minutes=None, max_count=None, _retry=True):
        minutes = minutes or BACKFILL_SECONDS // 60
        max_count = max_count or (minutes // 5 + 2)  # +2 for safety, as the firmware does
        try:
            self._login()
            url = (f"{self.base}{READINGS_PATH}?sessionId={self.session_id}"
                   f"&minutes={minutes}&maxCount={max_count}")
            raw = _post_json(url, {})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            if "AccountPasswordInvalid" in detail or "SSO_AuthenticateAccountNotFound" in detail:
                raise SourceError("Dexcom rejected the credentials", "BAD LOGIN", fatal=True)
            if "Session" in detail and _retry:
                self.session_id = None
                return self.fetch(minutes, max_count, _retry=False)
            raise SourceError(f"Dexcom HTTP {exc.code}", "HTTP")
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
            raise SourceError(f"Dexcom unreachable: {exc}", "NO NET")

        if not isinstance(raw, list):
            raise SourceError("Dexcom response was not an array", "BAD DATA")
        readings = []
        for item in raw:
            # "ST" looks like /Date(1703182152000)/ - the firmware trims 5 off the
            # front and 4 off the back (BGSourceDexcom.cpp:159-163).
            match = re.search(r"(\d{10,13})", str(item.get("ST", "")))
            if not match:
                continue
            readings.append(Reading(int(match.group(1)) // 1000,
                                    item.get("Value", 0),
                                    parse_trend(item.get("Trend"))))
        readings.sort(key=lambda r: r.epoch)
        return readings


class Nightscout:
    """GET /api/v1/entries.json. Token optional; only needed if the site reads
    are protected (src/BGSourceNightscout.cpp).

    `api_secret` is the other way a protected site authenticates a read, and is
    what the homelab's own Nightscout needs: it runs AUTH_DEFAULT_ROLES=denied,
    so an unauthenticated entries read is a 401 and no subject token exists.
    Nightscout wants the SHA1 hex of API_SECRET in an `api-secret` header - the
    firmware never needed this because the clocks read Dexcom directly, so this
    is an addition to the port rather than part of it.
    """

    def __init__(self, base_url, token=None, api_secret=None):
        self.base = base_url.rstrip("/")
        self.token = token
        self.api_secret = api_secret

    def fetch(self, minutes=None, max_count=None):
        minutes = minutes or BACKFILL_SECONDS // 60
        count = max_count or (minutes // 5 + 2)
        url = f"{self.base}/api/v1/entries.json?count={count}"
        if self.token:
            url += "&token=" + urllib.parse.quote(self.token)
        try:
            headers = {"User-Agent": "nightscout-pixbar"}
            if self.api_secret:
                # Hashed here, never logged: the plain secret must not leave .env.
                headers["api-secret"] = hashlib.sha1(
                    self.api_secret.encode()).hexdigest()
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15,
                                        context=ssl.create_default_context()) as r:
                raw = json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            raise SourceError(f"Nightscout HTTP {exc.code}", "HTTP",
                              fatal=exc.code in (401, 403))
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
            raise SourceError(f"Nightscout unreachable: {exc}", "NO NET")

        readings = []
        for item in raw or []:
            if "sgv" not in item:
                continue
            epoch = int(item.get("date", 0)) // 1000 or int(item.get("mills", 0)) // 1000
            readings.append(Reading(epoch, item["sgv"], parse_trend(item.get("direction"))))
        readings.sort(key=lambda r: r.epoch)
        return readings


def build(config):
    kind = config.get("source", "dexcom").lower()
    if kind == "dexcom":
        creds = config.get("dexcom", {})
        return DexcomShare(creds.get("username"), creds.get("password"),
                           creds.get("server", "us"))
    if kind == "nightscout":
        creds = config.get("nightscout", {})
        return Nightscout(creds.get("url", ""), creds.get("token"),
                          creds.get("api_secret"))
    raise SourceError(f"unknown source {kind!r}", "CONFIG", fatal=True)


# src/BGDisplayFaceValueAndDiff.cpp:37-91. Not "latest minus previous": Dexcom
# Share returns the same reading twice about 11 s apart, so the previous element
# is often the current one's twin and the delta comes out zero. The firmware
# takes everything inside a 6.5 minute window and works from its min and max,
# which is immune to that.
DIFF_WINDOW_SECONDS = 6 * 60 + 30


def delta_for(readings):
    """Change since the previous reading, or None when it cannot be stated.

    None means genuinely unknown - render it as "?", never as 0. A zero delta
    on a falling glucose is worse than no delta at all."""
    if len(readings) < 2:
        return None
    last = readings[-1]
    window = [r for r in readings if last.epoch - r.epoch <= DIFF_WINDOW_SECONDS]
    if len(window) > 5:  # Libre-style dense data: just the last two
        window = window[-2:]
    if len(window) < 2:
        return None
    lo = min(r.sgv for r in window)
    hi = max(r.sgv for r in window)
    base = last.sgv
    if lo != base and hi != base:
        return None  # moved both ways inside the window; no honest single number
    delta = base - hi if lo == base else base - lo
    return None if abs(delta) > 99 else delta
