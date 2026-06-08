"""Agent-free kill detection from the killfeed *highlight*.

No agent template required. In Valorant a kill row in the top-right killfeed
is right-anchored and shows the killer's nameplate in the player's team colour
(green) on the LEFT and the victim's nameplate in red on the RIGHT. A row with
green-on-the-left and red-on-the-right is a kill by the player's team.

We count how many such rows are on screen each frame and take the *rising
edges* of that count as new kills (so multikills are captured too) -- the same
timeline logic the template detector uses, but driven by colour instead of a
portrait match. Deaths are naturally ignored: when the player dies their row is
red-on-the-left, which fails the green-left test.
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

# OpenCV HSV (H is 0-180). Ally/killer nameplate green, enemy/victim red.
_GREEN_LO, _GREEN_HI = (35, 70, 70), (90, 255, 255)
_RED1_LO, _RED1_HI = (0, 90, 80), (10, 255, 255)
_RED2_LO, _RED2_HI = (170, 90, 80), (180, 255, 255)


_WHITE_LO, _WHITE_HI = (0, 0, 170), (180, 70, 255)


def _masks(roi_bgr):
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array(_GREEN_LO), np.array(_GREEN_HI))
    red = cv2.inRange(hsv, np.array(_RED1_LO), np.array(_RED1_HI)) | \
        cv2.inRange(hsv, np.array(_RED2_LO), np.array(_RED2_HI))
    white = cv2.inRange(hsv, np.array(_WHITE_LO), np.array(_WHITE_HI))
    return green, red, white


def count_killfeed_rows(
    roi_bgr,
    *,
    min_w: float = 0.10,     # nameplate blob must be this wide (frac of ROI width)
    min_h: float = 0.05,     # ... and within this height range (frac of ROI height)
    max_h: float = 0.45,
    min_aspect: float = 3.0,  # nameplates are long, thin bars; rejects portraits & netgraph
    close_w: float = 0.02,   # bridge white-text gaps inside a nameplate
    row_merge: float = 0.06,  # blob centres closer than this count as one row
    min_white: float = 0.03,  # nameplate carries white name text; netgraph/scenery don't
) -> tuple[int, float]:
    """Count the player's own kill rows visible in the killfeed ROI.

    The signal is the killer nameplate in the team colour (green) on the left
    of a row. We find green blobs, keep the nameplate-shaped ones (wide, not
    square, plausible height, with white name text inside), and cluster them by
    vertical position so the killer + a green victim on the same row collapse to
    a single kill. Deaths show red on the left, so they're excluded; the green
    netgraph waveform and scenery have no white text, so they're rejected too.
    """
    h, w = roi_bgr.shape[:2]
    if h < 8 or w < 16:
        return 0, 0.0
    green, _, white = _masks(roi_bgr)
    k = max(3, int(w * close_w))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    n, _, stats, _ = cv2.connectedComponentsWithStats((green > 0).astype(np.uint8), 8)

    centres: list[float] = []
    area = 0
    for i in range(1, n):
        x, y = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if bw < min_w * w or not (min_h * h <= bh <= max_h * h):
            continue
        if bw / max(1, bh) < min_aspect:
            continue
        # a nameplate has white name text on/around the green banner
        near = white[max(0, y - bh // 2):y + bh + bh // 2, x:x + bw]
        if near.size == 0 or (near > 0).mean() < min_white:
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
            count, score = count_killfeed_rows(frame[y1:y2, x1:x2])
            times.append(idx / fps)
            counts.append(count)
            scores.append(score)
        idx += 1
    cap.release()
    if not counts:
        return []

    # The raw per-frame row count flickers badly (detection drops in/out between
    # frames). Clean it into a stable step signal, then take rising edges -- so
    # one kill counts once, not once per flicker.
    dt = (times[-1] - times[0]) / max(1, len(times) - 1)
    smooth = _clean_steps(np.asarray(counts, dtype=int),
                          close_k=max(3, int(round(0.6 / dt))),
                          open_k=max(3, int(round(0.5 / dt))))
    timeline = list(zip(times, smooth.tolist(), scores))
    tl_cfg = replace(cfg, min_gap_seconds=max(cfg.min_gap_seconds, 0.7))
    return _kills_from_timeline(timeline, tl_cfg)
