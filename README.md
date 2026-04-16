# XIAO ESP32S3 Sense — Camera Bring-Up

A minimal, plug-and-play camera test for the **Seeed Studio XIAO ESP32S3
Sense**.  The board captures a 640×480 JPEG every 3 seconds and streams it
over USB.  A host-side script saves one frame to `image.jpg` so you can
confirm the camera works before doing anything else.

This is the *starting point* for an Edge Impulse computer-vision project —
once you can grab a picture, the rest (data collection, training,
on-device inference) is additive.

---

## Quick start

```bash
make setup       # checks your tools (one-time)
make all         # build + upload + grab image.jpg + open it
```

That's it.  If something doesn't work, see [Troubleshooting](#troubleshooting).

> **Windows users:** see [`WINDOWS.md`](WINDOWS.md).  The recommended path
> is WSL2 + `usbipd-win` (then everything below works as-is); a native
> PowerShell path is documented as well.

---

## What you need

**Hardware**

- Seeed Studio XIAO ESP32S3 **Sense** (with the OV2640/OV3660 camera
  daughter-board attached via the FFC ribbon).
- USB-C cable — must be a *data* cable, not charge-only.

**Host (macOS)**

- [Homebrew](https://brew.sh/)
- [PlatformIO](https://platformio.org/) — `brew install platformio`
- [esptool](https://github.com/espressif/esptool) — `pipx install esptool`
  (install [pipx](https://pipx.pypa.io/) first if needed: `brew install pipx`)
- Python 3 (already on macOS).  The host scripts (`tools/*.py`) use only the
  standard library — no virtualenv needed.
- *(For Edge Impulse upload only)* Node.js + EI CLI:
  `brew install node && npm install -g edge-impulse-cli`

---

## First-time hardware setup

Plug the board in via USB.  If this is a **brand-new** XIAO ESP32S3 whose
factory firmware is misbehaving, you may need to enter the bootloader
manually exactly once:

1. Unplug USB.
2. Hold the tiny **B** button on top of the board (next to the USB-C jack).
3. Plug USB back in *while holding* B.
4. Release B.
5. Run `make upload`.

After this first flash succeeds, you never need the B button again — the
Arduino-ESP32 firmware exposes a working USB-Serial-JTAG that esptool can
auto-reset.

---

## Targets

| Command | What it does |
|---|---|
| `make all` | build + upload + grab + open the image |
| `make build` | compile only |
| `make upload` | flash the chip via USB |
| `make grab` | capture one `image.jpg` from the running firmware |
| `make show` | open `image.jpg` in Preview |
| `make monitor` | live serial output (Ctrl+C to quit) |
| `make reset` | recover the chip if it's stuck in the bootloader |
| `make capture CLASS=foo N=50` | burst-capture 50 frames into `data/foo/` |
| `make ei-upload CLASS=foo` | push `data/foo/` to your Edge Impulse project |
| `make clean` | remove `.pio/` and `image.jpg` |
| `make help` | list all targets |

---

## What's in this repo

```
.
├── platformio.ini   PlatformIO config (board, PSRAM, partition, USB-CDC)
├── src/
│   └── main.cpp     Arduino sketch: init OV2640, emit base64 JPEG over USB
├── tools/
│   ├── grab.py      Host-side: read one framed JPEG, save image.jpg
│   └── capture.py   Host-side: burst capture into data/<class>/NNN.jpg
├── Makefile         Convenience targets (make all, make grab, …)
├── README.md        This file
└── .gitignore       Keeps .pio/, data/, image.jpg out of git
```

---

## How it works (one paragraph each)

**Camera init.**  `src/main.cpp` configures the OV2640/OV3660 over the
parallel-DVP interface using the verified XIAO Sense pin map (XCLK=10,
PCLK=13, VSYNC=38, HREF=47, D0–D7=15/17/18/16/14/12/11/48, SDA/SCL=40/39).
Frames land in PSRAM thanks to `cfg.fb_location = CAMERA_FB_IN_PSRAM`.

**Transport.**  Once a JPEG is in the framebuffer, the sketch base64-encodes
it (in PSRAM via `mbedtls_base64_encode`) and prints it between
`JPEG_BEGIN len=… w=… h=…` and `JPEG_END` markers, 76 chars per line.  The
ESP32-S3 talks to the host via its native USB-Serial-JTAG, so there is no
external USB-to-UART chip and no real "baud rate" — bytes move at USB
full-speed (12 Mbps).

**Capture.**  `tools/grab.py` runs `cat /dev/cu.usbmodem*` in a subprocess
and parses its output line-by-line.  Why `cat` and not `pyserial`?  See
[Why `cat` instead of `pyserial`](#why-cat-instead-of-pyserial) below.

---

## Edge Impulse workflow

Once `make all` shows you a picture, you're ready for the full
data → train → deploy loop.

**1. Collect a dataset (board pointed at the subject).**

```bash
make capture CLASS=hotdog N=50          # 50 frames -> data/hotdog/0000.jpg ...
make capture CLASS=not_hotdog N=50
```

Re-running `make capture CLASS=hotdog` appends new frames without
overwriting old ones (next free 4-digit index).  Use `DELAY=2` to add a
2-second pause between captures so you can rearrange things in frame.

**2. Push the data to your Edge Impulse project.**

```bash
make ei-upload CLASS=hotdog
make ei-upload CLASS=not_hotdog
```

The first run prompts you to log in (`edge-impulse-uploader` opens a
browser).  After that it's cached.  Files are uploaded with the class as
their label and `--category split` to auto-divide into train/test.

**3. Train in the EI Studio.**

In your project at <https://studio.edgeimpulse.com/>:
*Impulse design* → image input → preprocessing (resize) → transfer
learning (MobileNet) → *Train*.  Runs in the cloud.

**4. Deploy back to the board.**

In *Deployment*, choose **"Arduino library"** → *Build* → download the
`.zip`.  In this repo:

```bash
mkdir -p lib
unzip -d lib/ ei-yourproject-arduino-1.0.0.zip
# replace src/main.cpp with the example sketch shipped inside the lib
make upload
```

The sketch from EI calls the camera the same way `src/main.cpp` does,
then feeds each frame into the model.  Output goes over USB-CDC, so
`make monitor` shows live predictions.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `no serial port found at /dev/cu.usbmodem*` | Board unplugged, charge-only cable, or USB hub problem | Plug into the laptop directly with a known-good data cable |
| `make upload` says `Failed to connect to ESP32-S3: No serial data received` | Chip is running app firmware that doesn't release USB-CDC for esptool | Hold the **B** button, replug USB, release B, then `make upload` (this is the brand-new-board scenario) |
| `make grab` times out with no output | Chip is stuck in the bootloader / stub flasher | `make reset` then `make grab` again |
| `make grab` saves a tiny corrupt `image.jpg` | A frame was already in flight when `cat` attached | Just rerun `make grab` — the next full frame will be clean |
| Serial monitor shows `STUCK:no-camera` | `esp_camera_init` failed (missing/loose ribbon, wrong board variant) | Power-cycle, check the OV2640 daughter-board ribbon is fully seated, confirm board is the *Sense* variant |
| Serial monitor shows `BOOT psram=no` | Octal PSRAM didn't initialise | Verify your board *is* the N8R8 module; check `board_build.psram_type = opi` is still in `platformio.ini` |
| `ERR:alloc need=…` in serial output | PSRAM was full (e.g. another large allocation leaked) | Reduce `fb_count` to 1 in `main.cpp` and rebuild |
| `make ei-upload` opens a browser then hangs | First-time login | Complete the login in the browser; the CLI caches the token |

---

## Why `cat` instead of `pyserial`

On macOS, opening `/dev/cu.usbmodem*` with `pyserial.Serial()` toggles the
DTR/RTS modem-control lines as a side effect.  The ESP32-S3's native
USB-Serial-JTAG peripheral interprets those toggles as the GPIO0 strap pin
being pulled low at reset, which reboots the chip into the ROM bootloader
— no serial output ever appears.  `cat` does *not* toggle modem lines on
`cu.*` devices, so the host scripts read the port via a `cat` subprocess.
`pio device monitor` is configured the same way (`--rts 0 --dtr 0`).

The other related gotcha is the **upload-time reset**: PlatformIO's default
`--after hard_reset` uses RTS, which can re-strap GPIO0 low and bounce the
chip back into the bootloader after flashing.  The `make reset` target
uses `esptool --after watchdog-reset`, which uses the chip's own watchdog
timer to reset and bypasses the strap emulation entirely.  In practice the
plain hard-reset works on this board, so `make upload` doesn't chain
`make reset` automatically — but if you ever see "boots but won't talk",
`make reset` is the escape hatch.

---

## What's *not* in this starter (intentionally)

These would be useful, but they distract from the EI workflow on day one:

- **microSD storage** — XIAO Sense has a slot.  Useful for untethered
  field collection, not needed for tethered batches.
- **WiFi `CameraWebServer`** — the canonical browser-stream demo.  Cool,
  but a separate project rather than part of the EI loop.
- **PDM microphone** — XIAO Sense has one, EI does audio classification.
  Different sensor, different workflow.

Add these as separate examples once the basics click.
