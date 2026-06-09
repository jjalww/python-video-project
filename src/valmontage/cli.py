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
    from .killdetect.highlight import detect_kills_by_highlight
    from .killdetect.manual import kills_from_timestamps

    video = None
    if args.manual:
        times = [float(t) for t in args.manual.split(",") if t.strip()]
        kills = kills_from_timestamps(times)
        print(f"Manual mode: {len(kills)} kill timestamps")
    elif args.method == "highlight":
        from .utils.fetch import fetch_video
        video = fetch_video(args.video)   # downloads if a URL, else passthrough
        cfg = DetectionConfig()
        if args.roi:
            cfg.roi = tuple(float(v) for v in args.roi.split(","))  # type: ignore[assignment]
        print(f"Scanning {video} for highlighted killfeed rows (no agent needed)...")
        kills = detect_kills_by_highlight(video, cfg)
        print(f"Detected {len(kills)} kills")
        for k in kills:
            print(f"  t={k.time:7.3f}s  feed_count={k.count}")
    else:
        if not args.template:
            print("error: --method template needs --template <image>", file=sys.stderr)
            return 2
        from .utils.fetch import fetch_video
        video = fetch_video(args.video)
        cfg = DetectionConfig(threshold=args.threshold)
        if args.roi:
            cfg.roi = tuple(float(v) for v in args.roi.split(","))  # type: ignore[assignment]
        print(f"Scanning {video} for {args.agent} portrait (player {args.player})...")
        kills = detect_kills(video, args.template, cfg)
        print(f"Detected {len(kills)} kills")
        for k in kills:
            print(f"  t={k.time:7.3f}s  score={k.score:.3f}  feed_count={k.count}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(
            {"player": args.player, "agent": args.agent,
             "kills": [k.__dict__ for k in kills]}, indent=2))
        print(f"  saved -> {args.out}")

    if args.debug and not args.manual and args.method == "template":
        from .killdetect.overlay import render_debug_overlay
        from .killdetect.template import DetectionConfig
        cfg = DetectionConfig(threshold=args.threshold)
        if args.roi:
            cfg.roi = tuple(float(v) for v in args.roi.split(","))  # type: ignore[assignment]
        print("Rendering debug overlay (this re-reads the video)...")
        p = render_debug_overlay(video or args.video, args.template, kills, args.debug, cfg)
        print(f"  debug overlay -> {p}")
    return 0


def _load_kill_times(path: str) -> list[float]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        return [k["time"] for k in data.get("kills", [])]
    return [float(t) for t in data]


