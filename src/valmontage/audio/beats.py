"""Phase 1: beat / tempo / onset detection.

Loads an audio file and returns the song's tempo (BPM), the beat
timestamps, and onset timestamps. Beats drive cut placement in
beat-match mode; onsets give finer transient markers and feed the
energy curve used to find the drop in freeze-finisher mode.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import librosa
import numpy as np


@dataclass
class BeatResult:
    """Result of analyzing a song's rhythm."""

    bpm: float
    beats: list[float]              # beat times in seconds
    onsets: list[float]             # onset (transient) times in seconds
    duration: float                 # track length in seconds
    sr: int                         # sample rate used for analysis

    # --- convenience ---
    @property
    def n_beats(self) -> int:
        return len(self.beats)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["n_beats"] = self.n_beats
        return d

    def save_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path


def detect_beats(
    audio_path: str | Path,
    *,
    sr: int | None = 22050,
    hop_length: int = 512,
    tightness: float = 100.0,
) -> BeatResult:
    """Detect tempo, beats, and onsets in an audio file.

    Args:
        audio_path: path to a local audio file (wav/mp3/flac/...).
        sr: target sample rate for analysis (22.05 kHz is plenty for
            rhythm and keeps it fast). Pass None to keep native rate.
        hop_length: STFT hop in samples; sets time resolution of the
            beat/onset grid (512 @ 22050 Hz ~= 23 ms).
        tightness: how strictly librosa's tracker locks to the estimated
            tempo. Higher = steadier grid (good for funk/EDM with a
            constant beat); lower = follows tempo drift.

    Returns:
        BeatResult with bpm, beat times, onset times, duration, sr.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))

    # Onset envelope drives both tempo/beat tracking and onset picking.
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)

    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=hop_length,
        tightness=tightness,
        units="frames",
    )
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)

    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env, sr=sr, hop_length=hop_length, units="frames"
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)

    # librosa may return tempo as a 0-d/1-element array.
    bpm = float(np.atleast_1d(tempo)[0])

    return BeatResult(
        bpm=round(bpm, 2),
        beats=[round(float(t), 4) for t in beat_times],
        onsets=[round(float(t), 4) for t in onset_times],
        duration=round(duration, 4),
        sr=int(sr),
    )


def nearest_beat(beats: list[float], t: float) -> float:
    """Return the beat time closest to ``t`` (used later to snap cuts)."""
    if not beats:
        return t
    arr = np.asarray(beats)
    return float(arr[int(np.argmin(np.abs(arr - t)))])
