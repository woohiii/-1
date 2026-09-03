#!/usr/bin/env bash
# Runs astra_s_live.py (headless) and restarts it whenever its published
# depth array (/tmp/vsp_astra_depth_mm.npy) goes stale or the process dies.
#
# Why this exists: confirmed via py-spy that this Astra S unit's OpenNI2
# streams can hang in native read calls after anywhere from seconds to
# minutes, even running standalone - not a bug in this project's code, an
# intrinsic flakiness of this device/driver (same finding for IR; depth goes
# through the same OpenNI2 device handle so it's assumed to share the risk).
# Killing and reopening the device recovers it, so this script automates
# that instead of requiring a manual restart every time it stalls.
#
# ponytail: naive poll-and-restart supervisor (checked every 3s, 8s stale
# threshold). Upgrade to a real watchdog/systemd unit if unattended uptime
# beyond a debugging session ever matters.
#
# Usage: ~/ROBOTICS_PROJECT/calibration/run_astra_depth_watchdog.sh
set -u

FRAME=/tmp/vsp_astra_depth_mm.npy
SCRIPT=/home/youngchan/lerobot/custom_scripts/vision_pick_place/astra_s_live.py
PYTHON=~/lerobot_song_venv/bin/python
STALE_S=8
CHECK_INTERVAL_S=3

export ASTRA_LIVE_HEADLESS=1

cleanup() {
    echo "[watchdog] stopping"
    [ -n "${PID:-}" ] && kill -9 "$PID" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

start() {
    "$PYTHON" "$SCRIPT" &
    PID=$!
    echo "[watchdog] started astra_s_live.py pid=$PID"
}

# A plain process kill+restart wasn't enough to recover this device once it
# wedges (confirmed live for the IR path: the new process hung on its very
# first read, never publishing a single frame) - a real USB-level reset was
# needed.
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