def _cmd_render(args: argparse.Namespace) -> int:
    from .modes.beatmatch import render_beatmatch
    from .utils.fetch import fetch_audio, fetch_video

    video = fetch_video(args.video)   # downloads if a URL, else passthrough
    audio = fetch_audio(args.audio)

    if args.kills_json:
        kills = _load_kill_times(args.kills_json)
    elif args.kills:
        kills = [float(t) for t in args.kills.split(",") if t.strip()]
    else:  # fully automatic: detect the player's kills, then pick the best round
        from .killdetect.highlight import detect_kills_by_highlight
        from .editing.plan import pick_highlight
        print("No kills given -- detecting your kills automatically...")
        detected = [round(k.time, 3) for k in detect_kills_by_highlight(video)]
        if not detected:
            print("error: couldn't auto-detect kills (is 'highlight my own kills' "
                  "on?); pass --kills or --kills-json", file=sys.stderr)
            return 2
        kills = pick_highlight(detected) if args.mode == "freeze_finisher" else detected
        print(f"Detected {len(detected)} kills; using {len(kills)}.")
    print(f"Rendering {args.mode} montage from {len(kills)} kills...")

    if args.mode == "beatmatch":
        out = render_beatmatch(
            video, audio, kills, args.out,
            width=args.width, height=args.height, fps=args.fps,
            grade=args.grade, lut=args.lut, vignette=args.vignette,
            beats_per_clip=args.beats_per_clip, encoder=args.encoder,
            music_start=args.music_start, intro_dur=args.intro,
            pre_roll=args.pre_roll, finisher_factor=args.finisher_speed,
            zoom=args.zoom,
        )
    else:
        from .modes.freeze_finisher import render_freeze_finisher
        out = render_freeze_finisher(
            video, audio, kills, args.out,
            width=args.width, height=args.height, fps=args.fps,
            grade=args.grade, lut=args.lut, vignette=args.vignette,
            beats_per_clip=args.beats_per_clip, encoder=args.encoder,
            music_start=args.music_start, pre_roll=args.pre_roll,
            aftermath_dur=args.aftermath, slowmo_dur=args.slowmo_dur,
            spotlight=args.spotlight, caption=args.caption,
        )
    print(f"Done -> {out}")
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
    k.add_argument("--method", choices=["highlight", "template"], default="highlight",
                   help="highlight = killfeed colour (no agent needed); template = agent portrait")
    k.add_argument("--template", help="agent portrait template image (template method only)")
    k.add_argument("--player", default="", help="player name (for labelling)")
    k.add_argument("--agent", default="", help="agent name (for labelling)")
    k.add_argument("--threshold", type=float, default=0.62)
    k.add_argument("--roi", help="killfeed ROI as 'x1,y1,x2,y2' fractions")
    k.add_argument("--manual", help="comma-separated kill timestamps (manual fallback)")
    k.add_argument("--debug", help="write a debug overlay video to this path")
    k.add_argument("--out", help="write kill timestamps to this JSON file")
    k.set_defaults(func=_cmd_kills)

    r = sub.add_parser("render", help="render a montage from kills + song")
    r.add_argument("video", help="gameplay clip")
    r.add_argument("audio", help="song (local file)")
    r.add_argument("--mode", default="beatmatch", choices=["beatmatch", "freeze_finisher"])
    r.add_argument("--kills-json", dest="kills_json", help="kills JSON from the 'kills' command")
    r.add_argument("--kills", help="comma-separated kill timestamps (alternative to --kills-json)")
    r.add_argument("--out", default="output/montage.mp4")
    r.add_argument("--width", type=int, default=1920)
    r.add_argument("--height", type=int, default=1080)
    r.add_argument("--fps", type=float, default=60.0)
    r.add_argument("--grade", default="teal_orange")
    r.add_argument("--lut", help="path to a .cube LUT (overrides --grade)")
    r.add_argument("--vignette", action="store_true")
    r.add_argument("--zoom", action="store_true", help="enable zoom punches (off by default)")
    r.add_argument("--beats-per-clip", dest="beats_per_clip", type=int, default=None,
                   help="clip length in beats (auto from tempo if omitted)")
    r.add_argument("--encoder", default="h264_nvenc")
    r.add_argument("--music-start", dest="music_start", type=float,
                   help="override chorus auto-detection (seconds)")
    r.add_argument("--intro", type=float, default=5.0,
                   help="opening intro length in seconds (0 disables it)")
    r.add_argument("--pre-roll", dest="pre_roll", type=float, default=0.25,
                   help="start each kill clip this many seconds before the kill")
    r.add_argument("--finisher-speed", dest="finisher_speed", type=float, default=0.4,
                   help="finisher slow-mo speed (lower = slower; 0.4 = 2.5x slower)")
    r.add_argument("--aftermath", type=float, default=1.25,
                   help="freeze-finisher: seconds past the last kill the slow-mo "
                        "settles on (default lands on the knife flex)")
    r.add_argument("--slowmo-dur", dest="slowmo_dur", type=float, default=4.0,
                   help="freeze-finisher: how long the slow-motion finish lasts on screen")
    r.add_argument("--caption", default="",
                   help="freeze-finisher: optional banner over the freeze (e.g. "
                        "ACE); off by default, or 'auto' for a multikill/ace label")
    r.add_argument("--no-spotlight", dest="spotlight", action="store_false",
                   help="freeze-finisher: disable the heavy spotlight vignette")
    r.set_defaults(func=_cmd_render)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
