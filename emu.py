"""Live 52x16 face emulator for the TC002.

    python emu.py            then open http://localhost:8431/

Why a server and not a static page: the faces live in faces.py, and a second
copy in JavaScript would drift from the one that actually drives the device
(the nsc-emulator learned this the hard way on 32x8). So Python renders every
frame, the browser only displays it, and the SAME bytes can be pushed to the
real panel with one click - what you see and what the LEDs show cannot diverge.

faces.py and render.py are reloaded whenever their mtime changes, so editing a
face and refreshing the browser is the whole iteration loop.
"""

import importlib
import json
import os
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config as C
import faces as F
import model as M
import render as R
from device import Device

PORT = 8431
_mtimes = {}
_cfg = C.load()
DEV = Device(_cfg["host"], _cfg["app"])


def reload_if_changed():
    """Pick up edits to the face code without restarting the server."""
    changed = False
    for mod in (M, R, F):
        path = mod.__file__
        stamp = os.path.getmtime(path)
        if _mtimes.get(path) != stamp:
            _mtimes[path] = stamp
            changed = True
    if changed:
        importlib.reload(M)
        importlib.reload(R)
        importlib.reload(F)
    return changed


def reading_from(q):
    """Build a Reading from query params, falling back to the named state. An
    empty delta means "unknown" - the state the faces draw as `?`."""
    states = dict(F.demo_states())
    base = states.get(q.get("state", ["in-range"])[0], states["in-range"])
    sgv = _clamp(q.get("sgv", [base.sgv])[0], 1, 999)
    delta = q.get("delta", [base.delta])[0]
    return F.Reading(
        sgv=sgv,
        trend=q.get("trend", [base.trend])[0],
        delta=None if delta in (None, "", "?") else _clamp(delta, -999, 999),
        minutes_ago=_clamp(q.get("mins", [base.minutes_ago])[0], 0, 9999),
        time=q.get("time", [base.time])[0],
        # keep the demo timeline, retarget its newest point at the slider value
        history=(base.history[:-1] + [(base.history[-1][0], sgv)]) if base.history else [],
        now=base.now,
    )


def panel_for(q):
    face = F.face(q.get("face", [F.SLUGS[0]])[0]) or F.FACES[0]
    panel = face.fn(reading_from(q))
    bri = _clamp(q.get("bri", [255])[0], 0, 255)
    return panel if bri >= 255 else panel.dimmed(bri)


