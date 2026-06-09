"""Freeze-finisher mode: play the clutch round straight through as ONE
continuous shot -- no jump cuts -- then keep rolling a moment past the last kill
and freeze the final frame while the song fades out, with a spotlight vignette
and an optional banner.

This is modelled on hand-made clutch edits: a single clean continuous clip with
a held finish, NOT a montage stitched from scattered moments. Feed it roughly one
round / one clutch and it reads like that reference; feed it a whole game and
it'll just play the long span continuously (with a warning).

Renders end-to-end with FFmpeg (+ NVENC).
"""

from __future__ import annotations

from pathlib import Path

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
    grade: str = "teal_orange", lut: str | None = None, vignette: bool = False,
    encoder: str = "h264_nvenc", music_start: float | None = None,
    kill_offset: float = -0.30, lead_in: float = 4.0, aftermath_dur: float = 1.25,
    freeze_dur: float = 3.0, freeze_zoom: float = 0.0, flash: float = 0.1,
    freeze_fade: float = 1.2, xfade: float = 0.25,
    spotlight: bool = True, caption: str = "",
    work_dir: str | Path = "output/_work",
    # accepted for CLI/GUI compatibility; not used by the continuous edit:
    beats_per_clip: int | None = None, pre_roll: float = 0.25,
) -> Path:
    video, out_path = Path(video), Path(out_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    video_dur = ffmpeg.probe_duration(video)
    song_dur = ffmpeg.probe_duration(audio)

    in_range = [k for k in kills if k < video_dur]
    if len(in_range) < len(kills):
        print(f"  note: {len(kills) - len(in_range)} kill(s) past the clip end "
              f"({video_dur:.1f}s) ignored")
    kills = sorted(in_range)
    if not kills:
        raise ValueError(f"no kills fall within the {video_dur:.1f}s clip")

    # The song's peak (its drop). We line this up to land ON the freeze.
    peak = music_start if music_start is not None else energy_curve(audio).peak_time

    # One continuous window: a run-up before the first kill, through every kill,
    # then ~aftermath_dur past the last kill (lands on the knife flex / reaction),
    # which is the frame we freeze on.
    first, last = kills[0], kills[-1]
    seg_in = max(0.0, first + kill_offset - lead_in)
    freeze_at = min(video_dur - 1.0 / fps, last + kill_offset + aftermath_dur)
    play_dur = max(0.5, round(freeze_at - seg_in, 3))
    if play_dur > 60:
        print(f"  note: {play_dur:.0f}s of continuous footage -- for a clean clutch "
              f"edit, feed roughly one round")
    print(f"  one continuous shot {seg_in:.2f}-{freeze_at:.2f}s "
          f"({play_dur:.1f}s), then freeze")

    if not ffmpeg.has_encoder(encoder):
        print(f"  {encoder} unavailable -> libx264")
        encoder = "libx264"

    # 1) the whole round as ONE continuous shot (no cuts), lightly graded
    seg = Segment(round(seg_in, 3), play_dur, play_dur, zoom_amount=0.0)
    shot = work / "fz_shot.mp4"
    vf = build_segment_vf(seg, width, height, fps, grade=grade, lut=lut,
                          vignette=vignette)
    ffmpeg.run(["-ss", f"{seg_in:.3f}", "-t", f"{play_dur:.3f}", "-i", str(video),
                "-an", "-vf", vf, "-r", f"{fps:g}",
                *ffmpeg.video_encoder_args(encoder), str(shot)])

    # 2) freeze the final frame (spotlight + optional achievement banner)
    if caption == "auto":  # only badge a genuine multikill/ace -- never "6 KILLS"
        caption = {2: "DOUBLE KILL", 3: "TRIPLE KILL",
                   4: "QUAD KILL", 5: "ACE"}.get(len(kills), "")
    frame_png = work / "freeze.png"
    ffmpeg.extract_frame(video, freeze_at, frame_png)
    fz_vf = build_freeze_vf(width, height, fps, freeze_dur, grade=grade, lut=lut,
                            vignette=vignette, spotlight=spotlight,
                            zoom_amount=freeze_zoom, flash=flash,
                            fade_out=freeze_fade, caption=caption)
    freeze = work / "fz_freeze.mp4"
    ffmpeg.run(["-loop", "1", "-t", f"{freeze_dur:.3f}", "-i", str(frame_png),
                "-vf", fz_vf, "-r", f"{fps:g}",
                *ffmpeg.video_encoder_args(encoder), str(freeze)])
    badge = f', "{caption}" badge' if caption else ""
    print(f"    freeze @ {freeze_at:.2f}s held {freeze_dur:.1f}s{badge}")

    # 3) lay the song so its PEAK lands on the freeze: the build-up plays under
    #    the run-up and the drop slams exactly as the picture locks, then fades.
    out_durs = [play_dur, freeze_dur]
    total = sum(out_durs) - xfade
    freeze_pos = play_dur - xfade            # where the freeze lands on the timeline
    audio_start = max(0.0, min(peak - freeze_pos, max(0.0, song_dur - total)))
    audio_len = min(total, song_dur - audio_start)
    if audio_len < total - 1e-3:
        print(f"  note: song ({song_dur:.1f}s) is shorter than the edit "
              f"({total:.1f}s) -- it ends as the song does")
    print(f"  timeline ~{total:.2f}s; song {audio_start:.1f}-{audio_start + audio_len:.1f}s; "
          f"peak lands on the freeze (~{peak - audio_start:.1f}s in)")

    return compose([shot, freeze], out_durs, audio, audio_start, audio_len, out_path,
                   xfade=xfade, fps=fps, encoder=encoder, end_fade=freeze_fade)
