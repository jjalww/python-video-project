"""Agent-free kill detection from the killfeed -- tuned to the LOCAL player.

No agent template required. In Valorant a killfeed row is right-anchored and
reads left-to-right as [killer] [weapon] [victim]. With "highlight my own kills"
on (the default), the local player's OWN kills show their name on the killer
(left) side in a gold/yellow highlight, with the enemy victim plate in red on
the right.

We look for exactly that signature -- a gold killer plate on the left paired
with a red victim plate to its right -- and take the rising edges of how many
such rows are on screen as the player's kills (so multikills count too).

Deliberately matching the *self* gold (not team green) is what makes this
robust: teammates' kills and deaths show green/red, not gold, and green/teal
ability or map washes (e.g. Clove's ult glow, Breeze's water) have no gold
killer plate paired with a red victim -- so none of those register as kills.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from .template import DetectionConfig, KillEvent, _kills_from_timeline, _roi_px


def _slide(x: np.ndarray, k: int, op) -> np.ndarray:
    k = max(1, k)
    r = k // 2
    xp = np.pad(x, (r, r), mode="edge")
    return np.array([op(xp[i:i + k]) for i in range(len(x))])


def _clean_steps(x: np.ndarray, close_k: int, open_k: int) -> np.ndarray:
    """Turn a flickery integer count into a stable step signal.

    Morphological close (dilate then erode) bridges the brief detection
    dropouts inside a real kill; open (erode then dilate) removes brief false
    spikes. The result steps up once per real kill instead of once per flicker.
    """
    closed = _slide(_slide(x, close_k, np.max), close_k, np.min)
    opened = _slide(_slide(closed, open_k, np.min), open_k, np.max)
    return opened.astype(int)


# OpenCV HSV (H is 0-180). The local player's own kills are highlighted in
# gold/yellow on the killer (left) side; the enemy victim plate (right) is red.
# Teal/green allies are intentionally NOT matched.
_SELF_LO, _SELF_HI = (18, 90, 120), (44, 255, 255)
_RED1_LO, _RED1_HI = (0, 90, 80), (12, 255, 255)
_RED2_LO, _RED2_HI = (168, 90, 80), (180, 255, 255)
_WHITE_LO, _WHITE_HI = (0, 0, 170), (180, 70, 255)


def _masks(roi_bgr):
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    self_ = cv2.inRange(hsv, np.array(_SELF_LO), np.array(_SELF_HI))
    red = cv2.inRange(hsv, np.array(_RED1_LO), np.array(_RED1_HI)) | \
        cv2.inRange(hsv, np.array(_RED2_LO), np.array(_RED2_HI))
    white = cv2.inRange(hsv, np.array(_WHITE_LO), np.array(_WHITE_HI))
    return self_, red, white


def count_player_kill_rows(
    roi_bgr,
    *,
    min_w: float = 0.05,      # gold killer plate width (frac of ROI width)
    min_h: float = 0.04,      # ... and height range (frac of ROI height)
    max_h: float = 0.40,
    min_aspect: float = 1.8,  # nameplates are wider than tall; rejects specks
    close_w: float = 0.02,    # bridge white-text gaps inside the gold plate
    row_merge: float = 0.06,  # blob centres closer than this are one row
    min_white: float = 0.02,  # the killer name carries white text
    min_red_right: float = 0.04,  # a red victim plate must sit to the right
) -> tuple[int, float]:
    """Count the LOCAL player's own kill rows in the killfeed ROI.

    Find gold "you" killer plates (left), keep the nameplate-shaped ones with
    white name text, and require a red enemy victim plate to the right -- then
    cluster by vertical position so each row counts once.
    """
    h, w = roi_bgr.shape[:2]
    if h < 8 or w < 16:
        return 0, 0.0
    self_, red, white = _masks(roi_bgr)
    k = max(3, int(w * close_w))
    self_ = cv2.morphologyEx(self_, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    n, _, stats, _ = cv2.connectedComponentsWithStats((self_ > 0).astype(np.uint8), 8)

    centres: list[float] = []
    area = 0
    for i in range(1, n):
        x, y = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if bw < min_w * w or not (min_h * h <= bh <= max_h * h):
            continue
        if bw / max(1, bh) < min_aspect:
            continue
        # the killer plate carries white name text on/around the gold banner
        near = white[max(0, y - bh // 2):y + bh + bh // 2, x:x + bw]
        if near.size == 0 or (near > 0).mean() < min_white:
            continue
        # a real player kill pairs the gold killer (left) with a RED victim to
        # its right -- this is what rejects ult/map colour washes and deaths.
        right = red[max(0, y):y + bh, x + bw:w]
        if right.size == 0 or (right > 0).mean() < min_red_right:
            continue
        centres.append(y + bh / 2)
        area += int(stats[i, cv2.CC_STAT_AREA])
    if not centres:
        return 0, 0.0

    centres.sort()
    merge = max(4.0, row_merge * h)
    rows = 1 + sum((b - a) > merge for a, b in zip(centres, centres[1:]))
    return rows, round(area / (w * h), 4)


# The killfeed sits in the top strip; keep the ROI shallow so the netgraph
# overlay (which lives just below the feed) stays out of the detector.
HIGHLIGHT_ROI = (0.60, 0.0, 1.0, 0.20)


def detect_kills_by_highlight(
    video_path: str | Path,
    cfg: DetectionConfig | None = None,
    roi: tuple[float, float, float, float] = HIGHLIGHT_ROI,
) -> list[KillEvent]:
    cfg = cfg or DetectionConfig()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0

    box = None
    times: list[float] = []
    counts: list[int] = []
    scores: list[float] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % cfg.sample_stride == 0:
            if box is None:
                h, w = frame.shape[:2]
                box = _roi_px(w, h, roi)
            x1, y1, x2, y2 = box
            count, score = count_player_kill_rows(frame[y1:y2, x1:x2])
            times.append(idx / fps)
            counts.append(count)
            scores.append(score)
        idx += 1
    cap.release()
    if len(counts) < 2:  # need >=2 samples to smooth + measure dt below
        return []

    # The raw per-frame row count flickers badly (detection drops in/out between
    # frames). Clean it into a stable step signal, then take rising edges -- so
    # one kill counts once, not once per flicker.
    dt = (times[-1] - times[0]) / max(1, len(times) - 1)
    smooth = _clean_steps(np.asarray(counts, dtype=int),
                          close_k=max(3, int(round(0.6 / dt))),
                          open_k=max(3, int(round(0.5 / dt))))
    timeline = list(zip(times, smooth.tolist(), scores))
    # Keep the debounce small: the rising edges of a multikill land only a few
    # tenths of a second apart, so a large floor would merge a double/triple into
    # one. Flicker is already handled by _clean_steps, not this gap.
    tl_cfg = replace(cfg, min_gap_seconds=max(cfg.min_gap_seconds, 0.25))
    return _kills_from_timeline(timeline, tl_cfg)
