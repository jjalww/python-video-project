"""Build per-segment FFmpeg filter chains: fill-to-canvas, eased zoom,
colour grade / LUT, optional vignette, and (for the finisher) smooth
slow-motion via minterpolate + fade-out.

Expressions are single-quoted so commas inside them are not mistaken for
filter separators.
"""

from __future__ import annotations

import os

from .plan import Segment

GRADES = {
    # Kept deliberately subtle -- a light warm/cool push, not a colour wash. A
    # heavy grade reads as "over-filtered" and muddies already-saturated maps.
    "teal_orange": "eq=contrast=1.03:saturation=1.06:gamma=0.99,"
                   "colorbalance=rs=-0.03:bs=0.03:rh=0.05:bh=-0.03",
    "contrast_boost": "eq=contrast=1.08:saturation=1.10:brightness=0.01",
    "vignette_only": "vignette=PI/6",
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


def _default_badge_font() -> str:
    """First bold font that exists, so the banner works on Windows AND on a
    Linux server (the web app). Falls back to the Windows path; if nothing is
    found, _badge_filter just skips the banner rather than failing."""
    for c in (r"C:\Windows\Fonts\ariblk.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        if os.path.isfile(c):
            return c
    return r"C:\Windows\Fonts\ariblk.ttf"


DEFAULT_BADGE_FONT = _default_badge_font()  # bold banner font, cross-platform


def _badge_filter(text: str, font: str, height: int) -> str | None:
    """A centred bold banner over the freeze (e.g. 'ACE' / 'TRIPLE KILL'), like
    the reference edit's achievement callout. Returns None if there's no usable
    text. Only alnum/space/-/! survive so the drawtext string never needs
    escaping; the font path is escaped the same way LUT paths are.
    """
    safe = "".join(c for c in text.upper() if c.isalnum() or c in " -!").strip()
    if not safe or not os.path.isfile(font):  # no text, or font missing -> skip
        return None
    f = font.replace("\\", "/").replace(":", "\\:")
    fs = max(20, int(height * 0.06))
    return (f"drawtext=fontfile='{f}':text='{safe}':fontcolor=white:fontsize={fs}:"
            f"box=1:boxcolor=black@0.45:boxborderw={int(fs * 0.55)}:"
            f"x=(w-text_w)/2:y={int(height * 0.11)}")


def build_slowmo_vf(
    width: int, height: int, fps: float, ramp_src: float, slowmo_dur: float,
    *, grade: str = "teal_orange", lut: str | None = None,
    vignette: bool = False, spotlight: bool = True, fade_out: float = 1.2,
    caption: str = "", caption_font: str = DEFAULT_BADGE_FONT,
) -> str:
    """Filter chain for the slow-motion finisher: a source window of
    ``ramp_src`` seconds eased from 1x (a seamless hard cut from the preceding
    normal-speed shot) down into super-slow, near-frozen motion over
    ``slowmo_dur`` on-screen seconds, smoothed with minterpolate. Plus the
    spotlight vignette (eased in, so nothing pops at the cut), an optional
    banner, and a fade-out.

    The ramp is a hyperbolic ``setpts`` -- on-screen speed is 1/(1+a*T)^2 at T
    seconds into the slow-mo -- so it *starts at 1x* (invisible join) and
    decelerates smoothly the whole way down to (ramp_src/slowmo_dur)^2 by the
    end, with no sudden knee. The map only reaches ``slowmo_dur`` in the limit,
    so the last (near-frozen) frame is clone-padded; render with an output-side
    ``-t slowmo_dur`` to trim exactly.
    """
    ramp_src = max(0.05, min(ramp_src, slowmo_dur * 0.4))
    a = (slowmo_dur - ramp_src) / (slowmo_dur * ramp_src)   # deceleration coeff
    parts: list[str] = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        "setsar=1",
        # hyperbolic ease: output_secs = t/(1 - a*t) (t = secs into the window)
        f"setpts='((PTS-STARTPTS)*TB)/(1-{a:.6f}*(PTS-STARTPTS)*TB)/TB'",
        f"minterpolate=fps={fps:g}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir",
        "tpad=stop_mode=clone:stop_duration=4",
    ]
    if lut:
        parts.append(f"lut3d=file='{_lut_path(lut)}'")
    elif grade in GRADES:
        parts.append(GRADES[grade])
    if spotlight:   # ease the spotlight in over the first second of slow-mo
        base = "PI/6" if vignette else "0"
        parts.append(f"vignette=angle='{base}+(PI/4.2-{base})*min(t,1)':eval=frame")
    elif vignette and grade != "vignette_only":
        parts.append("vignette=PI/6")
    badge = _badge_filter(caption, caption_font, height) if caption else None
    if badge:
        parts.append(badge)
    if fade_out > 0:
        parts.append(f"fade=t=out:st={max(0.0, slowmo_dur - fade_out):.3f}:"
                     f"d={fade_out:.3f}")
    parts.append(f"fps={fps:g}")
    return ",".join(parts)
