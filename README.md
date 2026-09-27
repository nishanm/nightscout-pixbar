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
`$NIGHTSCOUT_PIXBAR_CONFIG`.

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

- **Nothing can bring the app on screen.** `switchDiyApp` / `switchApp` do not
  exist — verified on firmware 1.0.8 *and* 1.1.3, with the app present. The
  vendor's docs say a custom app renders only while it is displayed, so the
  face has to be selected with the knob.
- **A restart clears custom apps.** Measured. `daemon.py` re-creates its app
  every cycle for this reason, but a device that reboots unattended shows
  anything but glucose until something re-selects the app.
- **No alarms.** The speaker is not reachable from the push API.
- **Needs a host.** Nothing runs on the device.

Together these mean this is an *integration*, not a replacement firmware. A
native app built with Ulanzi's Flythings SDK would fix all four — the demo
project exposes the panel, the knob, the buttons and the speaker, and their
repo already contains a merged third-party native app. Whether it can do TLS
(and so reach Dexcom directly) is the open question.

## Not a medical device

Display only, best-effort, on a LAN with no delivery guarantees. Do not make
treatment decisions from this panel. Use the CGM app and its alarms.
