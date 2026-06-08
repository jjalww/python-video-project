"""Build per-segment FFmpeg filter chains: fill-to-canvas, eased zoom,
colour grade / LUT, optional vignette, and (for the finisher) smooth
slow-motion via minterpolate + fade-out.

Expressions are single-quoted so commas inside them are not mistaken for
filter separators.
"""

from __future__ import annotations

from .plan import Segment

GRADES = {
    "teal_orange": "eq=contrast=1.06:saturation=1.18:gamma=0.98,"
                   "colorbalance=rs=-0.06:bs=0.06:rh=0.10:bh=-0.07",
    "contrast_boost": "eq=contrast=1.15:saturation=1.25:brightness=0.02",
    "vignette_only": "vignette=PI/5",
    "none": "null",
}


def _lut_path(path: str) -> str:
    # FFmpeg filter args need ':' and '\' escaped on Windows paths.
    p = path.replace("\\", "/")
    return p.replace(":", "\\:")


def _zoom_filter(seg: Segment, width: int, height: int, kind: str = "punch") -> str:
    """Smooth eased zoom via per-frame scale + centre crop (constant output
    size). zoompan is avoided: it OOMs on some FFmpeg builds.

    Zoom factor Z(t) >= 1; the frame is scaled up by Z then centre-cropped
    back to WxH, so a larger Z = more zoomed in.
    """
    a = seg.zoom_amount
    if kind == "push":  # ease-in push from 1.0 -> 1+a over the clip
        z = f"1+{a}*(1-pow(1-min(t/{max(0.1, seg.out_dur):.3f},1),3))"
    else:               # punch: spike to 1+a on the beat, ease back to 1.0
        z = f"1+{a}*(1-pow(min(t/0.45,1),3))"
    return (f"scale='ceil(iw*({z})/2)*2':'ceil(ih*({z})/2)*2':eval=frame,"
            f"crop={width}:{height}")


def build_segment_vf(
    seg: Segment, width: int, height: int, fps: float,
    *, grade: str = "teal_orange", lut: str | None = None,
    vignette: bool = False, zoom_kind: str = "punch",
) -> str:
    parts: list[str] = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        "setsar=1",
    ]

    # slow-motion (finisher): retime, then interpolate to smooth frames
    if seg.speed != 1.0:
        parts.append(f"setpts={1/seg.speed:.4f}*PTS")
        parts.append(f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir")

    if seg.zoom_amount and seg.zoom_amount > 0:
        parts.append(_zoom_filter(seg, width, height, zoom_kind))

    if lut:
        parts.append(f"lut3d=file='{_lut_path(lut)}'")
    elif grade in GRADES:
        parts.append(GRADES[grade])
    if vignette and grade != "vignette_only":
        parts.append("vignette=PI/6")

    if seg.fade_in > 0:
        parts.append(f"fade=t=in:st=0:d={seg.fade_in:.3f}")
    if seg.fade_out > 0:
        st = max(0.0, seg.out_dur - seg.fade_out)
        parts.append(f"fade=t=out:st={st:.3f}:d={seg.fade_out:.3f}")

    parts.append(f"fps={fps}")
    return ",".join(parts)


def build_freeze_vf(
    width: int, height: int, fps: float, freeze_dur: float,
    *, grade: str = "teal_orange", lut: str | None = None,
    vignette: bool = True, zoom_amount: float = 0.22,
    flash: float = 0.10, fade_out: float = 1.0,
) -> str:
    """Filter chain for the freeze-finisher climax: a single held frame that
    punches in, flashes white on the hit, takes an intensified grade, then
    fades to black as the song settles. Fed a looped still image, so ``t`` runs
    0..freeze_dur across the hold.
    """
    parts: list[str] = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        "setsar=1",
    ]
    # eased full-screen push into the kill over the whole hold
    if zoom_amount > 0:
        z = f"1+{zoom_amount}*(1-pow(1-min(t/{max(0.1, freeze_dur):.3f},1),3))"
        parts.append(f"scale='ceil(iw*({z})/2)*2':'ceil(ih*({z})/2)*2':eval=frame,"
                     f"crop={width}:{height}")
    # grade, then an extra pop so the climax reads stronger than the body
    if lut:
        parts.append(f"lut3d=file='{_lut_path(lut)}'")
    elif grade in GRADES:
        parts.append(GRADES[grade])
    parts.append("eq=contrast=1.08:saturation=1.12")
    if vignette and grade != "vignette_only":
        parts.append("vignette=PI/5")
    # white flash on the freeze hit, then settle into the held frame
    if flash > 0:
        parts.append(f"fade=t=in:color=white:st=0:d={flash:.3f}")
    if fade_out > 0:
        st = max(0.0, freeze_dur - fade_out)
        parts.append(f"fade=t=out:st={st:.3f}:d={fade_out:.3f}")
    parts.append(f"fps={fps}")
    return ",".join(parts)
