"""Command-line entrypoint for valmontage.

Phase 1 exposes the `beats` command:

    python -m valmontage beats samples/song.wav
    python -m valmontage beats "https://youtu.be/..." --out output/beats.json

Later phases add `kills`, `render`, etc.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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


def _cmd_kills(args: argparse.Namespace) -> int:
    from .killdetect.template import DetectionConfig, detect_kills
    from .killdetect.manual import kills_from_timestamps

    if args.manual:
        times = [float(t) for t in args.manual.split(",") if t.strip()]
        kills = kills_from_timestamps(times)
        print(f"Manual mode: {len(kills)} kill timestamps")
    else:
        cfg = DetectionConfig(threshold=args.threshold)
        if args.roi:
            cfg.roi = tuple(float(v) for v in args.roi.split(","))  # type: ignore[assignment]
        print(f"Scanning {args.video} for {args.agent} portrait (player {args.player})...")
        kills = detect_kills(args.video, args.template, cfg)
        print(f"Detected {len(kills)} kills")
        for k in kills:
            print(f"  t={k.time:7.3f}s  score={k.score:.3f}  feed_count={k.count}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(
            {"player": args.player, "agent": args.agent,
             "kills": [k.__dict__ for k in kills]}, indent=2))
        print(f"  saved -> {args.out}")

    if args.debug and not args.manual:
        from .killdetect.overlay import render_debug_overlay
        from .killdetect.template import DetectionConfig
        cfg = DetectionConfig(threshold=args.threshold)
        if args.roi:
            cfg.roi = tuple(float(v) for v in args.roi.split(","))  # type: ignore[assignment]
        print("Rendering debug overlay (this re-reads the video)...")
        p = render_debug_overlay(args.video, args.template, kills, args.debug, cfg)
        print(f"  debug overlay -> {p}")
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

    k = sub.add_parser("kills", help="detect the player's kills in a clip")
    k.add_argument("video", help="path to the gameplay clip")
    k.add_argument("--template", help="agent portrait template image (template mode)")
    k.add_argument("--player", default="", help="player name (for labelling)")
    k.add_argument("--agent", default="", help="agent name (for labelling)")
    k.add_argument("--threshold", type=float, default=0.62)
    k.add_argument("--roi", help="killfeed ROI as 'x1,y1,x2,y2' fractions")
    k.add_argument("--manual", help="comma-separated kill timestamps (manual fallback)")
    k.add_argument("--debug", help="write a debug overlay video to this path")
    k.add_argument("--out", help="write kill timestamps to this JSON file")
    k.set_defaults(func=_cmd_kills)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
