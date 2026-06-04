"""Generate a synthetic click track at a known BPM for testing beat detection."""

import sys
from pathlib import Path

import numpy as np
import soundfile as sf


def make(path: str, bpm: float = 120.0, dur: float = 8.0, sr: int = 22050) -> None:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    y = np.zeros_like(t)
    period = 60.0 / bpm
    click_len = int(0.01 * sr)
    env = np.exp(-np.linspace(0, 8, click_len))
    tone = np.sin(2 * np.pi * 1000 * np.arange(click_len) / sr) * env
    for k in range(int(dur / period)):
        i = int(k * period * sr)
        y[i:i + click_len] += tone
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, y.astype(np.float32), sr)
    print(f"wrote {path}  (expected {bpm:g} BPM, beat every {period:g}s)")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "samples/_synthetic_test.wav"
    make(out)
