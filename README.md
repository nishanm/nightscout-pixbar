# nightscout-pixbar

Glucose on an **Ulanzi TC002 "Pixbar"** (52×16 pixel panel), rendered on a host
and pushed to the device over its official custom-app API.

This is **not** a port of [ktomy/nightscout-clock](https://github.com/ktomy/nightscout-clock).
That firmware runs on the TC001, which is an ESP32. The TC002 is a Sigmastar
SSD21x — two ARM Cortex-A7 cores running Linux, driving the panel through a
separate pixel MCU over SPI. There is no PlatformIO, no esptool, no serial
port and no `firmware.bin`: everything reaches the device over the network.
What *is* shared is the data layer, ported faithfully so a reading means the
same thing on both.

## State

Working: real Dexcom readings render and reach the panel. Not yet a product —
see **Known limits**.

## Quick start

```bash
python daemon.py --once          # one poll, render, push
python daemon.py --poll 60       # run continuously
python emu.py                    # face emulator at http://localhost:8431/
python audit.py                  # check every face in every state
python make_mockups.py           # PNG sheets + gallery into mockups/
```

Credentials are never stored here. `config.py` reads them from
`clock-standard-config.json` (the file the TC001 clocks already use, kept
outside every repo), or from `pixbar-config.json`, or from
`$NIGHTSCOUT_PIXBAR_CONFIG` — and then lets `PIXBAR_*` environment variables
override all of it, which is how the container is configured. See `.env.example`.

## Running it unattended

Run from a laptop and the panel goes stale the moment the terminal closes, which
on a glucose display reads as a calm number rather than as "no data". So the
daemon lives on the NAS instead, beside the rest of the homelab:

```bash
# on the deploy host, once. DEPLOY is wherever that host keeps its stacks.
DEPLOY=<deploy-dir>/pixbar
sudo git clone https://github.com/nishanm/nightscout-pixbar "$DEPLOY"
cd "$DEPLOY"
sudo cp .env.example .env && sudo chmod 600 .env   # then fill it in
sudo docker compose up -d        # sudo: .env is 600 root:root, like every stack's
sudo docker logs -f pixbar

# updating
sudo git -C "$DEPLOY" pull
sudo docker compose -f "$DEPLOY/compose.yaml" up -d --force-recreate
```

The bind mounts in `compose.yaml` are relative to the compose file, so the deploy
directory can be anywhere.

There is no image to build: the code is stdlib-only, so `python:3.12-alpine`
plus a read-only bind mount of the working copy is the whole deployment.

**Prefer `PIXBAR_SOURCE=nightscout` there.** The homelab's own Nightscout
already holds this CGM history, and the Dexcom Share account is already being
logged into by its bridge, by `insulin-api` and by three TC001 clocks — one more
consumer is account-lock risk for no freshness gained. A wrong credential is
also treated as fatal and backed off (5 → 30 min) rather than retried every
minute, for the same reason.

## Layout

| File | What |
|---|---|
| `render.py` | 52×16 panel, Spleen text engine, trend/graph primitives, PNG encoder. No dependencies. |
| `fonts.py` | Glyphs baked from Spleen BDFs by `make_fonts.py`. Generated — do not hand-edit. |
| `faces.py` | The faces, drawn native for 52×16. |
| `sources.py` | Dexcom Share and Nightscout, ported from `BGSource*`. |
| `daemon.py` | Poll → render → push, with app re-creation and honest failure faces. |
| `emu.py` | Browser emulator; renders through the same Python and can push to the device. |
| `audit.py` | Gate: clipped pixels, edge margins, empty frames, night-brightness legibility. |
| `push.py` | One frame to the device. |

## Design rules

Learned by putting the first attempt on real hardware and looking at it:

1. **Real letterforms.** Hand-rolled seven-segment digits read as a calculator.
   Ulanzi's own reference renderer bakes a pixel font with a 1 px inter-character
   gap for this reason.
2. **One hero element, filling the height.** 52×16 is big; four elements at 5 px
   each are illegible across a room.
3. **Measure, never assume a width.** `48` and `287` are different sizes, and
   assuming otherwise is what made the trend arrow collide with the value.
4. **Colour is state, not decoration.** The value's colour is the glucose state;
   everything else stays white or dim.
5. **Stale must never look live.** A frozen number still reads as a reading.

## Known limits

- **A restart clears custom apps.** Measured. `daemon.py` checks every cycle,
  re-creates its app when it is gone, and then calls
  `POST /api/switchDiyApp?name=<app>` to put it back on screen (firmware
  1.1.0+, in Ulanzi's own protocol doc; measured on 1.1.3). An earlier claim
  here that no such endpoint existed came from probing it with GET, which
  404s. Set `PIXBAR_PIN_SECONDS` to re-assert it on a timer if the panel must
  never be left on another app; off by default so the knob still works.
- **Custom apps are not in the device carousel** (Ulanzi issue #22), so a
  custom app stays up only until the knob moves or the carousel timer fires.
  Leave `carouselSpeed` at 0 on the device.
- **No alarms.** The speaker is not reachable from the push API.
- **Needs a host.** Nothing runs on the device. The `pixbar` container on the
  NAS is that host; it survives a laptop session and a reboot, but the device
  still needs something else to solve the two problems above.

Together these mean this is an *integration*, not a replacement firmware. A
native app built with Ulanzi's Flythings SDK would fix the rest — the demo
project exposes the panel, the knob, the buttons and the speaker, and their
repo already contains a merged third-party native app. Whether it can do TLS
(and so reach Dexcom directly) is the open question.

## Not a medical device

Display only, best-effort, on a LAN with no delivery guarantees. Do not make
treatment decisions from this panel. Use the CGM app and its alarms.
