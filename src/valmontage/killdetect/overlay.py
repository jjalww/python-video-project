"""Render a debug overlay video so kill detection can be eyeballed.

Draws the killfeed ROI box, every template match (with score), the live
portrait count, and flags the frames where a kill is registered.
"""

from __future__ import annotations

from pathlib import Path

import cv2

from .template import DetectionConfig, KillEvent, _match_positions, _roi_px, _is_death


def render_debug_overlay(
    video_path: str | Path,
    template_path: str | Path,
    kills: list[KillEvent],
    out_path: str | Path,
    cfg: DetectionConfig | None = None,
) -> Path:
    cfg = cfg or DetectionConfig()
    template = cv2.imread(str(template_path))
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    rx1, ry1, rx2, ry2 = _roi_px(W, H, cfg.roi)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))

    kill_times = [k.time for k in kills]
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), (255, 255, 0), 1)

        if idx % cfg.sample_stride == 0:
            roi = frame[ry1:ry2, rx1:rx2]
            for score, x, y, w, h in _match_positions(roi, template, cfg.threshold, cfg.scales):
                dead = cfg.reject_deaths and _is_death(roi, x, y, w, h)
                col = (0, 0, 255) if dead else (0, 255, 0)
                cv2.rectangle(frame, (rx1 + x, ry1 + y), (rx1 + x + w, ry1 + y + h), col, 2)
                cv2.putText(frame, f"{score:.2f}", (rx1 + x, ry1 + y - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1, cv2.LINE_AA)

        # flag a kill near this time
        if any(abs(t - kt) < 0.10 for kt in kill_times):
            cv2.putText(frame, "KILL", (rx1, ry2 + 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
        n_so_far = sum(1 for kt in kill_times if kt <= t + 1e-6)
        cv2.putText(frame, f"t={t:5.2f}s  kills={n_so_far}", (10, H - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)

        writer.write(frame)
        idx += 1

    cap.release()
    writer.release()
    return out_path
