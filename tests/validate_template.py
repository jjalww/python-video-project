"""Validate a template against the known Neon clip (ground truth: 4 kills
at ~9.4, 38.3, 40.7, 42.3 s). Tries a few target heights x thresholds and
reports detections, so we can judge whether public API icons are usable.
"""

import sys

import cv2

from valmontage.killdetect.template import DetectionConfig, _kills_from_timeline, _match_positions, _roi_px, _is_death

VIDEO = r"C:\Medal\Clips\Valorant\sample.mp4"
GT = [9.4, 38.3, 40.7, 42.3]


def run(template, heights, thresholds):
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    frames = []
    idx = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if idx % 2 == 0:
            frames.append((idx / fps, f))
        idx += 1
    cap.release()
    H, W = frames[0][1].shape[:2]
    rx1, ry1, rx2, ry2 = _roi_px(W, H, DetectionConfig.roi)

    for th_h in heights:
        tw = int(template.shape[1] * th_h / template.shape[0])
        tmpl = cv2.resize(template, (tw, th_h))
        for thr in thresholds:
            cfg = DetectionConfig(threshold=thr)
            timeline = []
            for t, f in frames:
                roi = f[ry1:ry2, rx1:rx2]
                ms = _match_positions(roi, tmpl, thr, cfg.scales)
                ms = [m for m in ms if not _is_death(roi, m[1], m[2], m[3], m[4])]
                timeline.append((t, len(ms), max((m[0] for m in ms), default=0.0)))
            kills = _kills_from_timeline(timeline, cfg)
            times = [round(k.time, 1) for k in kills]
            print(f"  h={th_h:2d} thr={thr:.2f} -> {len(kills)} kills {times}")


if __name__ == "__main__":
    path = sys.argv[1]
    img = cv2.imread(path)
    print(f"template {path} shape={img.shape}")
    print(f"ground truth: {GT}")
    run(img, heights=[22, 26, 30], thresholds=[0.50, 0.55, 0.60])
