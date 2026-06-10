"""Shared final stage for every montage mode: crossfade-concat a list of
already-rendered segment clips and lay the song under them.

Both beat-match and freeze-finisher build a list of segment files plus their
on-screen durations, then hand off here. Keeping the xfade-chain + audio-bed
logic in one place means the two modes can't drift apart on transitions or
audio handling.
"""

from __future__ import annotations

from pathlib import Path

from . import ffmpeg


def build_xfade_chain(n: int, out_durs: list[float], xfade: float,
                      last_xfade: float | None = None) -> tuple[list[str], str]:
    """Chain ``n`` segment video streams ([0:v]..[n-1:v]) with eased crossfades.

    ``last_xfade`` overrides the duration of the final join; 0 makes it a hard
    cut (concat). The freeze-finisher uses that: its slow-mo continues the last
    shot's footage at 1x, so a dissolve there only ghosts two near-identical
    frames over each other -- a clean cut is the invisible join.

    Returns the filter_complex parts and the label of the final video stream.
    With a single segment there is nothing to fade, so ``0:v`` is returned.
    """
    if n <= 1:
        return [], "0:v"
    fc: list[str] = []
    cur = out_durs[0]
    prev = "0:v"
    for k in range(1, n):
        d = last_xfade if (last_xfade is not None and k == n - 1) else xfade
        out = f"v{k}"
        if d > 1e-6:
            fc.append(f"[{prev}][{k}:v]xfade=transition=fade:"
                      f"duration={d:.3f}:offset={cur - d:.3f}[{out}]")
            cur = cur + out_durs[k] - d
        else:
            fc.append(f"[{prev}][{k}:v]concat=n=2:v=1:a=0[{out}]")
            cur = cur + out_durs[k]
        prev = out
    return fc, prev


def compose(
    seg_files: list[Path],
    out_durs: list[float],
    audio: str | Path,
    audio_start: float,
    total_dur: float,
    out_path: str | Path,
    *,
    xfade: float = 0.22,
    last_xfade: float | None = None,
    fps: float = 60.0,
    encoder: str = "libx264",
    end_fade: float = 0.8,
    audio_fade_in: float = 0.15,
) -> Path:
    """Crossfade-concat ``seg_files`` and lay ``audio`` (from ``audio_start``)
    under the result, trimmed to ``total_dur`` with an eased fade-out so the
    song settles instead of cutting. Encodes to ``out_path``.
    """
    inputs: list[str] = []
    for f in seg_files:
        inputs += ["-i", str(f)]
    audio_idx = len(seg_files)
    # audio_start is the *song* offset: started early enough that the build-up
    # plays under the opening and the drop lands where the mode wants it.
    inputs += ["-ss", f"{audio_start:.3f}", "-i", str(audio)]

    fc, vlabel = build_xfade_chain(len(seg_files), out_durs, xfade, last_xfade)
    fc.append(
        f"[{audio_idx}:a]atrim=0:{total_dur:.3f},"
        f"afade=t=in:st=0:d={audio_fade_in:.3f},"
        f"afade=t=out:st={max(0.0, total_dur - end_fade):.3f}:d={end_fade:.3f}[a]")

    out_args = ["-map", f"[{vlabel}]" if len(seg_files) > 1 else "0:v",
                "-map", "[a]", "-r", f"{fps:g}",
                *ffmpeg.video_encoder_args(encoder),
                "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)]
    ffmpeg.run([*inputs, "-filter_complex", ";".join(fc), *out_args])
    return Path(out_path)
