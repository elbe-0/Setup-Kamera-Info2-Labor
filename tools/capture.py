#!/usr/bin/env python3
"""Burst-capture frames from the XIAO and save them as a labeled dataset.

Saves to:  data/<CLASS>/<index>.jpg
File names are zero-padded so they sort lexicographically and you can resume
a batch without overwriting (next free 4-digit index is found per run).

Usage
-----
    python3 tools/capture.py CLASS [N]

    CLASS  - dataset class name (e.g. "hotdog").  Becomes data/<CLASS>/.
             Must be a simple identifier: letters, digits, '_', '-'.
    N      - number of frames to capture (default: 50).

Environment
-----------
    PORT       - serial port glob/path (default: /dev/cu.usbmodem*)
    DELAY      - extra seconds between frames after the firmware's own 3 s
                 loop; useful when you need to move the subject (default: 0)
    TIMEOUT    - per-frame timeout in seconds (default: 20)

Why this script reads the port via `cat` (not pyserial)
-------------------------------------------------------
On macOS, opening /dev/cu.usbmodem* with pyserial toggles the DTR/RTS
modem-control lines as a side effect.  The ESP32-S3's native USB-Serial-JTAG
peripheral interprets those toggles as the GPIO0 strap pin being pulled low
at reset, which reboots the chip into the ROM bootloader -- no serial
output appears.  `cat` does not toggle modem lines on `cu.*` devices, so
this script (and tools/grab.py) read the port via a `cat` subprocess.

Tip
---
Edge Impulse Studio's bulk uploader (`edge-impulse-uploader`) reads the
data/<class>/*.jpg layout directly -- no renaming step needed.
"""
from __future__ import annotations

import base64
import glob
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PORT_GLOB = os.environ.get("PORT", "/dev/cu.usbmodem*")
TIMEOUT_S = float(os.environ.get("TIMEOUT", "20"))
DELAY_S   = float(os.environ.get("DELAY", "0"))

# Class names become directory names.  Restrict to a safe identifier set so
# a typo like CLASS=../etc cannot escape the data/ directory.
CLASS_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def find_port() -> str:
    if "*" not in PORT_GLOB:
        return PORT_GLOB
    matches = sorted(glob.glob(PORT_GLOB))
    if not matches:
        sys.exit(f"no serial port matching {PORT_GLOB!r} - is the board plugged in?")
    return matches[0]


def validate_class_name(name: str) -> str:
    """Reject anything that isn't a simple identifier - prevents path
    traversal (CLASS=../foo) and avoids surprises with hidden dirs."""
    if not CLASS_NAME_RE.match(name):
        sys.exit(
            f"invalid CLASS {name!r}: use only letters, digits, '_' and '-'"
        )
    return name


def next_index(class_dir: Path) -> int:
    """Return the next free 4-digit index for class_dir, never overwriting."""
    class_dir.mkdir(parents=True, exist_ok=True)
    existing = [
        int(p.stem) for p in class_dir.glob("[0-9]" * 4 + ".jpg")
        if p.stem.isdigit()
    ]
    return (max(existing) + 1) if existing else 0


def capture_one(stdout, deadline: float) -> bytes:
    """Read one JPEG_BEGIN..JPEG_END frame from `stdout`, return JPEG bytes.

    The firmware emits frames continuously; we ignore everything until the
    first JPEG_BEGIN we see, so spawning `cat` mid-frame is harmless -- we
    just lose the partial frame and pick up the next complete one.
    """
    buf = bytearray()
    header_seen = False
    chunks: list[str] = []
    while time.monotonic() < deadline:
        byte = stdout.read(1)
        if not byte:
            continue
        buf.extend(byte)
        if byte != b"\n":
            continue
        line = buf.decode("utf-8", errors="replace").rstrip("\r\n")
        buf.clear()
        if not header_seen:
            if line.startswith("JPEG_BEGIN"):
                header_seen = True
            continue
        if line == "JPEG_END":
            return base64.b64decode("".join(chunks), validate=False)
        chunks.append(line)
    raise TimeoutError(f"no JPEG frame within {TIMEOUT_S:.0f}s")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: capture.py CLASS [N]")
    class_name = validate_class_name(sys.argv[1])
    n_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    class_dir = Path("data") / class_name
    start = next_index(class_dir)
    port = find_port()
    print(f"capturing {n_frames} frames into {class_dir}/ "
          f"starting at {start:04d} (port: {port})")

    proc = subprocess.Popen(
        ["cat", port],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
    )
    stdout = proc.stdout
    assert stdout is not None, "subprocess.PIPE always yields a readable stdout"

    saved = 0
    attempts = 0
    try:
        for _ in range(n_frames):
            attempts += 1
            deadline = time.monotonic() + TIMEOUT_S
            try:
                data = capture_one(stdout, deadline)
            except TimeoutError as e:
                print(f"  ! attempt {attempts}: {e}")
                continue
            if not data.startswith(b"\xff\xd8\xff"):
                print(f"  ! attempt {attempts}: not a valid JPEG, skipping")
                continue
            out = class_dir / f"{start + saved:04d}.jpg"
            out.write_bytes(data)
            saved += 1
            print(f"  [{saved:>3}/{n_frames}] {out} ({len(data)} bytes)")
            if DELAY_S > 0 and saved < n_frames:
                time.sleep(DELAY_S)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"done: {saved}/{n_frames} frames in {class_dir}/")


if __name__ == "__main__":
    main()
