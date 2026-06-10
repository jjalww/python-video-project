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
              smooth_seconds: float = 1.0, hi: float = 0.85,
              low_hz: float = 200.0) -> float:
    """Locate the song's drop -- the climactic moment the beat/bass slams back in
    after the main breakdown.

    In hype/EDM tracks the drop montages hit is the return to full energy after a
    breakdown, not the first chorus or the loudest average moment. So: take the
    *loud* frames (>= ``hi`` x the track's peak energy, blending RMS with
    low-frequency bass); the deepest energy valley between the first and last loud
    moment is the main breakdown; the drop is the first loud frame after it.

    That crossing happens during the buildup's rising crescendo, a beat or two
    BEFORE the bass actually slams in (the smoothed curve climbs over the
    threshold early), so the result is then snapped to the steepest bass jump
    nearby -- the slam itself.
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

    loud = energy >= hi * energy.max()
    if not loud.any():
        return round(float(times[int(np.argmax(energy))]), 3)
    first = int(np.argmax(loud))                       # first slam
    last = len(loud) - 1 - int(np.argmax(loud[::-1]))  # last slam
    if last <= first:
        return round(float(times[first]), 3)
    breakdown = first + int(np.argmin(energy[first:last + 1]))  # deepest valley between
    drop = breakdown + int(np.argmax(loud[breakdown:]))         # first slam after it

    # Snap to the slam: the first near-max bass jump within a couple of seconds
    # of the threshold crossing (which lands in the buildup, not the kick-in).
    # "First >= 80% of the biggest" rather than the argmax, because every kick
    # after the drop is a near-identical jump -- the max alone may pick beat 2.
    j = max(1, int(round(0.15 * sr / hop_length)))   # bass-rise window ~0.15s
    w = int(round(2.0 * sr / hop_length))            # search +/-2s around the crossing
    lo, hi_i = max(0, drop - w), min(len(energy) - j, drop + w)
    if hi_i > lo:
        bsm = np.convolve(_norm(bass), np.ones(j) / j, mode="same")
        rise = bsm[lo + j:hi_i + j] - bsm[lo:hi_i]
        if rise.max() > 0:
            first_big = int(np.flatnonzero(rise >= 0.8 * rise.max())[0])
            drop = lo + first_big + j // 2
    return round(float(times[drop]), 3)


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
