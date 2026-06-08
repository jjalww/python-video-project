"""Turn kill timestamps + song beats into a beat-aligned clip plan.

Each kill becomes a segment whose on-screen length spans a whole number
of song beats, so cuts land on the beat. The kill's action moment is
placed at the segment start (on the beat) with a small pre-roll. The last
kill becomes a slow-motion finisher.

The plan is book-ended: an opening intro (footage leading up to the first
kill, fading in with an eased push) eases the viewer in before the cuts
start, mirroring the slow-motion fade-out finisher at the other end. The
song is started early enough that its build-up plays under the intro and
the chorus/drop lands exactly as the beat-matched montage begins.

The ending ramps into deep slow motion (the last clips slow progressively,
then a long slow-mo finisher) and the finisher is stretched so the montage
lands on a musical bar line, so the song fades out on a clean boundary
rather than being chopped mid-phrase.

Kills that land close together are handled so footage is never shown twice:
near-simultaneous kills (within ~a beat) merge into one continuous shot, and
every shot's length is capped to the room before the next kill -- so two kills
0.8s apart become two short on-beat cuts, not two overlapping 1.3s clips.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _snap_forward(x: float, grid: np.ndarray, step: float) -> float:
    """Distance from ``x`` forward to the next point on ``grid`` (a sorted
    array of times). If ``x`` is past the grid, extrapolate with ``step``.
    Always >= 0, so we only ever lengthen (slow) the finisher.
    """
    later = grid[grid >= x - 1e-6]
    if len(later):
        target = float(later[0])
    else:
        base = float(grid[-1])
        target = base + float(np.ceil((x - base) / step)) * step
    return max(0.0, target - x)


@dataclass
class Segment:
    source_in: float       # seconds into the source clip
    source_dur: float      # source footage length used
    out_dur: float         # on-screen duration (after speed change)
    speed: float = 1.0     # <1 = slow motion
    zoom_amount: float = 0.12
    is_finisher: bool = False
    is_intro: bool = False
    fade_in: float = 0.0
    fade_out: float = 0.0


@dataclass
class Plan:
    segments: list[Segment]
    music_start: float
    xfade: float
    total_dur: float       # final timeline length after xfade overlaps


def build_beatmatch_plan(
    kills: list[float],
    beats: list[float],
    music_start: float,
    video_dur: float,
    *,
    kill_offset: float = -0.30,    # killfeed pops ~0.3s after the kill
    pre_roll: float = 0.25,        # start each kill clip 0.25s before the action
    beats_per_clip: int = 3,
    merge_gap: float | None = None,  # merge kills closer than this (default: ~1 beat)
    xfade: float = 0.22,
    finisher_factor: float = 0.4,  # finisher speed; lower = slower slow-mo
    finisher_fade: float = 0.9,
    ramp_clips: int = 2,           # trailing kills that slow down into the finisher
    ramp_factor: float = 0.6,      # speed of the clip just before the finisher
    align_end: bool = True,        # stretch the finisher to land on a bar line
    beats_per_bar: int = 4,
    min_finisher_speed: float = 0.28,  # don't slow the finisher past this
    intro_dur: float = 5.0,        # opening intro length (0 disables it)
    intro_fade: float = 0.6,       # intro fade-in (mirrors the finisher fade-out)
    intro_zoom: float = 0.10,      # intro eased push-zoom amount
    zoom: bool = False,            # zoom punches/pushes (off: they hit on off timings)
) -> Plan:
    beats = [b for b in beats if b >= music_start] or beats
    barr = np.asarray(beats)
    beat = float(np.median(np.diff(barr))) if len(barr) > 1 else 0.5
    # Zoom is off by default -- punches on slightly-off kill timings look worse
    # than clean cuts. za_* are 0 unless zoom is explicitly enabled.
    za_fin, za_ramp, za_norm, za_intro = (0.18, 0.14, 0.12, intro_zoom) if zoom else (0.0, 0.0, 0.0, 0.0)

    # Merge near-simultaneous kills into one shot so a fast multi-kill is one
    # continuous clip, not overlapping cuts.
    gap_merge = beat if merge_gap is None else merge_gap
    clusters: list[list[float]] = []
    for k in sorted(kills):
        if clusters and k - clusters[-1][-1] <= gap_merge:
            clusters[-1].append(k)
        else:
            clusters.append([k])

    m = len(clusters)
    segments: list[Segment] = []
    cursor = 0  # position in the beat grid; advancing it keeps cuts on real beats
    for ci, cl in enumerate(clusters):
        first, last = cl[0], cl[-1]
        src_in = max(0.0, first + kill_offset - pre_roll)
        rank = m - 1 - ci              # 0 = finisher, 1 = clip before it, ...

        # Source room before the next shot starts -- the clip may not exceed it,
        # or it would re-show footage the next clip also shows.
        if ci + 1 < m:
            nxt_in = max(0.0, clusters[ci + 1][0] + kill_offset - pre_roll)
            avail = max(0.0, nxt_in - src_in)
            cap = max(1, int(np.floor(avail / beat)))
        else:
            avail = max(0.0, video_dur - src_in)
            cap = len(barr)

        if len(cl) == 1:
            want = beats_per_clip
        else:  # a merged multi-kill needs enough beats to show the whole burst
            want = int(np.ceil(((last - first) + pre_roll + 0.45) / beat))
        nb = max(1, min(want, cap))

        on = float(barr[cursor + nb] - barr[cursor]) if cursor + nb < len(barr) else nb * beat
        cursor += nb

        if rank == 0:
            src_dur = min(on + 0.4, avail)
            seg = Segment(src_in, round(src_dur, 3), round(src_dur / finisher_factor, 3),
                          speed=finisher_factor, zoom_amount=za_fin,
                          is_finisher=True, fade_out=finisher_fade)
        elif 0 < rank <= ramp_clips:
            # Ease into the finisher: progressively slower, but kept on-beat by
            # playing less source footage over the same on-screen beat span.
            f = ramp_factor + (1.0 - ramp_factor) * (rank - 1) / max(1, ramp_clips)
            src_dur = min(on * f, avail)
            seg = Segment(src_in, round(src_dur, 3), round(on, 3),
                          speed=round(f, 4), zoom_amount=za_ramp)
        else:
            src_dur = min(on, avail)
            seg = Segment(src_in, round(src_dur, 3), round(src_dur, 3), zoom_amount=za_norm)
        segments.append(seg)

    # Opening intro: the footage leading up to the first kill, fading in with
    # an eased push so the montage doesn't start cold. Sits flush against the
    # first kill clip, so it flows straight into the action. Bookends the
    # slow-mo fade-out finisher at the other end.
    audio_start = music_start
    if intro_dur > 0 and segments:
        first_in = segments[0].source_in
        intro_in = max(0.0, first_in - intro_dur)
        intro_src = round(first_in - intro_in, 3)
        if intro_src > 0.1:
            segments.insert(0, Segment(
                intro_in, intro_src, intro_src,
                zoom_amount=za_intro, is_intro=True, fade_in=intro_fade))
            # Start the song early so its build-up plays under the intro and
            # the drop lands as the first beat-matched cut hits.
            audio_start = max(0.0, music_start - intro_src)

    # Land the ending on a musical boundary so the song fades out on a clean
    # bar line instead of mid-phrase. Stretch the finisher's slow-mo to reach
    # the next bar (fall back to the next beat if that would slow it too far).
    fin = segments[-1] if segments else None
    if align_end and fin is not None and fin.is_finisher and len(barr) > 1:
        total0 = sum(s.out_dur for s in segments) - xfade * (len(segments) - 1)
        song_end = audio_start + total0
        extra = _snap_forward(song_end, barr[::beats_per_bar], beats_per_bar * beat)
        if fin.source_dur / (fin.out_dur + extra) < min_finisher_speed:
            extra = _snap_forward(song_end, barr, beat)
        fin.out_dur = round(fin.out_dur + extra, 3)
        fin.speed = round(fin.source_dur / fin.out_dur, 4)

    total = sum(s.out_dur for s in segments) - xfade * (len(segments) - 1)
    return Plan(segments, round(audio_start, 3), xfade, round(total, 3))
