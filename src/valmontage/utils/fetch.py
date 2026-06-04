"""Helpers for resolving inputs that may be local paths or URLs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def fetch_audio(source: str, dest_dir: str | Path = "samples") -> Path:
    """Return a local audio path.

    If ``source`` is a local file, it's returned as-is. If it's a URL,
    the best audio stream is downloaded with yt-dlp into ``dest_dir`` as
    a wav (for clean, lossless beat analysis).
    """
    if not is_url(source):
        p = Path(source)
        if not p.exists():
            raise FileNotFoundError(f"Audio file not found: {p}")
        return p

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(dest_dir / "song.%(ext)s")
    # Requires ffmpeg on PATH (we install it via winget).
    subprocess.run(
        [
            sys.executable, "-m", "yt_dlp",
            "-x",
            "--audio-format", "wav",
            "--audio-quality", "0",
            "-o", out_template,
            source,
        ],
        check=True,
    )
    wav = dest_dir / "song.wav"
    if not wav.exists():
        raise RuntimeError("yt-dlp did not produce the expected song.wav")
    return wav
