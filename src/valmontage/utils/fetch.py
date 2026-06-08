"""Resolve inputs that may be local paths or URLs.

URLs are downloaded with yt-dlp into a per-URL cache file (named by a hash of
the URL), so:
  * a new link never silently reuses an old download (the previous bug where a
    YouTube link still played the old samples/song.wav), and
  * the same link is fetched once and reused.

Cookie-walled sites (Douyin/TikTok) are retried with browser cookies, and if
that can't be read a clear, actionable error is raised instead of a stale file.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

CACHE_DIR = Path("samples") / "_downloads"
_COOKIE_BROWSERS = ("firefox", "chrome", "edge")


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _needs_cookies_site(url: str) -> bool:
    return any(s in url for s in ("douyin.com", "tiktok.com"))


def _run(cmd: list[str]) -> tuple[int, str]:
    """Run yt-dlp, echo its output (so the app log shows it), return (rc, out)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if out.strip():
        print(out.strip())
    return p.returncode, out


def _download(source: str, out_template: str, fmt_args: list[str]) -> None:
    base = [sys.executable, "-m", "yt_dlp", "--no-progress", *fmt_args, "-o", out_template]
    rc, out = _run([*base, source])
    if rc == 0:
        return
    # Looks like a login/cookie wall -> retry with cookies from each browser.
    if "cookie" in out.lower() or _needs_cookies_site(source):
        for br in _COOKIE_BROWSERS:
            print(f"  retrying with {br} cookies...")
            rc, _ = _run([*base, "--cookies-from-browser", br, source])
            if rc == 0:
                return
        raise RuntimeError(
            "This link needs your browser login (cookies) to download, and that "
            "could not be read automatically -- Douyin/TikTok links usually do. "
            "Use a YouTube link instead, or download the file yourself and pick it "
            "with Browse.")
    raise RuntimeError(f"Download failed (yt-dlp exit {rc}). See the log above for why.")


def fetch_audio(source: str, dest_dir: str | Path = CACHE_DIR) -> Path:
    """Return a local audio path; download (and cache) the URL as wav if needed."""
    if not is_url(source):
        p = Path(source)
        if not p.exists():
            raise FileNotFoundError(f"Audio file not found: {p}")
        return p

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    wav = dest / f"song_{_key(source)}.wav"
    if wav.exists() and wav.stat().st_size > 0:
        print(f"  using cached audio: {wav.name}")
        return wav
    _download(source, str(dest / f"song_{_key(source)}.%(ext)s"),
              ["-x", "--audio-format", "wav", "--audio-quality", "0"])
    if not wav.exists():
        raise RuntimeError("yt-dlp ran but produced no audio file.")
    return wav


def fetch_video(source: str, dest_dir: str | Path = CACHE_DIR) -> Path:
    """Return a local video path; download (and cache) the URL as mp4 if needed."""
    if not is_url(source):
        p = Path(source)
        if not p.exists():
            raise FileNotFoundError(f"Video file not found: {p}")
        return p

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    key = _key(source)

    def _produced() -> list[Path]:
        # yt-dlp emits .mp4 when it merges video+audio, but the source's native
        # container (.webm/.mkv) when it falls back to one progressive stream.
        # Accept any of them (but not a half-written .part) so a finished
        # download is reused instead of re-fetched every run.
        return [p for p in sorted(dest.glob(f"clip_{key}.*"))
                if p.suffix not in (".part", ".ytdl") and p.stat().st_size > 0]

    cached = _produced()
    if cached:
        print(f"  using cached video: {cached[0].name}")
        return cached[0]
    _download(source, str(dest / f"clip_{key}.%(ext)s"),
              ["-f", "bv*+ba/b", "--merge-output-format", "mp4"])
    produced = _produced()
    if produced:
        return produced[0]
    raise RuntimeError("yt-dlp ran but produced no video file.")
