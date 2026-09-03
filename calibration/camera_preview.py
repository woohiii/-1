#!/usr/bin/env python
"""3-window live camera preview: Astra S depth camera (IR mode) + 2 USB wrist cameras.

IMPORTANT - run with the OTHER venv, NOT the lerobot uv venv:
    ~/lerobot_song_venv/bin/python calibration/camera_preview.py

This script needs the `primesense` package (OpenNI2 bindings for the Astra S)
and a GUI-enabled OpenCV build (cv2.imshow). Neither is available in
/home/youngchan/lerobot's uv-managed venv (that one has headless opencv, where
cv2.imshow raises an error) - both exist only in ~/lerobot_song_venv. Do NOT
run this via `uv run --project /home/youngchan/lerobot ...`.

The Astra S can only be held open by one process at a time - close any other
running astra_s_*.py script before running this one.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, "/home/youngchan/lerobot/custom_scripts/vision_pick_place")
from camera_utils import find_camera_index  # noqa: E402
from orbbec_color_camera import DEFAULT_OPENNI2_REDIST_DIR  # noqa: E402
from primesense import openni2  # noqa: E402

CAMERAS_JSON = Path(__file__).parent / "cameras.json"


def load_cameras():
    with open(CAMERAS_JSON) as f:
        return json.load(f)


def self_test():
    checks = []
    try:
        cameras = load_cameras()
        checks.append(("cameras.json parses with wrist_1_name/wrist_2_name", {"wrist_1_name", "wrist_2_name"} <= cameras.keys()))
    except Exception as e:
        print(f"FAIL: cameras.json parses with wrist_1_name/wrist_2_name ({e})")
        cameras = {}

    for key in ("wrist_1_name", "wrist_2_name"):
        name = cameras.get(key)
        if name is None:
            continue
        idx = find_camera_index(name)
        if idx is not None:
            print(f"PASS: {key} ('{name}') resolved to /dev/video{idx}")
        else:
            print(f"FAIL: {key} ('{name}') not found (camera may not be plugged in)")

    checks.append(("v4l2-ctl available", shutil.which("v4l2-ctl") is not None))

    ok = True
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
        ok = ok and passed

    return 0 if ok else 1


def ir_frame_to_display(raw):
    """16-bit raw IR -> 8-bit displayable image via percentile contrast stretch."""
    valid = raw[raw > 0]
    if valid.size:
        lo, hi = np.percentile(valid, (2, 98))
        return np.clip((raw.astype(np.float32) - lo) * 255.0 / max(hi - lo, 1.0), 0, 255).astype(np.uint8)
    return np.zeros(raw.shape, dtype=np.uint8)


def open_astra_ir():
    openni2.initialize(str(DEFAULT_OPENNI2_REDIST_DIR))
    device = openni2.Device.open_any()
    stream = device.create_ir_stream()
    if stream is None:
        raise RuntimeError("Astra S IR stream is unavailable on this device/driver")
    stream.configure_mode(640, 480, 30, openni2.PIXEL_FORMAT_GRAY16)
    stream.set_mirroring_enabled(False)
    stream.start()
    return device, stream


def open_wrist(name, label):
    idx = find_camera_index(name)
    if idx is None:
        print(f"ERROR: {label} ('{name}') not found - skipping this window")
        return None
    cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"ERROR: {label} ('{name}') at /dev/video{idx} could not be opened - skipping this window")
        return None
    return cap


def run_preview(cameras):
    device = stream = wrist1 = wrist2 = None
    try:
        device, stream = open_astra_ir()
        wrist1 = open_wrist(cameras["wrist_1_name"], "Wrist 1")
        wrist2 = open_wrist(cameras["wrist_2_name"], "Wrist 2")

        while True:
            frame = stream.read_frame()
            raw = np.frombuffer(bytes(frame.get_buffer_as_uint16()), dtype=np.uint16).reshape(frame.height, frame.width)
            cv2.imshow("Astra S IR", ir_frame_to_display(raw))

            if wrist1 is not None:
                ok, img = wrist1.read()
                if ok:
                    cv2.imshow("Wrist 1", img)
            if wrist2 is not None:
                ok, img = wrist2.read()
                if ok:
                    cv2.imshow("Wrist 2", img)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        if stream is not None:
            stream.stop()
        if device is not None:
            device.close()
        if wrist1 is not None:
            wrist1.release()
        if wrist2 is not None:
            wrist2.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true", help="Validate cameras.json + resolve indices (no hardware streams)")
    args = parser.parse_args()

    if args.self_test:
        sys.exit(self_test())

    run_preview(load_cameras())


if __name__ == "__main__":
    main()