def _clamp(value, lo, hi):
    """Query params are ints from a text box; keep them inside what the
    renderer can sensibly do (a scale of 10000 is a gigabyte of PNG)."""
    return max(lo, min(hi, int(value)))


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>TC002 face emulator</title><style>
:root { color-scheme: dark; }
body { background:#0b0b0c; color:#e8e8e8; font:14px/1.5 system-ui,sans-serif; margin:0; padding:24px 28px; }
h1 { font-size:18px; margin:0 0 2px; } .sub { color:#8a8a8a; margin:0 0 18px; }
.row { display:flex; gap:28px; align-items:flex-start; flex-wrap:wrap; }
.panel { background:#000; padding:10px; border-radius:8px; }
.controls { display:grid; grid-template-columns:auto 1fr auto; gap:8px 12px; align-items:center;
  min-width:330px; background:#151517; padding:16px 18px; border-radius:10px; }
label { color:#9a9a9a; font-size:12px; }
input[type=range] { width:100%; } select, input[type=text] { background:#0d0d0e; color:#e8e8e8;
  border:1px solid #2a2a2e; border-radius:5px; padding:4px 6px; width:100%; }
.val { font:12px ui-monospace,monospace; color:#6ee7b7; min-width:52px; text-align:right; }
button { background:#1f6feb; color:#fff; border:0; border-radius:6px; padding:8px 14px;
  font-size:13px; cursor:pointer; } button.ghost { background:#26262b; }
button:disabled { opacity:.5; cursor:default; }
.bar { display:flex; gap:8px; align-items:center; margin-top:14px; }
.status { font:12px ui-monospace,monospace; color:#8a8a8a; }
h2 { font-size:13px; color:#9a9a9a; font-weight:600; margin:26px 0 8px; letter-spacing:.02em; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(430px,1fr)); gap:14px; }
.cell { background:#111; border-radius:8px; padding:8px 10px 10px; }
.cap { font:11px ui-monospace,monospace; color:#7a7a7a; margin-bottom:5px; }
.cell img, .panel img { display:block; width:100%; height:auto; image-rendering:pixelated; }
.err { color:#ff7b72; font:12px ui-monospace,monospace; white-space:pre-wrap; }
</style></head><body>
<h1>TC002 face emulator - 52&times;16</h1>
<p class="sub">Rendered by <code>faces.py</code>, the same code that builds the frames sent to the
device. Edit a face and the next render picks it up - no restart.</p>

<div class="row">
  <div class="panel"><img id="hero" alt="face preview"></div>
  <div class="controls">
    <label>Face</label><select id="face"></select><span></span>
    <label>State</label><select id="state"></select><span></span>
    <label>Value</label><input type="range" id="sgv" min="39" max="400" value="118"><span class="val" id="sgvv">118</span>
    <label>Trend</label><select id="trend"></select><span></span>
    <label>Delta</label><input type="range" id="delta" min="-30" max="30" value="2"><span class="val" id="deltav">+2</span>
    <label>Age</label><input type="range" id="mins" min="0" max="45" value="3"><span class="val" id="minsv">3m</span>
    <label>Time</label><input type="text" id="time" value="14:32"><span></span>
    <label>Bright</label><input type="range" id="bri" min="4" max="255" value="255"><span class="val" id="briv">255</span>
  </div>
</div>
<div class="bar">
  <button id="pushbtn">Push to device</button>
  <button class="ghost" id="followbtn">Follow: off</button>
  <span class="status" id="status"></span>
</div>

<h2>EVERY FACE, CURRENT CONTROLS</h2>
<div class="grid" id="allfaces"></div>
<h2>CURRENT FACE, EVERY STATE</h2>
<div class="grid" id="allstates"></div>
<p class="err" id="err"></p>

<script>
let META = null, follow = false;
const $ = id => document.getElementById(id);
const ctl = () => ({
  face: $("face").value, state: $("state").value, sgv: $("sgv").value, trend: $("trend").value,
  delta: $("delta").value, mins: $("mins").value, time: $("time").value, bri: $("bri").value,
});
const qs = o => new URLSearchParams(o).toString();

function paint() {
  const c = ctl();
  $("sgvv").textContent = c.sgv;
  $("deltav").textContent = (c.delta > 0 ? "+" : "") + c.delta;
  $("minsv").textContent = c.mins + "m";
  $("briv").textContent = c.bri;
  const stamp = Date.now();
  $("hero").src = "/png?" + qs({ ...c, scale: 18, t: stamp });
  $("allfaces").innerHTML = META.faces.map(f =>
    `<div class="cell"><div class="cap">${f.name} - ${f.about}</div>
     <img src="/png?${qs({ ...c, face: f.slug, scale: 9, t: stamp })}"></div>`).join("");
  $("allstates").innerHTML = META.states.map(s =>
    `<div class="cell"><div class="cap">${s}</div>
     <img src="/png?${qs({ ...c, state: s, sgv: "", delta: "", mins: "", time: "", scale: 9, t: stamp })}"></div>`).join("");
}

function fill(sel, items, value) {
  $(sel).innerHTML = items.map(i =>
    `<option value="${i.v}"${i.v === value ? " selected" : ""}>${i.t}</option>`).join("");
}

fetch("/meta").then(r => r.json()).then(m => {
  META = m;
  fill("face", m.faces.map(f => ({ v: f.slug, t: f.name })), m.faces[0].slug);
  fill("state", m.states.map(s => ({ v: s, t: s })), "in-range");
  fill("trend", m.trends.map(t => ({ v: t, t })), "FLAT");
  for (const id of ["face", "state", "sgv", "trend", "delta", "mins", "time", "bri"])
    $(id).addEventListener("input", () => { if (id === "state") syncState(); else paint(); });
  paint();
});

function syncState() {
  fetch("/state?name=" + encodeURIComponent($("state").value)).then(r => r.json()).then(s => {
    $("sgv").value = s.sgv; $("delta").value = s.delta; $("mins").value = s.minutes_ago;
    $("time").value = s.time; $("trend").value = s.trend; paint();
  });
}

$("pushbtn").onclick = () => {
  $("status").textContent = "pushing...";
  fetch("/push?" + qs(ctl()), { method: "POST" }).then(r => r.json()).then(r => {
    $("status").textContent = r.ok ? `pushed ${r.bytes} B in ${r.ms} ms to ${r.host}` : "FAILED: " + r.error;
  });
};
$("followbtn").onclick = () => {
  follow = !follow;
  $("followbtn").textContent = "Follow: " + (follow ? "on" : "off");
};
setInterval(() => { if (follow && META) paint(); }, 1000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        q = {k: v for k, v in q.items() if v and v[0] != ""}
        try:
            reload_if_changed()
            if url.path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
            elif url.path == "/meta":
                meta = {
                    "faces": [{"slug": f.slug, "name": f.name, "about": f.about} for f in F.FACES],
                    "states": F.STATE_NAMES,
                    "trends": list(M.TRENDS),
                    "host": DEV.host,
                }
                self._send(200, "application/json", json.dumps(meta).encode())
            elif url.path == "/state":
                r = F.state(q.get("name", ["in-range"])[0])
                self._send(200, "application/json", json.dumps({
                    "sgv": r.sgv, "trend": r.trend, "delta": r.delta,
                    "minutes_ago": r.minutes_ago, "time": r.time}).encode())
            elif url.path == "/png":
                scale = _clamp(q.get("scale", [14])[0], 1, 40)
                self._send(200, "image/png", R.png_leds(panel_for(q), scale=scale))
            elif url.path == "/raw.png":
                self._send(200, "image/png", R.png_raw(panel_for(q)))
            else:
                self._send(404, "text/plain", b"no")
        except Exception:
            self._send(500, "text/plain; charset=utf-8", traceback.format_exc().encode())

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v for k, v in urllib.parse.parse_qs(url.query).items() if v and v[0] != ""}
        try:
            reload_if_changed()
            if url.path != "/push":
                return self._send(404, "text/plain", b"no")
            ms, size, reply = DEV.send_panel(panel_for(q))
            self._send(200, "application/json", json.dumps({
                "ok": True, "ms": round(ms), "bytes": size, "host": DEV.host,
                "device": reply}).encode())
        except Exception as exc:
            self._send(200, "application/json", json.dumps({"ok": False, "error": str(exc)}).encode())


if __name__ == "__main__":
    reload_if_changed()
    print(f"TC002 face emulator on http://localhost:{PORT}/  (device {DEV})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
