#!/usr/bin/env python
"""Astra S depth-only publisher, watchdog-friendly variant of astra_s_live.py.

Why this exists: astra_s_live.py's ThreadedOrbbecRGBDCamera reads color and
depth in a background thread and caches the last successfully-read frame.
If either native read_frame() call wedges (confirmed this Astra S unit does
this unpredictably - see run_astra_depth_watchdog.sh's comments), the
background thread just silently stops updating the cache forever, while the
outer publish loop keeps re-writing that SAME stale array with a fresh
mtime every iteration - so a file-staleness watchdog can never detect the
hang. Reproduced live: /tmp/vsp_astra_depth_mm.npy stayed at 0.0s "fresh"
indefinitely while the displayed depth image never actually changed.

Fix: read the depth stream directly in the main thread, no background
thread, no cache, no color stream at all (matches astra_s_ir_hub.py's
already-proven-watchdog-detectable pattern) - if read_frame() wedges, this
process visibly stalls and stops writing, which the watchdog's mtime check
correctly catches.

Run standalone in ~/lerobot_song_venv (needs GUI opencv for imshow unless
headless). ASTRA_DEPTH_HUB_HEADLESS=1 skips the window, same convention as
astra_s_ir_hub.py's ASTRA_IR_HUB_HEADLESS.
"""

import os
import sys

import cv2
import numpy as np
from primesense import openni2

sys.path.insert(0, "/home/youngchan/lerobot/custom_scripts/vision_pick_place")
from camera_utils import ASTRA_DEPTH_MM_PATH  # noqa: E402
from orbbec_color_camera import DEFAULT_OPENNI2_REDIST_DIR  # noqa: E402

DEPTH_W, DEPTH_H = 320, 240  # matches astra_s_live.py's depth resolution
# Same close-range convention as astra_s_live.py/camera_preview.py (350-800mm
# covers the table workspace on this rig).
DEPTH_MIN_MM = 350
DEPTH_MAX_MM = 800


def depth_to_display(depth_mm):
    clipped = np.clip(depth_mm, DEPTH_MIN_MM, DEPTH_MAX_MM).astype(np.float32)
    scaled = ((clipped - DEPTH_MIN_MM) * 255.0 / (DEPTH_MAX_MM - DEPTH_MIN_MM)).astype(np.uint8)
    image = cv2.applyColorMap(scaled, cv2.COLORMAP_JET)
    image[depth_mm == 0] = (0, 0, 0)
    return image


def atomic_write_npy(path: str, array) -> None:
    tmp = path + ".tmp.npy"
    np.save(tmp, array)
    os.replace(tmp, path)


def main() -> None:
    headless = os.environ.get("ASTRA_DEPTH_HUB_HEADLESS") == "1"

    openni2.initialize(str(DEFAULT_OPENNI2_REDIST_DIR))
    device = openni2.Device.open_any()
    depth = device.create_depth_stream()
    if depth is None:
        print("[astra_s_depth_hub] Astra S depth 스트림을 열 수 없습니다.")
        device.close()
        return

    try:
        try:
            depth.configure_mode(DEPTH_W, DEPTH_H, 30, openni2.PIXEL_FORMAT_DEPTH_1_MM)
        except Exception:
            pass
        try:
            depth.set_mirroring_enabled(False)
        except Exception:
            pass
        depth.start()

        if not headless:
            cv2.namedWindow("Astra S - Depth", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Astra S - Depth", 640, 480)
            print("[astra_s_depth_hub] 실행 중 - 'q' 또는 ESC로 종료.")
        else:
            print("[astra_s_depth_hub] 실행 중 (headless, ASTRA_DEPTH_HUB_HEADLESS=1) - Ctrl-C로 종료.")

        while True:
            depth_frame = depth.read_frame()
            depth_mm = np.frombuffer(bytes(depth_frame.get_buffer_as_uint16()), dtype=np.uint16).reshape(
                depth_frame.height, depth_frame.width
            )

            atomic_write_npy(ASTRA_DEPTH_MM_PATH, depth_mm)

            if headless:
                continue

            vis = depth_to_display(depth_mm)
            cv2.putText(vis, "ASTRA DEPTH", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("Astra S - Depth", vis)
            if cv2.waitKey(15) & 0xFF in (27, ord("q")):
                break
    finally:
        try:
            depth.stop()
        except Exception:
            pass
        device.close()
        if not headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
