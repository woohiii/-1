#!/usr/bin/env bash
# Runs astra_s_ir_hub.py (headless) and restarts it whenever its published
# IR frame (/tmp/vsp_astra_ir.png) goes stale or the process dies.
#
# Why this exists: confirmed via py-spy that this Astra S unit's OpenNI2 IR
# stream hangs in oniStreamReadFrame after anywhere from seconds to minutes,
# even running astra_s_ir_hub.py completely standalone - not a bug in this
# project's code, an intrinsic flakiness of this device/driver. Killing and
# reopening the device recovers it, so this script automates that instead of
# requiring a manual restart every time it stalls.
#
# astra_s_ir_hub.py already reads the stream directly in its main thread (no
# background-thread cache), so a wedge visibly stalls the process and stops
# the published file's mtime from advancing - correctly detectable by this
# watchdog's staleness check. (astra_s_live.py's threaded RGB+depth camera
# does NOT have this property - see run_astra_depth_watchdog.sh's comments
# for why depth needed its own non-threaded publisher instead of reusing it.)
#
# Only run this OR run_astra_depth_watchdog.sh at a time, never both - the
# Astra S can't run IR and depth streams simultaneously (confirmed:
# depth.start() raises ONI_STATUS_ERROR while IR is running).
#
# ponytail: naive poll-and-restart supervisor (checked every 3s, 8s stale
# threshold). Upgrade to a real watchdog/systemd unit if unattended uptime
# beyond a debugging session ever matters.
#
# Usage: ~/ROBOTICS_PROJECT/calibration/run_astra_ir_watchdog.sh
set -u

FRAME=/tmp/vsp_astra_ir.png
SCRIPT=/home/youngchan/lerobot/custom_scripts/vision_pick_place/astra_s_ir_hub.py
PYTHON=~/lerobot_song_venv/bin/python
STALE_S=8
CHECK_INTERVAL_S=3

export ASTRA_IR_HUB_HEADLESS=1

cleanup() {
    echo "[watchdog] stopping"
    [ -n "${PID:-}" ] && kill -9 "$PID" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

start() {
    "$PYTHON" "$SCRIPT" &
    PID=$!
    echo "[watchdog] started astra_s_ir_hub.py pid=$PID"
}

# A plain process kill+restart wasn't enough to recover this device once it
# wedges (confirmed live: the new process hung on its very first read_frame(),
# never publishing a single frame) - a real USB-level reset was needed.
reset_and_start() {
    kill -9 "$PID" 2>/dev/null
    wait "$PID" 2>/dev/null
    usbreset 2bc5:0402 2>&1 | sed 's/^/[watchdog] usbreset: /'
    sleep 3
    start
}

start
while true; do
    sleep "$CHECK_INTERVAL_S"

    if ! kill -0 "$PID" 2>/dev/null; then
        echo "[watchdog] process died, resetting device and restarting"
        reset_and_start
        continue
    fi

    if [ -f "$FRAME" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$FRAME") ))
        if [ "$age" -gt "$STALE_S" ]; then
            echo "[watchdog] frame stale (${age}s), resetting device and restarting"
            reset_and_start
        fi
    fi
done
