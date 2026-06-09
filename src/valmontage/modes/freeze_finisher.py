"""Freeze-finisher mode: build a tight clutch edit that plays kills continuously
when they're close together but CUTS past long dead stretches, then eases into
super-slow, near-frozen motion on the finish (the knife flex / reaction) with a
spotlight vignette and an optional banner, the song's drop landing as the
slow-motion begins.

Kills within ``gap_cut`` seconds of each other play as one continuous shot (no
jump cuts); a longer gap (walking / rotating) is cut out with a crossfade. So a
tight clutch stays one smooth continuous take, while a whole-game clip becomes a
few tight scenes instead of minutes of dead time.

Renders end-to-end with FFmpeg (+ NVENC).
"""

from __future__ import annotations

from pathlib import Path

from ..audio.energy import find_drop
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
    kill_offset: float = -0.30, lead_in: float = 3.0, gap_cut: float = 6.0,
    scene_lead: float = 1.2, scene_tail: float = 1.3, aftermath_dur: float = 1.25,
    slowmo_dur: float = 4.0, ramp_src: float = 0.6, freeze_fade: float = 1.2,
    xfade: float = 0.25, spotlight: bool = True, caption: str = "",
    work_dir: str | Path = "output/_work",
    # accepted for CLI/GUI compatibility; not used by this edit:
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

    # The song's drop (where the bass kicks in). We line this up to the start of
    # the slow-mo so it slams as time begins to slow.
    drop = music_start if music_start is not None else find_drop(audio)

    # Group kill action-moments into scenes: kills within gap_cut play together
    # (one continuous shot); a bigger gap starts a new scene (cut between them).
    actions = [k + kill_offset for k in kills]
    scenes: list[list[float]] = [[actions[0]]]
    for a in actions[1:]:
        if a - scenes[-1][-1] <= gap_cut:
            scenes[-1].append(a)
        else:
            scenes.append([a])

    # The slow-mo's near-frozen END lands ~aftermath_dur past the last kill; the
    # short window before it (ramp_src of source) is what gets stretched.
    slowmo_end = min(video_dur - 1.0 / fps, actions[-1] + aftermath_dur)
    ramp_src = max(0.1, min(ramp_src, slowmo_dur * 0.4))
    ramp_start = slowmo_end - ramp_src
    end_speed = ramp_src / (2 * slowmo_dur - ramp_src)

    if not ffmpeg.has_encoder(encoder):
        print(f"  {encoder} unavailable -> libx264")
        encoder = "libx264"
    print(f"  {len(scenes)} scene(s) (gaps > {gap_cut:.0f}s cut out), "
          f"then slow-mo to ~{end_speed:.2f}x")

    # 1) each scene as one continuous normal-speed shot; the last scene runs up
    #    to ramp_start, where the slow-mo takes over.
    seg_files: list[Path] = []
    out_durs: list[float] = []
    for i, sc in enumerate(scenes):
        s_start = max(0.0, sc[0] - (lead_in if i == 0 else scene_lead))
        s_end = ramp_start if i == len(scenes) - 1 else min(video_dur, sc[-1] + scene_tail)
        dur = max(0.5, round(s_end - s_start, 3))
        seg = Segment(round(s_start, 3), dur, dur, zoom_amount=0.0)
        dst = work / f"fz_sc{i:02d}.mp4"
        vf = build_segment_vf(seg, width, height, fps, grade=grade, lut=lut,
                              vignette=vignette)
        ffmpeg.run(["-ss", f"{s_start:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
                    "-an", "-vf", vf, "-r", f"{fps:g}",
                    *ffmpeg.video_encoder_args(encoder), str(dst)])
        seg_files.append(dst)
        out_durs.append(dur)
        print(f"    scene {i}: {s_start:.1f}-{s_end:.1f}s ({dur:.1f}s, "
              f"{len(sc)} kill{'s' if len(sc) > 1 else ''})")

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
    seg_files.append(slow)
    out_durs.append(slowmo_dur)
    badge = f', "{caption}" banner' if caption else ""
    print(f"    slow-mo ends @ {slowmo_end:.2f}s{badge}")

    # 3) lay the song so its PEAK lands on the START of the slow-mo, then fades.
    total = sum(out_durs) - xfade * (len(out_durs) - 1)
    slowmo_start = total - slowmo_dur
    audio_start = max(0.0, min(drop - slowmo_start, max(0.0, song_dur - total)))
    audio_len = min(total, song_dur - audio_start)
    if audio_len < total - 1e-3:
        print(f"  note: song ({song_dur:.1f}s) is shorter than the edit "
              f"({total:.1f}s) -- it ends as the song does")
    print(f"  timeline ~{total:.2f}s; song {audio_start:.1f}-{audio_start + audio_len:.1f}s; "
          f"drop lands as the slow-mo starts (~{slowmo_start:.1f}s)")

    return compose(seg_files, out_durs, audio, audio_start, audio_len, out_path,
                   xfade=xfade, fps=fps, encoder=encoder, end_fade=freeze_fade)
