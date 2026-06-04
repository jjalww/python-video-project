"""Command-line entrypoint for valmontage.

Phase 1 exposes the `beats` command:

    python -m valmontage beats samples/song.wav
    python -m valmontage beats "https://youtu.be/..." --out output/beats.json

Later phases add `kills`, `render`, etc.
"""

from __future__ import annotations

import argparse
import sys

from .audio.beats import detect_beats
from .utils.fetch import fetch_audio


def _cmd_beats(args: argparse.Namespace) -> int:
    audio_path = fetch_audio(args.source)
    print(f"Analyzing: {audio_path}")
    result = detect_beats(
        audio_path,
        hop_length=args.hop_length,
        tightness=args.tightness,
    )

    print(f"  duration : {result.duration:.2f} s")
    print(f"  tempo    : {result.bpm:.2f} BPM")
    print(f"  beats    : {result.n_beats}")
    print(f"  onsets   : {len(result.onsets)}")
    preview = ", ".join(f"{t:.2f}" for t in result.beats[:8])
    print(f"  first beats: {preview}{' ...' if result.n_beats > 8 else ''}")

    if args.out:
        path = result.save_json(args.out)
        print(f"  saved -> {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="valmontage")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("beats", help="detect tempo and beat timestamps in a song")
    b.add_argument("source", help="local audio path or a URL (yt-dlp)")
    b.add_argument("--out", help="write full result to this JSON file")
    b.add_argument("--hop-length", type=int, default=512, dest="hop_length")
    b.add_argument("--tightness", type=float, default=100.0)
    b.set_defaults(func=_cmd_beats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
