#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Run on Vermeer under Linux. --capture also tests RAW and processed frames.

set -u

capture=no
if [ "${1:-}" = "--capture" ]; then
	capture=yes
	shift
fi
if [ "$#" -gt 1 ] || [ "${1:-}" = "--help" ]; then
	echo "Usage: sh $0 [--capture] [report-directory]"
	exit 2
fi

report=${1:-vermeer-camera-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$report" || exit 1
report=$(cd "$report" && pwd) || exit 1

uname -a > "$report/uname.txt"
cat /proc/cmdline > "$report/cmdline.txt"
cat /etc/os-release > "$report/os-release.txt" 2>/dev/null
for module in i2c-qcom-cci qcom-camss imx355; do
	modprobe "$module" >> "$report/modprobe.txt" 2>&1
done

snapshot()
{
	dmesg > "$report/dmesg-$1.txt" 2>&1
	for name in regulator/regulator_summary clk/clk_summary devices_deferred; do
		if [ -r "/sys/kernel/debug/$name" ]; then
			cat "/sys/kernel/debug/$name" > "$report/$(basename "$name")-$1.txt"
		fi
	done
}

snapshot before
ls -l /dev/media* /dev/video* /dev/v4l-subdev* /dev/dma_heap/* /dev/udmabuf \
	> "$report/devices.txt" 2>&1
ls -l /sys/bus/i2c/drivers/imx355/ /sys/bus/i2c/drivers/wl2868c-regulator/ \
	> "$report/drivers.txt" 2>&1
lsmod > "$report/lsmod.txt" 2>&1

if command -v media-ctl >/dev/null 2>&1; then
	for media in /dev/media*; do
		[ -e "$media" ] || continue
		media-ctl -d "$media" -p > "$report/$(basename "$media").txt" 2>&1
	done
fi
if command -v v4l2-ctl >/dev/null 2>&1; then
	v4l2-ctl --list-devices > "$report/v4l2-devices.txt" 2>&1
	for subdev in /dev/v4l-subdev*; do
		[ -e "$subdev" ] || continue
		v4l2-ctl -d "$subdev" --list-ctrls \
			> "$report/$(basename "$subdev")-controls.txt" 2>&1
	done
fi

if ! command -v cam >/dev/null 2>&1 || ! command -v timeout >/dev/null 2>&1; then
	echo "Kernel diagnostics saved in $report"
	echo "Install libcamera's cam tool and timeout to test capture."
	[ "$capture" = no ] && exit 0
	exit 1
fi

export LIBCAMERA_LOG_LEVELS='*:DEBUG'
export LIBCAMERA_LOG_COLOR=0
timeout 45 cam --list > "$report/cameras.txt" 2>&1
list_status=$?
cat "$report/cameras.txt"
if [ "$capture" = no ]; then
	echo "Diagnostics saved in $report; capture has not been tested."
	exit "$list_status"
fi

# Newer cam versions print "Internal back camera" instead of the sensor model.
camera=$(awk '/^[[:space:]]*[0-9]+:/ && (/imx355/ || (/cci@ac15000/ && /i2c-bus@1\/camera@1a/)) { sub(/:$/, "", $1); print $1; exit }' \
	"$report/cameras.txt")
if [ -z "$camera" ]; then
	echo "IMX355 was not registered by libcamera. See $report"
	exit 1
fi

mkdir -p "$report/raw" "$report/processed" || exit 1
timeout 60 cam --camera "$camera" \
	--stream role=raw,width=1640,height=1232 \
	--capture=5 --file="$report/raw/frame-#.bin" \
	> "$report/raw-capture.txt" 2>&1
raw_status=$?
timeout 60 cam --camera "$camera" \
	--stream role=viewfinder,width=1640,height=1232,pixelformat=RGB888 \
	--capture=30 --file="$report/processed/frame-#.bin" \
	> "$report/processed-capture.txt" 2>&1
processed_status=$?
snapshot after

echo "RAW capture exit status: $raw_status"
echo "Processed capture exit status: $processed_status"
echo "Frames and logs saved in $report"
if [ "$raw_status" -ne 0 ] || [ "$processed_status" -ne 0 ]; then
	exit 1
fi
for stream in raw processed; do
	found=no
	for frame in "$report/$stream"/*.bin; do
		[ -s "$frame" ] && found=yes
	done
	if [ "$found" = no ]; then
		echo "No nonempty $stream frames were saved."
		exit 1
	fi
done
echo "Both capture commands completed. Inspect frames to verify the image."
