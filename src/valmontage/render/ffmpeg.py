"""Thin FFmpeg/ffprobe helpers: run filtergraphs and probe media."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


_FFMPEG_MISSING = ("FFmpeg isn't installed on this PC. Double-click "
                   "'Setup (run once).bat' (or run: winget install Gyan.FFmpeg), "
                   "then reopen the app.")


def run(args: list[str], *, quiet: bool = True) -> None:
    """Run ffmpeg with the given args (``-y`` and loglevel are prepended).

    Failures raise a RuntimeError carrying ffmpeg's own error text (last few
    stderr lines) so the GUI/CLI can show the actual reason, not just the
    command line.
    """
    cmd = ["ffmpeg", "-y", "-loglevel", "error" if quiet else "info", *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(_FFMPEG_MISSING) from None
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-8:])
        raise RuntimeError(f"FFmpeg failed:\n{tail or '(no error text)'}")


def extract_frame(video: str | Path, t: float, dst: str | Path) -> Path:
    """Grab a single frame at ``t`` seconds as an image (used as the freeze)."""
    run(["-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(dst)])
    return Path(dst)


def probe_duration(path: str | Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(_FFMPEG_MISSING) from None
    return float(out.stdout.strip())


def probe_video(path: str | Path) -> dict:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,duration",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(_FFMPEG_MISSING) from None
    s = json.loads(out.stdout)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"width": int(s["width"]), "height": int(s["height"]),
            "fps": float(num) / float(den)}


def video_encoder_args(encoder: str = "h264_nvenc") -> list[str]:
    """Encoder args; NVENC for speed on the RTX 4060, libx264 fallback."""
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p"]


def has_encoder(encoder: str) -> bool:
    """True if ffmpeg can actually encode with it. A listing check isn't
    enough: standard builds list h264_nvenc even on PCs with no NVIDIA GPU,
    so do a tiny real test encode. (NVENC rejects very small frames, hence
    256x256.)"""
    try:
        p = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "color=size=256x256:rate=30:duration=0.1",
             "-frames:v", "3", "-c:v", encoder, "-f", "null", "-"],
            capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return p.returncode == 0
