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
thread, no cache (matches astra_s_ir_hub.py's already-proven-watchdog-
detectable pattern) - if read_frame() wedges, this process visibly stalls
and stops writing, which the watchdog's mtime check correctly catches.

2026-09-04, attempt 1 (reverted): tried reading color synchronously in this
same main-thread loop, right after the depth read, to also publish RGB.
Broke live within a minute - color.read_frame() wedged, which stalled the
WHOLE loop including the depth write after it, so the watchdog had to
USB-reset the device. Confirmed via the published depth file going stale
during a live recording-prep session.

2026-09-04, attempt 2 (this version): color now lives entirely in its own
background thread (_ColorFrameCache) - open/configure/start/read all happen
there, main() never calls anything color-related. If color wedges, only
that thread's cache goes stale; main()'s depth.read_frame() -> write loop
below is unmodified from the original fix above and cannot be blocked by it
(separate OS thread, and native blocking calls release the GIL). Also does
NOT enable depth-to-color image registration - that changes the recorded
depth array's own values/alignment, and this depth feed is what's actually
going into training datasets (see the towel-fold bimanual recordings) -
not worth risking a semantics mismatch between old and new recordings for a
preview overlay. camera_preview.py's RGB grasp-point overlay already treats
the RGB/depth alignment as an approximation, not exact registration.

Run standalone in ~/lerobot_song_venv (needs GUI opencv for imshow unless
headless). ASTRA_DEPTH_HUB_HEADLESS=1 skips the window, same convention as
astra_s_ir_hub.py's ASTRA_IR_HUB_HEADLESS.
"""

import os
import sys
import threading

import cv2
import numpy as np
from primesense import openni2

sys.path.insert(0, "/home/youngchan/lerobot/custom_scripts/vision_pick_place")
from camera_utils import ASTRA_DEPTH_MM_PATH, ASTRA_RGB_FRAME_PATH  # noqa: E402
from orbbec_color_camera import DEFAULT_OPENNI2_REDIST_DIR  # noqa: E402

DEPTH_W, DEPTH_H = 320, 240  # matches astra_s_live.py's depth resolution
# 2026-09-04: dropped from VGA to QVGA (matches depth) after color still stalled
# for 25s+ straight at VGA even fully isolated in its own thread - that
# "VGA color + QVGA depth" combo was only proven stable for SEQUENTIAL reads
# from one thread (orbbec_color_camera.py); two threads concurrently pulling
# frames off the same device may hit a different (USB bandwidth?) ceiling.
# Lower resolution costs nothing here - color is a screen-sized preview, not
# used for precise pixel work.
COLOR_W, COLOR_H = 320, 240
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


def atomic_write_png(path: str, frame) -> None:
    tmp = path + ".tmp.png"
    cv2.imwrite(tmp, frame)
    os.replace(tmp, path)


class _ColorFrameCache:
    """Reads the Astra S color stream in its own background thread. ALL
    color device interaction (create/configure/start/read) happens here,
    isolated from main()'s depth loop - if any of it hangs or errors, only
    this cache goes stale/empty. It must never be able to block or delay
    main()'s depth.read_frame() below, since that's what recording actually
    depends on; RGB here is a preview nice-to-have."""

    def __init__(self, device):
        self._device = device
        self._lock = threading.Lock()
        self._frame = None
        self._frame_id = 0
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            color = self._device.create_color_stream()
            if color is None:
                print("[astra_s_depth_hub] 컬러 스트림 미지원 - RGB 없이 depth만 발행합니다.")
                return
            try:
                color.configure_mode(COLOR_W, COLOR_H, 30, openni2.PIXEL_FORMAT_RGB888)
            except Exception:
                pass
            try:
                color.set_mirroring_enabled(False)
            except Exception:
                pass
            color.start()
        except Exception as e:
            print(f"[astra_s_depth_hub] 경고: 컬러 스트림을 열 수 없습니다 - RGB 없이 depth만 발행합니다: {e}")
            return

        while self._running:
            try:
                frame = color.read_frame()
                h, w = frame.height, frame.width
                img_rgb = np.frombuffer(bytes(frame.get_buffer_as_uint8()), dtype=np.uint8).reshape(h, w, 3)
                bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            except Exception:
                continue  # a dropped/errored color frame just retries - never touches depth
            with self._lock:
                self._frame = bgr
                self._frame_id += 1

        try:
            color.stop()
        except Exception:
            pass

    def latest_new_frame(self, last_seen_id: int):
        """Returns (frame, new_id) if a frame newer than last_seen_id has
        arrived, else (None, last_seen_id) - so the caller can skip
        rewriting the published PNG (and thus its mtime) once color has
        stalled, instead of faking freshness on a frozen frame."""
        with self._lock:
            if self._frame is None or self._frame_id == last_seen_id:
                return None, last_seen_id
            return self._frame, self._frame_id

    def stop(self):
        self._running = False


def main() -> None:
    headless = os.environ.get("ASTRA_DEPTH_HUB_HEADLESS") == "1"

    openni2.initialize(str(DEFAULT_OPENNI2_REDIST_DIR))
    device = openni2.Device.open_any()
    depth = device.create_depth_stream()
    if depth is None:
        print("[astra_s_depth_hub] Astra S depth 스트림을 열 수 없습니다.")
        device.close()
        return

    color_cache = _ColorFrameCache(device)
    last_rgb_id = 0

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

            new_rgb, last_rgb_id = color_cache.latest_new_frame(last_rgb_id)
            if new_rgb is not None:
                atomic_write_png(ASTRA_RGB_FRAME_PATH, new_rgb)

            if headless:
                continue

            vis = depth_to_display(depth_mm)
            cv2.putText(vis, "ASTRA DEPTH", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("Astra S - Depth", vis)
            if cv2.waitKey(15) & 0xFF in (27, ord("q")):
                break
    finally:
        color_cache.stop()
        try:
            depth.stop()
        except Exception:
            pass
        device.close()
        if not headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
