"""Freeze-finisher mode: the kill clips play through, then the montage freezes
on the key (final) kill exactly as the song's drop hits -- a full-screen punch,
a white flash, an intensified grade -- and holds before fading to black.

Where beat-match ends in slow motion, this ends on a held frame: the lead-up
kills play live and cut on the build-up, then the climax kill plays through and
stops dead on the drop. The song is started early enough that its drop lands on
that freeze. Renders end-to-end with FFmpeg (+ NVENC).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..audio.beats import detect_beats
from ..audio.energy import energy_curve
from ..editing.effects import build_freeze_vf, build_segment_vf
from ..editing.plan import Segment
from ..render import ffmpeg
from ..render.compose import compose


def render_freeze_finisher(
    video: str | Path,
    audio: str | Path,
    kills: list[float],
    out_path: str | Path,
    *,
    width: int = 1920, height: int = 1080, fps: float = 60.0,
    grade: str = "teal_orange", lut: str | None = None, vignette: bool = True,
    beats_per_clip: int | None = None, encoder: str = "h264_nvenc",
    music_start: float | None = None, pre_roll: float = 0.25,
    kill_offset: float = -0.30, freeze_lead: float = 0.25,
    freeze_dur: float = 2.5, freeze_zoom: float = 0.22, flash: float = 0.10,
    freeze_fade: float = 1.0, xfade: float = 0.22,
    work_dir: str | Path = "output/_work",
) -> Path:
    video, out_path = Path(video), Path(out_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    video_dur = ffmpeg.probe_duration(video)

    # Drop kills past the end of this clip -- their footage doesn't exist.
    in_range = [k for k in kills if k < video_dur]
    if len(in_range) < len(kills):
        print(f"  note: {len(kills) - len(in_range)} kill(s) past the clip end "
              f"({video_dur:.1f}s) ignored")
    kills = sorted(in_range)
    if not kills:
        raise ValueError(f"no kills fall within the {video_dur:.1f}s clip")

    beats = detect_beats(audio).beats
    barr = np.asarray(beats)
    beat = float(np.median(np.diff(barr))) if len(barr) > 1 else 0.5

    drop = music_start if music_start is not None else energy_curve(audio).peak_time
    if len(barr):  # snap the drop to the nearest beat so the freeze hits clean
        drop = float(barr[int(np.argmin(np.abs(barr - drop)))])
    print(f"  drop (freeze target): {drop:.2f}s")

    if beats_per_clip is None:
        beats_per_clip = int(max(2, min(4, round(1.3 / beat))))

    # Merge near-simultaneous kills into one shot (same logic as beat-match).
    clusters: list[list[float]] = []
    for k in kills:
        if clusters and k - clusters[-1][-1] <= beat:
            clusters[-1].append(k)
        else:
            clusters.append([k])
    *leadups, climax = clusters  # the final cluster is the freeze; rest lead up

    # Lead-up clips: each plays live for ~beats_per_clip beats, capped to the
    # room before the next kill so footage is never shown twice. Zoom stays off
    # (clean cuts) -- the drama is saved for the freeze.
    segments: list[Segment] = []
    for ci, cl in enumerate(leadups):
        src_in = max(0.0, cl[0] + kill_offset - pre_roll)
        nxt_in = max(0.0, clusters[ci + 1][0] + kill_offset - pre_roll)
        avail = max(0.0, nxt_in - src_in)
        want = beats_per_clip * beat
        if len(cl) > 1:  # a merged multi-kill needs room for the whole burst
            want = max(want, (cl[-1] - cl[0]) + pre_roll + 0.45)
        dur = min(want, avail) if avail > 0 else want
        dur = max(0.4, dur)
        segments.append(Segment(round(src_in, 3), round(dur, 3), round(dur, 3),
                                zoom_amount=0.0))

    # Climax play-through: from its pre-roll up to the freeze frame (the kill).
    climax_in = max(0.0, climax[0] + kill_offset - pre_roll)
    freeze_at = min(video_dur - 1.0 / fps, climax[-1] + kill_offset + freeze_lead)
    play_dur = max(0.4, freeze_at - climax_in)
    segments.append(Segment(round(climax_in, 3), round(play_dur, 3),
                            round(play_dur, 3), zoom_amount=0.0))

    if not ffmpeg.has_encoder(encoder):
        print(f"  {encoder} unavailable -> libx264")
        encoder = "libx264"

    # 1) render the lead-up + climax play-through clips
    seg_files: list[Path] = []
    for i, seg in enumerate(segments):
        vf = build_segment_vf(seg, width, height, fps, grade=grade, lut=lut,
                              vignette=vignette, zoom_kind="punch")
        dst = work / f"fz_{i:02d}.mp4"
        ffmpeg.run(["-ss", f"{seg.source_in:.3f}", "-t", f"{seg.source_dur:.3f}",
                    "-i", str(video), "-an", "-vf", vf, "-r", f"{fps:g}",
                    *ffmpeg.video_encoder_args(encoder), str(dst)])
        seg_files.append(dst)
        print(f"    clip {i}: src {seg.source_in:.2f}+{seg.source_dur:.2f}s")

    # 2) the freeze: grab the kill frame, then hold it with punch + flash + fade
    frame_png = work / "freeze.png"
    ffmpeg.extract_frame(video, freeze_at, frame_png)
    fz_vf = build_freeze_vf(width, height, fps, freeze_dur, grade=grade, lut=lut,
                            vignette=vignette, zoom_amount=freeze_zoom,
                            flash=flash, fade_out=freeze_fade)
    fz_dst = work / f"fz_{len(segments):02d}.mp4"
    ffmpeg.run(["-loop", "1", "-t", f"{freeze_dur:.3f}", "-i", str(frame_png),
                "-vf", fz_vf, "-r", f"{fps:g}",
                *ffmpeg.video_encoder_args(encoder), str(fz_dst)])
    seg_files.append(fz_dst)
    print(f"    freeze: frame @ {freeze_at:.2f}s held {freeze_dur:.1f}s")

    # 3) start the song so its drop lands on the freeze, then concat + grade.
    out_durs = [s.out_dur for s in segments] + [freeze_dur]
    total = sum(out_durs) - xfade * (len(out_durs) - 1)
    freeze_start = total - freeze_dur            # where the held frame begins
    audio_start = max(0.0, drop - freeze_start)
    if drop >= freeze_start:
        print(f"  {len(out_durs)} clips, timeline ~{total:.2f}s, "
              f"song from {audio_start:.2f}s (drop lands at the freeze)")
    else:
        # The drop is earlier in the song than the build-up is long, so it can't
        # be pulled forward to the freeze -- say so rather than imply it aligned.
        print(f"  {len(out_durs)} clips, timeline ~{total:.2f}s, song from 0.00s "
              f"(note: drop at {drop:.2f}s is earlier than the freeze point "
              f"{freeze_start:.2f}s -- alignment approximate)")

    return compose(seg_files, out_durs, audio, audio_start, total, out_path,
                   xfade=xfade, fps=fps, encoder=encoder, end_fade=freeze_fade)
