"""Thin FFmpeg/ffprobe helpers: run filtergraphs and probe media."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def run(args: list[str], *, quiet: bool = True) -> None:
    """Run ffmpeg with the given args (``-y`` and loglevel are prepended)."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error" if quiet else "info", *args]
    subprocess.run(cmd, check=True)


def extract_frame(video: str | Path, t: float, dst: str | Path) -> Path:
    """Grab a single frame at ``t`` seconds as an image (used as the freeze)."""
    run(["-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(dst)])
    return Path(dst)


def probe_duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def probe_video(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
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
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                         capture_output=True, text=True)
    return encoder in out.stdout
