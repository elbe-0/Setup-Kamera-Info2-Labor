#!/usr/bin/env python3
"""Capture one JPEG from the XIAO ESP32S3 Sense over USB.

Why this script doesn't use pyserial directly
---------------------------------------------
On macOS, opening /dev/cu.usbmodem* with pyserial toggles the DTR/RTS
modem-control lines as a side effect.  The ESP32-S3's native USB-Serial-JTAG
peripheral interprets those toggles as the GPIO0 strap pin being pulled low
at reset, which reboots the chip straight back into the ROM bootloader -- no
serial output ever appears.  `cat` does not toggle modem lines on `cu.*`
devices, so we read with `cat` via subprocess and parse its stdout.

What it does
------------
1. Spawns `cat <port>` and waits for the framing emitted by src/main.cpp:
       JPEG_BEGIN len=<n> w=<W> h=<H>
       <base64 line>
       ...
       JPEG_END
2. Decodes the base64 and writes the JPEG to disk (default: image.jpg).

If the read times out, the chip is most likely stuck in the bootloader.
Run `make reset` (or `esptool --after watchdog-reset run`) and try again.

Usage
-----
    python3 tools/grab.py                # writes image.jpg
    python3 tools/grab.py shot.jpg       # custom output path
    PORT=/dev/cu.usbmodem1101 python3 tools/grab.py
    TIMEOUT=30 python3 tools/grab.py     # per-frame timeout in seconds (default 20)
"""
from __future__ import annotations

import base64
import glob
import os
import subprocess
import sys
import time

PORT_GLOB = os.environ.get("PORT", "/dev/cu.usbmodem*")
TIMEOUT_S = float(os.environ.get("TIMEOUT", "20"))


def find_port() -> str:
    """Return the first matching serial port, or exit with a clear error."""
    if "*" not in PORT_GLOB:
        return PORT_GLOB
    matches = sorted(glob.glob(PORT_GLOB))
    if not matches:
        sys.exit(f"no serial port matching {PORT_GLOB!r} - is the board plugged in?")
    return matches[0]


def read_until_jpeg(port: str) -> tuple[str, bytes]:
    """Spawn `cat <port>` and return (header_line, jpeg_bytes)."""
    proc = subprocess.Popen(
        ["cat", port],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    stdout = proc.stdout
    assert stdout is not None, "subprocess.PIPE should yield a readable stdout"
    deadline = time.monotonic() + TIMEOUT_S
    buf = bytearray()
    header: str | None = None
    chunks: list[str] = []

    try:
        while time.monotonic() < deadline:
            byte = stdout.read(1)
            if not byte:
                continue
            buf.extend(byte)
            if byte != b"\n":
                continue
            # process one complete line
            line = buf.decode("utf-8", errors="replace").rstrip("\r\n")
            buf.clear()

            if header is None:
                if line.startswith("JPEG_BEGIN"):
                    header = line
                    print(line)
                else:
                    # surface whatever the firmware prints while we wait
                    if line:
                        print(f"  · {line}")
                continue

            if line == "JPEG_END":
                return header, base64.b64decode("".join(chunks), validate=False)
            chunks.append(line)
        sys.exit(f"timed out after {TIMEOUT_S:.0f}s waiting for a JPEG frame")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "image.jpg"
    port = find_port()
    print(f"port: {port}")

    header, data = read_until_jpeg(port)
    if not data.startswith(b"\xff\xd8\xff"):
        sys.exit(f"decoded data is not a JPEG (starts with {data[:4]!r})")

    with open(out_path, "wb") as f:
        f.write(data)
    print(f"saved {out_path} ({len(data)} bytes) - {header}")


if __name__ == "__main__":
    main()
