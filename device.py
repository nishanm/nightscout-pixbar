"""The TC002 as seen from the host: one HTTP client for everything the panel
understands, so the protocol is written down once.

Facts this class encodes, each of which cost a day when it was scattered:

* Navigation is **POST**. `/api/switchDiyApp?name=<app>` (firmware 1.1.0+) puts
  a custom app on screen; the GET form 404s, which is how it was recorded as
  "impossible" for a day.
* `POST /api/custom?name=<app>` creates the app on first use and updates it after;
  an empty object deletes it. A device restart clears the list.
* The API is unauthenticated and forgeable. Nothing here calls the destructive
  endpoints (`update`, `resetConfig`, `setLedRegister`, `setWifiConfig`).
* `setConfig` stores what it is handed rather than merging, so a settings change
  is GET, edit one key, POST the whole object (`set_config`).

Replies are parsed, not sniffed: the device answers `{"code":200,...}` on
success, and callers get that dict.
"""

import http.client
import json
import time
import urllib.parse
import urllib.request

import render as R

TIMEOUT = 5
# The device answers in a few hundred bytes. The API is unauthenticated on a
# LAN, so a reply is read with a ceiling rather than trusted to end.
MAX_REPLY = 64 * 1024


class DeviceError(Exception):
    pass


class Device:
    def __init__(self, host, app, timeout=TIMEOUT):
        self.host = host
        self.app = app
        self.timeout = timeout

    def __repr__(self):
        return f"Device({self.host}/{self.app})"

    # ------------------------------------------------------------- transport
    def _call(self, path, payload=None, method=None):
        """One request. Returns (milliseconds, bytes sent, parsed reply). A reply
        that is not JSON comes back as {"raw": text} so a caller never has to
        substring-match a body."""
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://{self.host}{path}",
            data=data,
            method=method or ("POST" if data is not None else "GET"),
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read(MAX_REPLY + 1).decode(errors="replace")
                if len(text) > MAX_REPLY:
                    raise DeviceError(f"{req.get_method()} {path}: reply larger than {MAX_REPLY} bytes")
        # URLError/timeout/refused are OSErrors; a reply cut off mid-body by the
        # device's small HTTP server is an HTTPException, which is NOT one.
        except (OSError, http.client.HTTPException) as exc:
            raise DeviceError(f"{req.get_method()} {path}: {exc}") from exc
        ms = (time.perf_counter() - started) * 1000
        try:
            reply = json.loads(text) if text.strip() else {}
        except ValueError:
            reply = {"raw": text.strip()}
        return ms, len(data or b""), reply

    def get(self, path):
        return self._call(path)[2]

    def post(self, path, payload):
        return self._call(path, payload)[2]

    # ------------------------------------------------------------ custom app
    def send_panel(self, panel, duration=60):
        """Push a rendered frame as the app's content. Creates the app if it is
        gone. Returns (ms, bytes, reply); reply["code"] == 200 means accepted."""
        payload = {"duration": duration,
                   "image": [{"data": R.data_uri(R.png_raw(panel)), "x": 0, "y": 0}]}
        return self._call(f"/api/custom?name={urllib.parse.quote(self.app)}", payload)

    def delete_app(self):
        return self.post(f"/api/custom?name={urllib.parse.quote(self.app)}", {})

    def app_exists(self):
        """False when the app is missing OR the device is unreachable - either
        way the caller should push and re-select rather than assume."""
        try:
            return self.app in (self.get("/api/customList").get("apps") or [])
        except DeviceError:
            return False

    def switch_to(self):
        """Ask the device to show our app. Applied on its next UI tick."""
        return self.post(f"/api/switchDiyApp?name={urllib.parse.quote(self.app)}", {})

    # ---------------------------------------------------------------- config
    def get_config(self):
        return self.get("/getConfig")

    def set_config(self, cfg):
        """Whole object in, whole object stored. Read with get_config first."""
        return self.post("/setConfig", cfg)

    def set_brightness(self, level):
        """The safe way to change one key: GET, edit, POST, read back."""
        cfg = self.get_config()
        cfg["brightness"]["level"] = level
        self.set_config(cfg)
        return self.get_config()["brightness"]["level"]
