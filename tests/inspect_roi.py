"""Calibration helper: crop a region of an image and overlay a labeled
pixel grid (in ORIGINAL image coordinates) so we can read exact
coordinates for the killfeed ROI and agent-icon template.

Usage:
    python tests/inspect_roi.py <image> <x> <y> <w> <h> [--scale N] [--step P] [--out PATH]
"""

import argparse
from pathlib import Path

import cv2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("x", type=int)
    ap.add_argument("y", type=int)
    ap.add_argument("w", type=int)
    ap.add_argument("h", type=int)
    ap.add_argument("--scale", type=int, default=8)
    ap.add_argument("--step", type=int, default=10, help="grid spacing in original px")
    ap.add_argument("--out", default="output/_frames/_roi_grid.png")
    a = ap.parse_args()

    img = cv2.imread(a.image)
    if img is None:
        raise SystemExit(f"could not read {a.image}")
    crop = img[a.y:a.y + a.h, a.x:a.x + a.w]
    big = cv2.resize(crop, (a.w * a.scale, a.h * a.scale), interpolation=cv2.INTER_NEAREST)

    # vertical lines + x labels
    for ox in range(0, a.w + 1, a.step):
        X = ox * a.scale
        cv2.line(big, (X, 0), (X, big.shape[0]), (0, 255, 255), 1)
        cv2.putText(big, str(a.x + ox), (X + 2, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1, cv2.LINE_AA)
    # horizontal lines + y labels
    for oy in range(0, a.h + 1, a.step):
        Y = oy * a.scale
        cv2.line(big, (0, Y), (big.shape[1], Y), (0, 255, 255), 1)
        cv2.putText(big, str(a.y + oy), (2, Y + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1, cv2.LINE_AA)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(a.out, big)
    print(f"wrote {a.out}  (region x={a.x} y={a.y} w={a.w} h={a.h}, scale {a.scale}x)")


if __name__ == "__main__":
    main()
