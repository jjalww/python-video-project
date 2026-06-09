"""Freeze-finisher mode: play the clutch round straight through as ONE
continuous shot -- no jump cuts -- and instead of ending on the last kill, ease
smoothly into super-slow, near-frozen motion on the finish (the knife flex /
reaction), with a spotlight vignette and an optional banner, while the song's
drop lands right as the slow-motion begins and then fades out.

Modelled on hand-made clutch edits: one clean continuous clip that ramps into a
held finish. Feed it roughly one round / one clutch.

Renders end-to-end with FFmpeg (+ NVENC).
"""

from __future__ import annotations

from pathlib import Path

from ..audio.energy import energy_curve
from ..editing.effects import build_segment_vf, build_slowmo_vf
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
    slowmo_dur: float = 4.0, ramp_src: float = 0.6, freeze_fade: float = 1.2,
    xfade: float = 0.25, spotlight: bool = True, caption: str = "",
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

    # The song's peak (its drop). We line this up to the start of the slow-mo.
    peak = music_start if music_start is not None else energy_curve(audio).peak_time

    # The slow-mo's near-frozen END lands ~aftermath_dur past the last kill (the
    # knife flex / reaction). The short window before it (ramp_src of source) is
    # what gets stretched, easing from 1x into near-freeze.
    first, last = kills[0], kills[-1]
    seg_in = max(0.0, first + kill_offset - lead_in)
    slowmo_end = min(video_dur - 1.0 / fps, last + kill_offset + aftermath_dur)
    ramp_src = max(0.1, min(ramp_src, slowmo_dur * 0.4, slowmo_end - seg_in - 0.5))
    ramp_start = max(seg_in + 0.3, slowmo_end - ramp_src)
    ramp_src = round(slowmo_end - ramp_start, 3)        # source actually consumed
    normal_dur = max(0.5, round(ramp_start - seg_in, 3))
    end_speed = ramp_src / (2 * slowmo_dur - ramp_src)  # speed at the deepest point
    print(f"  continuous shot {seg_in:.2f}-{ramp_start:.2f}s ({normal_dur:.1f}s), "
          f"then ease into slow-mo over {slowmo_dur:.1f}s (down to ~{end_speed:.2f}x)")

    if not ffmpeg.has_encoder(encoder):
        print(f"  {encoder} unavailable -> libx264")
        encoder = "libx264"

    # 1) the round as ONE continuous normal-speed shot (no cuts), lightly graded
    seg = Segment(round(seg_in, 3), normal_dur, normal_dur, zoom_amount=0.0)
    shot = work / "fz_shot.mp4"
    vf = build_segment_vf(seg, width, height, fps, grade=grade, lut=lut,
                          vignette=vignette)
    ffmpeg.run(["-ss", f"{seg_in:.3f}", "-t", f"{normal_dur:.3f}", "-i", str(video),
                "-an", "-vf", vf, "-r", f"{fps:g}",
                *ffmpeg.video_encoder_args(encoder), str(shot)])

    # 2) the finisher: ease the last beat of footage into super-slow motion
    if caption == "auto":  # only badge a genuine multikill/ace -- never "6 KILLS"
        caption = {2: "DOUBLE KILL", 3: "TRIPLE KILL",
                   4: "QUAD KILL", 5: "ACE"}.get(len(kills), "")
    slow = work / "fz_slow.mp4"
    sm_vf = build_slowmo_vf(width, height, fps, ramp_src, slowmo_dur, grade=grade,
                            lut=lut, vignette=vignette, spotlight=spotlight,
                            fade_out=freeze_fade, caption=caption)
    ffmpeg.run(["-ss", f"{ramp_start:.3f}", "-t", f"{ramp_src:.3f}", "-i", str(video),
                "-an", "-vf", sm_vf, "-r", f"{fps:g}",
                *ffmpeg.video_encoder_args(encoder), str(slow)])
    badge = f', "{caption}" banner' if caption else ""
    print(f"    slow-mo ends @ {slowmo_end:.2f}s{badge}")

    # 3) lay the song so its PEAK lands on the START of the slow-mo: the build-up
    #    plays under the run-up, the drop hits as time starts to slow, then fades.
    out_durs = [normal_dur, slowmo_dur]
    total = sum(out_durs) - xfade
    slowmo_start = normal_dur - xfade          # where the slow-mo begins on the timeline
    audio_start = max(0.0, min(peak - slowmo_start, max(0.0, song_dur - total)))
    audio_len = min(total, song_dur - audio_start)
    if audio_len < total - 1e-3:
        print(f"  note: song ({song_dur:.1f}s) is shorter than the edit "
              f"({total:.1f}s) -- it ends as the song does")
    print(f"  timeline ~{total:.2f}s; song {audio_start:.1f}-{audio_start + audio_len:.1f}s; "
          f"drop lands as the slow-mo starts (~{slowmo_start:.1f}s)")

    return compose([shot, slow], out_durs, audio, audio_start, audio_len, out_path,
                   xfade=xfade, fps=fps, encoder=encoder, end_fade=freeze_fade)
