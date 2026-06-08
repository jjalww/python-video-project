"""Beat-match mode: cut the player's kills to the song's beat, with eased
zoom-punches, a teal-orange grade, eased crossfades, a fade-in intro, and a
slow-motion finisher that lands on a bar line so the song ends cleanly.
Renders end-to-end with FFmpeg (+ NVENC).
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
    video: str | Path,
    audio: str | Path,
    kills: list[float],
    out_path: str | Path,
    *,
    width: int = 1920, height: int = 1080, fps: float = 60.0,
    grade: str = "teal_orange", lut: str | None = None, vignette: bool = False,
    beats_per_clip: int | None = None, encoder: str = "h264_nvenc",
    music_start: float | None = None, intro_dur: float = 5.0,
    pre_roll: float = 0.25, finisher_factor: float = 0.4, zoom: bool = False,
    work_dir: str | Path = "output/_work",
) -> Path:
    video, out_path = Path(video), Path(out_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    info = ffmpeg.probe_video(video)
    video_dur = ffmpeg.probe_duration(video)

    # Kills past the end of this clip (e.g. a kills.json detected on a longer
    # clip) have no footage to show -- drop them instead of emitting a
    # negative-length segment that crashes ffmpeg.
    in_range = [k for k in kills if k < video_dur]
    if len(in_range) < len(kills):
        print(f"  note: {len(kills) - len(in_range)} kill(s) past the clip end "
              f"({video_dur:.1f}s) ignored")
    kills = in_range
    if not kills:
        raise ValueError(f"no kills fall within the {video_dur:.1f}s clip")

    beats = detect_beats(audio).beats
    if music_start is None:
        music_start = pick_montage_start(beats, energy_curve(audio))
    print(f"  music start (chorus/drop): {music_start:.2f}s")

    if beats_per_clip is None:  # auto: ~1.3s default cuts, scaled to the tempo
        import numpy as np
        b = float(np.median(np.diff(beats))) if len(beats) > 1 else 0.5
        beats_per_clip = int(max(2, min(4, round(1.3 / b))))
        print(f"  auto clip length: {beats_per_clip} beats/clip")

    plan = build_beatmatch_plan(kills, beats, music_start, video_dur,
                                beats_per_clip=beats_per_clip,
                                intro_dur=intro_dur, pre_roll=pre_roll,
                                finisher_factor=finisher_factor, zoom=zoom)
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
        ffmpeg.run(["-ss", f"{seg.source_in:.3f}", "-t", f"{seg.source_dur:.3f}",
                    "-i", str(video), "-an", "-vf", vf, "-r", f"{fps:g}",
                    *ffmpeg.video_encoder_args(encoder), str(dst)])
        seg_files.append(dst)
        tag = (" (intro, fade-in)" if seg.is_intro else
               f" (finisher, {seg.speed:.2f}x slow-mo)" if seg.is_finisher else
               f" (ramp, {seg.speed:.2f}x slow-mo)" if seg.speed != 1.0 else "")
        print(f"    seg {i}: src {seg.source_in:.2f}+{seg.source_dur:.2f}s "
              f"-> {seg.out_dur:.2f}s{tag}")

    # 2) xfade-concat the segments and lay the chorus audio under them. Fade the
    # audio out over the final slow-mo so the song settles on the bar line
    # instead of cutting -- matching the finisher's visual fade for a clean end.
    end_fade = max(0.8, plan.segments[-1].fade_out) if plan.segments else 0.8
    return compose(
        seg_files, [s.out_dur for s in plan.segments], audio, plan.music_start,
        plan.total_dur, out_path, xfade=plan.xfade, fps=fps, encoder=encoder,
        end_fade=end_fade)
