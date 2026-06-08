"""Freeze-finisher mode: the kills play through as a montage, then -- instead of
cutting away on the last kill -- the footage keeps rolling past it (the "flow"),
and as the song winds down the picture freezes on the current frame and fades to
black, so the music ends right as the image locks.

Where beat-match ends in slow motion, this ends on a held frame. The lead-up
kills cut on the beat; the final shot plays through the last kill and keeps going
for a few seconds, then its last frame is frozen and held while the song fades.
Renders end-to-end with FFmpeg (+ NVENC).
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
    kill_offset: float = -0.30, aftermath_dur: float = 5.0,
    freeze_dur: float = 3.0, freeze_zoom: float = 0.12, flash: float = 0.1,
    freeze_fade: float = 1.2, xfade: float = 0.22,
    spotlight: bool = True, caption: str = "",
    work_dir: str | Path = "output/_work",
) -> Path:
    video, out_path = Path(video), Path(out_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    video_dur = ffmpeg.probe_duration(video)
    song_dur = ffmpeg.probe_duration(audio)

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

    # The song section starts on the drop (its most energetic point) so the kills
    # hit with the music, then it plays out and fades as the picture freezes.
    song_start = music_start if music_start is not None else energy_curve(audio).peak_time
    if len(barr):  # start on a beat so the cuts stay in time
        song_start = float(barr[int(np.argmin(np.abs(barr - song_start)))])

    if beats_per_clip is None:
        beats_per_clip = int(max(2, min(4, round(1.3 / beat))))

    # Merge near-simultaneous kills into one shot (same logic as beat-match).
    clusters: list[list[float]] = []
    for k in kills:
        if clusters and k - clusters[-1][-1] <= beat:
            clusters[-1].append(k)
        else:
            clusters.append([k])
    *leadups, climax = clusters  # the last cluster's shot keeps rolling into the freeze

    # Lead-up clips: each plays live for ~beats_per_clip beats, capped to the room
    # before the next kill so footage is never shown twice. Zoom stays off.
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

    # Final shot: from the last kill's pre-roll, play through the kill and KEEP
    # ROLLING for aftermath_dur (the "flow"), then freeze this shot's last frame.
    climax_in = max(0.0, climax[0] + kill_offset - pre_roll)
    freeze_at = min(video_dur - 1.0 / fps, climax[-1] + kill_offset + aftermath_dur)
    play_dur = max(0.4, freeze_at - climax_in)
    segments.append(Segment(round(climax_in, 3), round(play_dur, 3),
                            round(play_dur, 3), zoom_amount=0.0))

    if not ffmpeg.has_encoder(encoder):
        print(f"  {encoder} unavailable -> libx264")
        encoder = "libx264"

    # 1) render the lead-up clips + the final play-through-and-flow shot
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

    # 2) the freeze: grab the final frame of the last shot and hold it (push +
    #    grade + spotlight vignette + an achievement banner), fading to black as
    #    the song settles -- the reference edit's finisher look.
    if caption == "auto":  # only badge a genuine multikill/ace -- never "6 KILLS"
        caption = {2: "DOUBLE KILL", 3: "TRIPLE KILL",
                   4: "QUAD KILL", 5: "ACE"}.get(len(kills), "")
    frame_png = work / "freeze.png"
    ffmpeg.extract_frame(video, freeze_at, frame_png)
    fz_vf = build_freeze_vf(width, height, fps, freeze_dur, grade=grade, lut=lut,
                            vignette=vignette, spotlight=spotlight,
                            zoom_amount=freeze_zoom, flash=flash,
                            fade_out=freeze_fade, caption=caption)
    fz_dst = work / f"fz_{len(segments):02d}.mp4"
    ffmpeg.run(["-loop", "1", "-t", f"{freeze_dur:.3f}", "-i", str(frame_png),
                "-vf", fz_vf, "-r", f"{fps:g}",
                *ffmpeg.video_encoder_args(encoder), str(fz_dst)])
    seg_files.append(fz_dst)
    aftermath = max(0.0, freeze_at - (climax[-1] + kill_offset))
    badge = f', "{caption}" badge' if caption else ""
    print(f"    flow {aftermath:.1f}s past the last kill, then freeze "
          f"@ {freeze_at:.2f}s held {freeze_dur:.1f}s{badge}")

    # 3) lay the song from the drop; it plays under the montage and fades out
    #    over the freeze, so the music ends right as the picture locks.
    out_durs = [s.out_dur for s in segments] + [freeze_dur]
    total = sum(out_durs) - xfade * (len(out_durs) - 1)
    audio_start = max(0.0, min(song_start, max(0.0, song_dur - total)))
    # Never run the song past its end: cap the audio bed to what's left from
    # audio_start, so the fade-out still fires and -shortest can't chop the
    # picture. If the song is shorter than the montage, it just ends as the song
    # does.
    audio_len = min(total, song_dur - audio_start)
    if audio_len < total - 1e-3:
        print(f"  note: song ({song_dur:.1f}s) is shorter than the montage "
              f"({total:.1f}s) -- it ends as the song does")
    print(f"  {len(out_durs)} clips, timeline ~{total:.2f}s; song "
          f"{audio_start:.1f}-{audio_start + audio_len:.1f}s, fading out on the freeze")

    return compose(seg_files, out_durs, audio, audio_start, audio_len, out_path,
                   xfade=xfade, fps=fps, encoder=encoder, end_fade=freeze_fade)
