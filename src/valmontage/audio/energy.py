"""Find the high-energy section of a song (chorus / drop) to use as the
montage's music bed. Also reused by freeze-finisher mode (Phase 4) to
locate the climax.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np


@dataclass
class EnergyResult:
    times: list[float]
    energy: list[float]      # smoothed, normalised 0..1
    peak_time: float         # time of maximum sustained energy


def energy_curve(audio_path, *, sr: int = 22050, hop_length: int = 512,
                 smooth_seconds: float = 2.0) -> EnergyResult:
    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

    win = max(1, int(smooth_seconds * sr / hop_length))
    kernel = np.ones(win) / win
    smooth = np.convolve(rms, kernel, mode="same")
    norm = (smooth - smooth.min()) / (np.ptp(smooth) + 1e-9)

    return EnergyResult(
        times=[round(float(t), 3) for t in times],
        energy=[round(float(e), 4) for e in norm],
        peak_time=round(float(times[int(np.argmax(smooth))]), 3),
    )


def pick_montage_start(beats: list[float], energy: EnergyResult,
                       lead_in_beats: int = 0) -> float:
    """Return the beat at/just before the energy peak — a punchy entry
    into the chorus/drop. ``lead_in_beats`` can start a little earlier."""
    if not beats:
        return energy.peak_time
    arr = np.asarray(beats)
    i = int(np.searchsorted(arr, energy.peak_time))
    i = max(0, min(len(arr) - 1, i))
    i = max(0, i - lead_in_beats)
    return float(arr[i])
