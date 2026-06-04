# valmontage

Automatically edits **Valorant highlight montages** by syncing the player's
kills to the beat of a song.

- **Inputs:** gameplay video, a song, the player's in-game name, and the agent.
- **Detects:** song beats (librosa) + kill moments (OpenCV template-match of the
  agent's killfeed icon in the top-right; manual-timestamp fallback).
- **Cuts** a montage in one of two modes with eased zooms, crossfades, color
  grading, speed ramps, and a smooth slow-motion ending (FFmpeg + NVENC).

## Montage modes
1. **Beat-match** (default): kills cut ~one-per-beat in time with the song.
2. **Freeze-finisher**: clips play through, then freeze on the key kill at the
   song's drop with full-screen effects before fading out.

## Requirements
- **Python 3.12** (the audio/vision stack has no 3.14 wheels yet)
- **FFmpeg + ffprobe** on PATH
- NVIDIA GPU optional (uses `h264_nvenc` when available)

## Setup (Windows / PowerShell)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Phase 1 — beat detection
```powershell
# local file
python -m valmontage beats samples\song.wav --out output\beats.json
# or a link (downloads audio via yt-dlp)
python -m valmontage beats "https://youtu.be/..." --out output\beats.json
```
Prints BPM, beat count, and the first beats; `--out` writes the full result
(BPM, beats[], onsets[], duration) to JSON.

## Project layout
```
src/valmontage/
  audio/        beats, tempo, onsets, energy/drop
  killdetect/   OpenCV ROI template match + manual fallback
  editing/      clip windows, zoom/color/speed/slowmo effects, transitions
  modes/        beatmatch, freeze_finisher
  render/       FFmpeg filtergraph build + NVENC encode
  utils/
config/example.yaml   per-render config (player, agent, mode, style)
assets/agent_icons/   killfeed icon templates    assets/luts/   .cube LUTs
samples/   inputs (gitignored)    output/   renders (gitignored)
```

> `venv/`, `__pycache__/`, and all video/audio media are git-ignored.

Built in phases (beats → kills → beat-match → freeze-finisher → web UI).
