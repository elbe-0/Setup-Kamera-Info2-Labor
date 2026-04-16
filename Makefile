# XIAO ESP32S3 Sense camera demo - student-friendly entry points.
#
# Quick start (after cloning):
#   make setup          # one time - verifies tools are installed
#   make all            # build + upload + grab a test image + open it
#
# Less common targets:
#   make build          # compile only
#   make upload         # flash without grabbing an image
#   make reset          # bounce the chip into the application firmware
#   make grab           # capture image.jpg from the running firmware
#   make show           # open image.jpg
#   make monitor        # live serial output (Ctrl+C to quit)
#   make clean          # remove build artifacts and image.jpg
#
# Edge Impulse data flow (after `make all` works):
#   make capture CLASS=hotdog N=50  # save 50 frames to data/hotdog/
#   make ei-upload CLASS=hotdog     # push that folder to your EI project
#
# Notes:
#   - PORT is auto-detected from /dev/cu.usbmodem* (override: make grab PORT=...)
#   - First flash on a brand-new board may need the B button: hold B, plug USB,
#     release B, then run `make upload`.  After that, subsequent flashes don't.
#   - The host scripts (tools/*.py) are stdlib-only - no virtualenv required.

PORT     ?= $(shell ls /dev/cu.usbmodem* 2>/dev/null | head -n 1)
PYTHON   := python3

.PHONY: help setup build upload reset grab show monitor all clean capture ei-upload

help:
	@awk '/^# / && !/^#!/ {sub("# ?",""); print}' $(MAKEFILE_LIST) | head -32

setup:
	@command -v pio       >/dev/null || { echo "PlatformIO missing: brew install platformio"; exit 1; }
	@command -v esptool   >/dev/null || { echo "esptool missing: pipx install esptool"; exit 1; }
	@command -v $(PYTHON) >/dev/null || { echo "python3 missing - install Xcode Command Line Tools"; exit 1; }
	@echo "ready - try: make all"

build:
	pio run

upload: build
	@test -n "$(PORT)" || { echo "no serial port found at /dev/cu.usbmodem*"; exit 1; }
	pio run -t upload --upload-port $(PORT)

# Recovery target: forces the chip out of the ROM bootloader / stub flasher
# and back into the application firmware via watchdog reset.  Use this if
# `make grab` times out -- it usually means the chip is stuck in the
# bootloader (e.g., the B button was pressed but no upload ran since).
reset:
	@test -n "$(PORT)" || { echo "no serial port found"; exit 1; }
	esptool --chip esp32s3 --port $(PORT) --before default-reset --after watchdog-reset run

grab:
	@test -n "$(PORT)" || { echo "no serial port found"; exit 1; }
	PORT=$(PORT) $(PYTHON) tools/grab.py image.jpg

show:
	@test -f image.jpg || { echo "no image.jpg yet - run: make grab"; exit 1; }
	open image.jpg

monitor:
	@test -n "$(PORT)" || { echo "no serial port found"; exit 1; }
	pio device monitor --port $(PORT) --rts 0 --dtr 0

all: upload grab show

# ---- Edge Impulse data collection ----------------------------------------
# Burst-capture N frames into data/<CLASS>/.  Override N for batch size.
#   make capture CLASS=hotdog          (defaults to N=50)
#   make capture CLASS=hotdog N=100
N ?= 50
capture:
	@test -n "$(CLASS)" || { echo "usage: make capture CLASS=<name> [N=50]"; exit 1; }
	@test -n "$(PORT)"  || { echo "no serial port found"; exit 1; }
	PORT=$(PORT) $(PYTHON) tools/capture.py $(CLASS) $(N)

# Upload an already-captured class folder to your Edge Impulse project.
# Runs the EI CLI's interactive auth on first use; cached afterwards.
#   make ei-upload CLASS=hotdog
ei-upload:
	@test -n "$(CLASS)" || { echo "usage: make ei-upload CLASS=<name>"; exit 1; }
	@test -d data/$(CLASS) || { echo "no data/$(CLASS)/ directory yet - run: make capture CLASS=$(CLASS)"; exit 1; }
	@ls data/$(CLASS)/*.jpg >/dev/null 2>&1 || { echo "data/$(CLASS)/ has no JPEGs - run: make capture CLASS=$(CLASS)"; exit 1; }
	@command -v edge-impulse-uploader >/dev/null || { echo "edge-impulse-uploader missing: npm install -g edge-impulse-cli"; exit 1; }
	edge-impulse-uploader --label $(CLASS) --category split data/$(CLASS)/*.jpg

clean:
	rm -rf .pio image.jpg
