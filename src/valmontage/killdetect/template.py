"""Phase 2: detect the player's kills by template-matching their agent's
killfeed portrait in the top-right region of the screen.

Why this works: in a Valorant match every agent is unique across both
teams, so the player's agent portrait is a one-of-a-kind icon. When the
player kills, the portrait shows on the *killer* (left) side of a
killfeed row with the player's team-coloured nameplate; when they die it
shows on the *victim* (right) side with a red nameplate.

The killfeed is right-anchored, so a portrait's x-position shifts with
entry width -> we scan the whole killfeed band rather than a fixed box.
A kill stays in the feed for several seconds, so a single kill yields
many consecutive matches. We therefore count distinct portraits per
frame and treat *rising edges* of that count as new kills, which also
captures multikills (count climbs 1->2->3 for a triple).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class KillEvent:
    time: float          # seconds into the video
    score: float         # template match confidence at detection
    count: int           # killfeed portrait count when this kill registered


@dataclass
class DetectionConfig:
    roi: tuple[float, float, float, float] = (0.60, 0.0, 1.0, 0.32)  # x1,y1,x2,y2 fractions
    threshold: float = 0.62
    scales: tuple[float, ...] = (0.85, 0.92, 1.0, 1.08, 1.16)
    sample_stride: int = 2          # analyse every Nth frame
    persist_seconds: float = 0.12   # a count change must hold this long
    min_gap_seconds: float = 0.20   # ignore kills closer than this
    reject_deaths: bool = True      # drop matches whose left side is red (victim slot)


def _roi_px(w: int, h: int, roi) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = roi
    return int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)


def _match_positions(roi_bgr, template, threshold, scales):
    """Return non-max-suppressed matches as (score, x, y, w, h) in ROI coords."""
    th, tw = template.shape[:2]
    cands = []
    for s in scales:
        tw_s, th_s = max(1, int(tw * s)), max(1, int(th * s))
        if th_s >= roi_bgr.shape[0] or tw_s >= roi_bgr.shape[1]:
            continue
        tmpl = template if s == 1.0 else cv2.resize(template, (tw_s, th_s))
        res = cv2.matchTemplate(roi_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        for x, y in zip(xs.tolist(), ys.tolist()):
            cands.append((float(res[y, x]), x, y, tw_s, th_s))

    cands.sort(reverse=True)
    kept: list[tuple[float, int, int, int, int]] = []
    for score, x, y, w, h in cands:
        if all(abs(x - kx) > w * 0.6 or abs(y - ky) > h * 0.6 for _, kx, ky, _, _ in kept):
            kept.append((score, x, y, w, h))
    return kept


def _is_death(roi_bgr, x, y, w, h) -> bool:
    """A victim-slot portrait has a red nameplate to its LEFT."""
    strip = roi_bgr[max(0, y):y + h, max(0, x - w):max(1, x)]
    if strip.size == 0:
        return False
    b, g, r = strip[..., 0].mean(), strip[..., 1].mean(), strip[..., 2].mean()
    return r > 90 and r > g * 1.4 and r > b * 1.4


def detect_kills(
    video_path: str | Path,
    template_path: str | Path,
    cfg: DetectionConfig | None = None,
) -> list[KillEvent]:
    cfg = cfg or DetectionConfig()
    template = cv2.imread(str(template_path))
    if template is None:
        raise FileNotFoundError(f"template not found: {template_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0

    rx1 = ry1 = rx2 = ry2 = None
    timeline: list[tuple[float, int, float]] = []  # (t, count, best_score)

    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % cfg.sample_stride == 0:
            if rx1 is None:
                H, W = frame.shape[:2]
                rx1, ry1, rx2, ry2 = _roi_px(W, H, cfg.roi)
            roi = frame[ry1:ry2, rx1:rx2]
            matches = _match_positions(roi, template, cfg.threshold, cfg.scales)
            if cfg.reject_deaths:
                matches = [m for m in matches if not _is_death(roi, m[1], m[2], m[3], m[4])]
            t = idx / fps
            count = len(matches)
            best = max((m[0] for m in matches), default=0.0)
            timeline.append((t, count, best))
        idx += 1
    cap.release()

    return _kills_from_timeline(timeline, cfg)


def _kills_from_timeline(timeline, cfg: DetectionConfig) -> list[KillEvent]:
    """Rising edges of the portrait count = new kills (handles multikills)."""
    kills: list[KillEvent] = []
    stable = 0
    cand = None
    cand_since = 0.0
    cand_score = 0.0

    for t, count, best in timeline:
        if count == stable:
            cand = None
            continue
        if cand != count:
            cand, cand_since, cand_score = count, t, best
        # confirm the change once it has persisted
        if t - cand_since >= cfg.persist_seconds:
            if count > stable:
                for _ in range(count - stable):
                    if not kills or cand_since - kills[-1].time >= cfg.min_gap_seconds:
                        kills.append(KillEvent(round(cand_since, 3), round(cand_score, 3), count))
            stable = count
            cand = None

    return kills
