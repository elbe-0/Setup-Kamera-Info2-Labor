# Windows setup guide

The main `README.md` assumes macOS or Linux.  Two paths work on Windows:

1. **WSL2 with `usbipd-win`** *(strongly recommended)* — your code,
   scripts, and workflow are identical to the macOS instructions.
   One-time setup, then `make all` "just works" inside WSL.
2. **Native Windows (PowerShell + pyserial)** — no WSL, but the
   `cat`-based scripts in `tools/` don't work on Windows COM ports, so
   you'll run inline commands instead of `make grab` / `make capture`.
   See the [caveats](#caveats-for-native-windows) section before
   committing to this path.

If you're comfortable with the terminal, pick **path 1** — it's the
better-tested and less surprising route.

---

## Path 1 — WSL2 + usbipd-win (recommended)

WSL2 doesn't see USB devices by default.  Microsoft's `usbipd-win` bridges
them into the Linux side per session.

### One-time install (Administrator PowerShell)

```powershell
# Install (or update) WSL2 + Ubuntu.  Skip if you already have it.
wsl --install -d Ubuntu
wsl --update                           # usbipd needs WSL2 kernel >= 5.10.60.1

# Install usbipd-win.  Confirmed package id; current as of usbipd-win 4.x.
winget install --exact dorssel.usbipd-win
```

Reboot.  Open Ubuntu (your WSL distro) and install the same tools the main
README expects:

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv \
    pipx make build-essential nodejs npm
pipx install platformio
pipx install esptool
pipx ensurepath        # add ~/.local/bin to PATH; restart shell after
sudo npm install -g edge-impulse-cli
```

> **Heads-up on Windows Defender / SmartScreen:** the first time `pio` or
> `node` runs, Windows may prompt to allow them through the firewall.
> Click *Allow* — they need outbound network access to fetch toolchains
> and talk to Edge Impulse.

### Each session — attach the board to WSL

Plug the XIAO into USB.  In an **Administrator PowerShell window**
(usbipd commands all need admin):

```powershell
usbipd list                      # find the BUSID, e.g. "2-3"
usbipd bind   --busid 2-3        # one-time per BUSID; persists across reboots
usbipd attach --wsl --busid 2-3  # do this each time you replug
```

In WSL, confirm the device shows up:

```bash
ls /dev/ttyACM*                  # should print /dev/ttyACM0
```

If you see it, **everything in the main README now works**, with one
small change: WSL exposes the board as `/dev/ttyACM0` instead of
`/dev/cu.usbmodem*`.  Override the port detection like this:

```bash
export PORT=/dev/ttyACM0         # set once per shell session
make all
make capture CLASS=hotdog N=50
```

### Common WSL gotchas

- **"usbipd: device is not shared"** → you skipped `usbipd bind`.
- **No `/dev/ttyACM0` after replug** → `attach` is per-session; redo it.
- **`pio: command not found`** after `pipx install` → run `pipx ensurepath`
  and restart the shell (or open a fresh tab).
- **`open image.jpg`** doesn't exist in WSL.  Either copy the file out
  (`cp image.jpg /mnt/c/Users/<you>/Desktop/`) or launch the Windows
  image viewer with `explorer.exe image.jpg`.
- **Edge Impulse CLI install fails on `node-gyp`** → install the build
  prerequisites: `sudo apt install -y python3-distutils g++`.

---

## Path 2 — Native Windows (no WSL)

You skip WSL but lose `make`, `cat`, and our shell-based helpers.
Everything is doable, just with more typing.  **Read the [caveats
below](#caveats-for-native-windows) first** — there's a USB-Serial-JTAG
behavior that may not be solvable from native Windows.

### Install tools

Use [winget](https://learn.microsoft.com/en-us/windows/package-manager/winget/)
(built into Windows 10/11):

```powershell
winget install --exact Python.Python.3.12
winget install --exact OpenJS.NodeJS.LTS
```

PlatformIO does **not** ship as a winget package.  Install it (plus
esptool) via pip — open a fresh PowerShell window so PATH picks up
Python:

```powershell
python -m pip install --user platformio esptool
python -m pip install -r requirements.txt   # adds pyserial (used by capture_win.py)
npm install -g edge-impulse-cli
```

> If `npm install -g edge-impulse-cli` fails complaining about
> `node-gyp`: install Visual Studio 2022 Build Tools with the
> "Desktop development with C++" workload, then retry.

### Allow PowerShell to run scripts

Default Windows policy blocks unsigned `.ps1` files.  Run once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

This lets you run local scripts without breaking script-signing
requirements for downloaded files.

### Find your COM port

Plug the XIAO in.  In PowerShell:

```powershell
[System.IO.Ports.SerialPort]::GetPortNames()
# -> e.g. COM3, COM7
```

Or open *Device Manager → Ports (COM & LPT)* and look for "USB Serial
Device" with VID `303A` (Espressif) PID `1001`.

> **COM numbers can change** when you unplug and replug, especially
> across different USB ports.  If your scripts stop finding the board,
> rerun `GetPortNames()` and update `COM3` in the commands below.

If the device shows up under "Other devices" instead of "Ports", you
need a CDC driver.  On Windows 10 1809+ and Windows 11 the in-box
`Usbser.sys` should bind automatically.  On older Windows, get the
driver bundled with the
[ESP-IDF Tools Installer](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/get-started/windows-setup.html).

### Hardware bootloader entry (same as macOS)

Brand-new boards may need the B-button trick once:

1. Unplug USB.
2. Hold the **B** button on top of the board.
3. Plug USB back in *while holding* B.
4. Release B.

After the first successful upload, you usually don't need this again.

### Workflow — Windows command equivalents

Replace each `make` target with the equivalent PowerShell command.
`COM3` is a placeholder; use whatever `GetPortNames()` returned.

#### Build + upload

```powershell
pio run                                    # build
pio run -t upload --upload-port COM3       # upload
```

#### Live serial monitor

```powershell
pio device monitor --port COM3 --rts 0 --dtr 0
```

The `--rts 0 --dtr 0` flags are essential — without them, opening the
port can re-strap GPIO0 low and bounce the chip into the bootloader.

#### Capture one image to `image.jpg`

Save this as `tools\grab_win.ps1`:

```powershell
param([string]$Port = 'COM3', [string]$Out = 'image.jpg')

$port = [System.IO.Ports.SerialPort]::new($Port, 115200)
$port.DtrEnable  = $false   # try to keep modem lines low; see caveats
$port.RtsEnable  = $false
$port.ReadTimeout = 25000   # 25 s per line; chip emits a frame every 3 s
try {
    $port.Open()
    $lines   = New-Object System.Collections.Generic.List[string]
    $inFrame = $false
    while ($true) {
        try { $line = $port.ReadLine().TrimEnd("`r","`n") }
        catch [TimeoutException] {
            throw "no data on $Port - chip may be in bootloader. Run: pio run -t upload --upload-port $Port"
        }
        if (-not $inFrame) {
            if ($line.StartsWith('JPEG_BEGIN')) { $inFrame = $true; Write-Host $line }
            else { Write-Host "  $line" }
            continue
        }
        if ($line -eq 'JPEG_END') { break }
        $lines.Add($line) | Out-Null
    }
    $bytes = [Convert]::FromBase64String([string]::Join('', $lines))
    if ($bytes[0] -ne 0xFF -or $bytes[1] -ne 0xD8 -or $bytes[2] -ne 0xFF) {
        throw "decoded data is not a JPEG (starts with $($bytes[0..3] -join ','))"
    }
    [IO.File]::WriteAllBytes($Out, $bytes)
    Write-Host "saved $Out ($($bytes.Length) bytes)"
} finally {
    if ($port.IsOpen) { $port.Close() }
}
Invoke-Item .\$Out         # opens in default Windows image viewer
```

Run it:

```powershell
.\tools\grab_win.ps1 -Port COM3
```

#### Burst capture for Edge Impulse

Save as `tools\capture_win.py`:

```python
import base64, re, sys, time
from pathlib import Path
import serial

if len(sys.argv) < 3:
    sys.exit("usage: capture_win.py PORT CLASS [N]")
PORT, CLASS = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 50
if not re.match(r"^[A-Za-z0-9_-]+$", CLASS):
    sys.exit("invalid CLASS: letters, digits, '_', '-' only")

s = serial.Serial()
s.port = PORT; s.baudrate = 115200; s.timeout = 25
s.dtr = False; s.rts = False     # try to keep modem lines low; see caveats
s.open()

out_dir = Path("data") / CLASS
out_dir.mkdir(parents=True, exist_ok=True)
existing = [int(p.stem) for p in out_dir.glob("[0-9][0-9][0-9][0-9].jpg")
            if p.stem.isdigit()]
start = (max(existing) + 1) if existing else 0

saved = 0
try:
    for i in range(N):
        chunks, in_frame = [], False
        deadline = time.monotonic() + 25
        got = False
        while time.monotonic() < deadline:
            line = s.readline().decode(errors="replace").strip()
            if not in_frame:
                if line.startswith("JPEG_BEGIN"):
                    in_frame = True
                continue
            if line == "JPEG_END":
                data = base64.b64decode("".join(chunks), validate=False)
                if data.startswith(b"\xff\xd8\xff"):
                    p = out_dir / f"{start+saved:04d}.jpg"
                    p.write_bytes(data)
                    saved += 1
                    print(f"[{saved}/{N}] {p} ({len(data)} bytes)")
                    got = True
                break
            chunks.append(line)
        if not got:
            print(f"  ! attempt {i+1}: timeout, skipping")
finally:
    s.close()
print(f"done: {saved}/{N} in {out_dir}")
```

Run:

```powershell
python tools\capture_win.py COM3 hotdog 50
```

#### Push to Edge Impulse

Same as macOS:

```powershell
edge-impulse-uploader --label hotdog --category split data\hotdog\*.jpg
```

---

## Caveats for native Windows

The macOS scripts use `cat /dev/cu.usbmodem*` because pyserial on macOS
asserts DTR briefly when opening the port, which the ESP32-S3
USB-Serial-JTAG interprets as a strap-pin signal and reboots into the
bootloader.  `cat` on `cu.*` devices doesn't do this.

On Windows the situation is **less clean than path 1**:

- `cat COM3` doesn't work (Windows COM ports need `CreateFile` calls
  that GNU `cat` doesn't make), so we have no equivalent of the macOS
  workaround.
- pyserial and `System.IO.Ports.SerialPort` *try* to honor
  `dtr=False`/`DtrEnable=$false` set before `.open()`, **but** both
  underlying APIs (`SetCommState`/`EscapeCommFunction`) have a known
  race window where DTR can be momentarily asserted during open
  ([dotnet/runtime#37841](https://github.com/dotnet/runtime/issues/37841),
  pyserial docs note "There may be a glitch on RTS/DTR").
- In practice the inline scripts above usually work on USB-CDC because
  the glitch is too short for the ESP32-S3 firmware to see, but
  **this isn't guaranteed**.

If the inline scripts fail to read any frames:

1. Re-flash to make sure the chip is in app mode:
   `pio run -t upload --upload-port COM3`
2. Verify with `pio device monitor --port COM3 --rts 0 --dtr 0` — you
   should see `BOOT psram=yes` and `JPEG_BEGIN` lines every 3 s.
3. If `pio device monitor` works but the inline script doesn't, that
   confirms the DTR-glitch is the problem on your Windows install.
   **Switch to path 1 (WSL2)** — there's no clean fix on native Windows.

This is the honest reason we recommend WSL2: the macOS path was
deliberately designed around the macOS quirk, and its scripts work
unchanged in WSL2.  Native Windows is doable for build/upload/monitor
but the data-capture step has a fragile dependency on driver behavior
we can't guarantee.
