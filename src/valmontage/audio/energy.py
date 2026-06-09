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


def find_drop(audio_path, *, sr: int = 22050, hop_length: int = 512,
              smooth_seconds: float = 1.0, step_seconds: float = 2.0,
              low_hz: float = 200.0) -> float:
    """Locate the song's drop -- the moment the beat/bass kicks in after a
    build-up -- as the largest energy *step-up into a sustained loud section*.

    Blends overall RMS with low-frequency (bass) energy, since a drop is defined
    by the bass slamming in. This beats the plain energy peak (``peak_time``),
    which sits in the middle of the loudest chorus rather than on the impact, so
    it's what we sync a hit (e.g. the slow-mo) to.
    """
    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    spec = np.abs(librosa.stft(y, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr)
    low = freqs < low_hz
    bass = spec[low].sum(axis=0) if low.any() else rms

    def _norm(x):
        return (x - x.min()) / (np.ptp(x) + 1e-9)

    energy = 0.5 * _norm(rms) + 0.5 * _norm(bass)
    win = max(1, int(smooth_seconds * sr / hop_length))
    energy = np.convolve(energy, np.ones(win) / win, mode="same")
    times = librosa.frames_to_time(np.arange(len(energy)), sr=sr, hop_length=hop_length)

    w = max(1, int(step_seconds * sr / hop_length))
    n = len(energy)
    cs = np.concatenate([[0.0], np.cumsum(energy)])
    idx = np.arange(n)

    def _winmean(a, b):  # mean of energy[a:b], vectorised via cumulative sum
        a, b = np.clip(a, 0, n), np.clip(b, 0, n)
        return (cs[b] - cs[a]) / np.maximum(1, b - a)

    post = _winmean(idx, idx + w)                  # loudness of the next ``w`` frames
    step = post - _winmean(idx - w, idx)           # how much it jumps up
    # only count rises that land in a genuinely loud section (a real drop, not a
    # tiny bump in a quiet part)
    score = np.where(post >= 0.55 * energy.max(), step, -1.0)
    return round(float(times[int(np.argmax(score))]), 3)


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
