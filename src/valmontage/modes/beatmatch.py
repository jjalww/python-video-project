"""Beat-match mode: cut the player's kills to the song's beat, with eased
zoom-punches, a teal-orange grade, eased crossfades, a fade-in intro, and a
slow-motion finisher that lands on a bar line so the song ends cleanly.
Renders end-to-end with FFmpeg (+ NVENC).

Takes one clip or MANY: a beat-match wants a kill every few beats, far more
than one clip holds, so ``video`` may be a list of clips with ``kills`` a
matching list of per-clip kill timestamps. Clips play in order, except the
clip holding the biggest multikill is saved for last so the montage finishes
on the best moment instead of whatever happened to be final.
"""

from __future__ import annotations

from pathlib import Path

from ..audio.beats import detect_beats
from ..audio.energy import energy_curve, pick_montage_start
from ..editing.effects import build_segment_vf
from ..editing.plan import build_beatmatch_plan
from ..render import ffmpeg
from ..render.compose import compose


def render_beatmatch(
    video: str | Path | list[str | Path],
    audio: str | Path,
    kills: list[float] | list[list[float]],
    out_path: str | Path,
    *,
    width: int = 1920, height: int = 1080, fps: float = 60.0,
    grade: str = "teal_orange", lut: str | None = None, vignette: bool = False,
    beats_per_clip: int | None = None, encoder: str = "h264_nvenc",
    music_start: float | None = None, intro_dur: float = 5.0,
    pre_roll: float = 0.25, finisher_factor: float = 0.4, zoom: bool = False,
    work_dir: str | Path = "output/_work",
) -> Path:
    videos = [Path(v) for v in video] if isinstance(video, (list, tuple)) else [Path(video)]
    out_path = Path(out_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Normalise kills to one list per clip.
    if kills and isinstance(kills[0], (list, tuple)):
        kills_per = [sorted(float(t) for t in ks) for ks in kills]
    else:
        kills_per = [sorted(float(t) for t in kills)]
    if len(kills_per) != len(videos):
        raise ValueError(f"{len(videos)} clip(s) but {len(kills_per)} kill list(s)")

    # Kills past the end of their clip (e.g. a kills.json detected on a longer
    # clip) have no footage to show -- drop them instead of emitting a
    # negative-length segment that crashes ffmpeg. Clips left with no kills
    # are dropped entirely.
    durs = [ffmpeg.probe_duration(v) for v in videos]
    pruned: list[tuple[Path, float, list[float]]] = []
    for v, d, ks in zip(videos, durs, kills_per):
        in_range = [k for k in ks if k < d]
        if len(in_range) < len(ks):
            print(f"  note: {len(ks) - len(in_range)} kill(s) past the end of "
                  f"{v.name} ({d:.1f}s) ignored")
        if in_range:
            pruned.append((v, d, in_range))
        else:
            print(f"  note: {v.name} has no kills -- skipping that clip")
    if not pruned:
        raise ValueError("no kills fall within any clip")

    beats = detect_beats(audio).beats
    if music_start is None:
        music_start = pick_montage_start(beats, energy_curve(audio))
    print(f"  music start (chorus/drop): {music_start:.2f}s")

    if beats_per_clip is None:  # auto: ~1.3s default cuts, scaled to the tempo
        import numpy as np
        b = float(np.median(np.diff(beats))) if len(beats) > 1 else 0.5
        beats_per_clip = int(max(2, min(4, round(1.3 / b))))
        print(f"  auto clip length: {beats_per_clip} beats/clip")

    # Save the best moment for last. The finisher is always the final burst of
    # the final clip, so rank clips by their FINAL burst of near-simultaneous
    # kills -- a big multikill buried mid-clip wouldn't end the montage anyway.
    if len(pruned) > 1:
        import numpy as np
        b = float(np.median(np.diff(np.asarray(beats)))) if len(beats) > 1 else 0.5

        def final_burst(ks: list[float]) -> int:
            burst = 1
            for prev, cur in zip(reversed(ks[:-1]), reversed(ks)):
                if cur - prev > b:
                    break
                burst += 1
            return burst

        bursts = [final_burst(ks) for _, _, ks in pruned]
        star = max(range(len(pruned)), key=lambda i: (bursts[i], i))
        if star != len(pruned) - 1 and bursts[star] > 1:
            print(f"  ending on the biggest multikill ({bursts[star]} kills, "
                  f"{pruned[star][0].name})")
            pruned.append(pruned.pop(star))

    videos = [v for v, _, _ in pruned]
    durs = [d for _, d, _ in pruned]
    pairs = [(i, k) for i, (_, _, ks) in enumerate(pruned) for k in ks]
    if len(videos) > 1:
        print(f"  {len(pairs)} kills across {len(videos)} clips")

    plan = build_beatmatch_plan(pairs, beats, music_start, durs,
                                beats_per_clip=beats_per_clip,
                                intro_dur=intro_dur, pre_roll=pre_roll,
                                finisher_factor=finisher_factor, zoom=zoom,
                                fps=fps)
    if plan.music_start < music_start - 1e-3:
        print(f"  intro: {music_start - plan.music_start:.2f}s build-up "
              f"-> song now starts at {plan.music_start:.2f}s")
    print(f"  {len(plan.segments)} segments, timeline ~{plan.total_dur:.2f}s"
          f" (ends on the song at {plan.music_start + plan.total_dur:.2f}s)")

    if not ffmpeg.has_encoder(encoder):
        print(f"  {encoder} unavailable -> libx264")
        encoder = "libx264"

    # 1) render each segment to an intermediate
    seg_files: list[Path] = []
    for i, seg in enumerate(plan.segments):
        push = seg.is_finisher or seg.is_intro
        vf = build_segment_vf(seg, width, height, fps,
                              grade=grade, lut=lut, vignette=vignette,
                              zoom_kind="push" if push else "punch")
        dst = work / f"seg_{i:02d}.mp4"
        # Cut by FRAME COUNT, not by -t: Medal clips' slightly irregular frame
        # timing makes time-cut segments run 1-2 frames long, and that error
        # stacks across 30 segments into an audible off-beat drift. The input
        # window gets a little slack; -frames:v lands the exact planned length.
        nframes = int(round(seg.out_dur * fps))
        ffmpeg.run(["-ss", f"{seg.source_in:.3f}", "-t", f"{seg.source_dur + 0.1:.6f}",
                    "-i", str(videos[seg.source]), "-an", "-vf", vf, "-r", f"{fps:g}",
                    "-frames:v", str(nframes),
                    *ffmpeg.video_encoder_args(encoder), str(dst)])
        seg_files.append(dst)
        tag = (" (intro, fade-in)" if seg.is_intro else
               f" (finisher, {seg.speed:.2f}x slow-mo)" if seg.is_finisher else
               f" (ramp, {seg.speed:.2f}x slow-mo)" if seg.speed != 1.0 else "")
        clip_tag = f" [{videos[seg.source].name}]" if len(videos) > 1 else ""
        print(f"    seg {i}: src {seg.source_in:.2f}+{seg.source_dur:.2f}s "
              f"-> {seg.out_dur:.2f}s{tag}{clip_tag}")

    # 2) xfade-concat the segments and lay the chorus audio under them. Fade the
    # audio out over the final slow-mo so the song settles on the bar line
    # instead of cutting -- matching the finisher's visual fade for a clean end.
    end_fade = max(0.8, plan.segments[-1].fade_out) if plan.segments else 0.8
    return compose(
        seg_files, [s.out_dur for s in plan.segments], audio, plan.music_start,
        plan.total_dur, out_path, xfade=plan.xfade, fps=fps, encoder=encoder,
        end_fade=end_fade)
