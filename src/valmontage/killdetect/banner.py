"""Find the round-end banner (FLAWLESS / CLUTCH / ACE / WON...) that pops near
the top-centre of the screen right after a round-winning kill.

The freeze-finisher uses it as the slow-mo anchor: the song's drop slams
exactly as the banner pops, which matches how the moment FEELS even when the
player never pulls the knife out after the kill.

Detection, tuned against real Medal clips: candidate pixels are whitish
(loose saturation bound -- scene glow tints the text), bright, and NEW versus
a reference frame taken just BEFORE the kill (the banner can start fading in
within 0.2s of it). The decider is then GLYPH-ROW structure: banner text is a
row of several similar-height letter blobs on one baseline. Bright skies,
smokes, flashes and walls revealed by camera pans form big irregular masses
or lone slivers -- none of them produce four aligned look-alike glyphs.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .template import _roi_px

# Upper-centre strip where the banner lives: below the score/timer HUD
# (y < ~0.08) and left of the killfeed (x > ~0.62).
BANNER_ROI = (0.22, 0.08, 0.60, 0.28)


def _glyph_row(cand: np.ndarray) -> float | None:
    """If the candidate mask contains a row of >= 4 aligned, similar-height,
    glyph-sized blobs spanning a banner-ish width, return the row's y-centre
    (else None). The y-centre lets the caller demand the row hold STILL across
    samples -- a UI banner is screen-anchored, while look-alike world rows
    (white building trim, railing-chopped sky) wander as the camera moves."""
    h, w = cand.shape
    n, _, stats, cent = cv2.connectedComponentsWithStats(cand.astype(np.uint8), 8)
    glyphs = []
    for i in range(1, n):
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if stats[i, cv2.CC_STAT_AREA] < 12:
            continue
        if not (0.04 * h <= bh <= 0.30 * h) or bw > 0.15 * w or bw / max(1, bh) > 4.0:
            continue
        # real glyphs float INSIDE the strip; sky chopped up by rooftops /
        # railings hangs from the top edge, smoke intrudes from the bottom
        y0 = stats[i, cv2.CC_STAT_TOP]
        if y0 <= 1 or y0 + bh >= h - 2:
            continue
        glyphs.append((float(cent[i][0]), float(cent[i][1]), bh,
                       stats[i, cv2.CC_STAT_LEFT], bw))
    # group by baseline (y-centre) and judge each row
    for _, gy, gh, _, _ in glyphs:
        row = [g for g in glyphs if abs(g[1] - gy) <= max(4.0, 0.05 * h)]
        if len(row) < 4:
            continue
        heights = np.array([g[2] for g in row], dtype=float)
        if heights.std() / max(1.0, heights.mean()) > 0.45:
            continue
        xs = [g[3] for g in row]
        xe = [g[3] + g[4] for g in row]
        if max(xe) - min(xs) >= 0.10 * w:
            return float(np.mean([g[1] for g in row]))
    return None


def find_round_banner(
    video_path: str | Path,
    kill: float,
    *,
    window: float = 4.0,
    roi: tuple[float, float, float, float] = BANNER_ROI,
    samples_per_sec: float = 12.0,
    ref_lead: float = 0.35,   # reference frame this long BEFORE the kill
    new_thresh: int = 25,     # value delta vs the reference = "new"
    white_sat: int = 90,      # max HSV saturation (scene glow tints the text)
    white_val: int = 150,     # min HSV value
    min_frac: float = 0.004,
    hold: float = 0.5,         # the row must persist this long, every sample...
    max_wander: float = 0.05,  # ...with its y-centre this still (frac of ROI)
) -> float | None:
    """Return the time the round banner pops, scanning from the kill to
    ``kill + window`` seconds, or None if no banner shows."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    stride = max(1, int(round(fps / samples_per_sec)))

    # clean reference from just before the kill, before any banner fade-in
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, kill - ref_lead) * 1000)
    ok, frame = cap.read()
    if not ok:
        cap.release()
        return None
    h, w = frame.shape[:2]
    box = _roi_px(w, h, roi)
    x1, y1, x2, y2 = box
    ref_v = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)[..., 2]

    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, kill) * 1000)
    times: list[float] = []
    rows: list[float | None] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t > kill + window:
            break
        if idx % stride == 0:
            hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
            s, v = hsv[..., 1], hsv[..., 2]
            cand = (s < white_sat) & (v > white_val) & (cv2.absdiff(v, ref_v) > new_thresh)
            times.append(t)
            rows.append(_glyph_row(cand) if float(cand.mean()) >= min_frac else None)
        idx += 1
    cap.release()

    # first row that holds, position-stable, in EVERY sample for >= ``hold``
    # seconds. Deliberately conservative: a missed banner just falls back to
    # the kill-anchored timing, while a false hit would mis-time the drop --
    # so this only fires on rock-steady, unmistakable banner rows.
    need = max(2, int(round(hold * samples_per_sec)))
    wander = max(3.0, max_wander * (y2 - y1))
    run: list[float] = []
    run_t: list[float] = []
    for t, ry in zip(times, rows):
        if ry is not None and (not run or abs(ry - float(np.median(run))) <= wander):
            run.append(ry)
            run_t.append(t)
            if len(run) >= need:
                return round(run_t[0], 3)
        else:
            run, run_t = ([ry], [t]) if ry is not None else ([], [])
    return None
