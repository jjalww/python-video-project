# valmontage

Automatically edits **Valorant highlight montages** by syncing the player's
kills to the beat of a song.

- **Inputs:** gameplay video, a song, the player's in-game name, and the agent.
- **Detects:** song beats (librosa) + the player's kills (OpenCV — the gold "you"
  killfeed highlight, or the agent's killfeed icon; manual-timestamp fallback).
- **Cuts** a montage in one of two modes with eased zooms, crossfades, color
  grading, speed ramps, and a smooth slow-motion ending (FFmpeg + NVENC).

## Montage modes
1. **Beat-match** (default): kills cut ~one-per-beat in time with the song.
2. **Freeze-finisher**: the kills play through, the footage keeps rolling past the
   last kill, then it freezes on the final frame and fades out as the song ends.

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

## Phase 2 — kill detection
```powershell
# default: detect the player's OWN kills from the gold killfeed highlight (no agent needed)
python -m valmontage kills samples\clip.mp4 --out output\kills.json
# template mode: match the player's agent portrait instead
python -m valmontage kills samples\clip.mp4 --method template --template assets\agent_icons\neon.png `
    --player Zayn --agent neon --out output\kills.json --debug output\kills_debug.mp4
# manual fallback: supply timestamps yourself
python -m valmontage kills samples\clip.mp4 --manual 9.4,38.3,40.7,42.3 --out output\kills.json
```
The default **highlight** method finds the local player's own kills — the gold
"you" nameplate on the killer (left) side paired with a red enemy victim on the
right — so teammates' kills/deaths and ability/map colour washes are ignored (it
needs Valorant's "highlight my own kills" setting on, which is the default). The
**template** method instead matches the agent's (unique) killfeed portrait. Both
count rising edges so multikills register; `--debug` (template) writes an overlay.

Calibrate the ROI/template for a new clip with:
```powershell
python tests\inspect_roi.py output\_frames\full_43.png 950 50 120 100 --scale 8
```

## Phase 3 — render the montage
Both modes are driven by the kill timestamps + the song:
```powershell
# beat-match (default): kills cut ~one-per-beat, eased zooms, slow-mo finisher
python -m valmontage render samples\clip.mp4 samples\song.wav `
    --kills-json output\kills.json --out output\montage.mp4

# freeze-finisher: play past the last kill, then freeze with a spotlight + banner
python -m valmontage render samples\clip.mp4 samples\song.wav `
    --kills-json output\kills.json --mode freeze_finisher --caption ACE `
    --out output\montage.mp4
```
`--kills 9.4,38.3,40.7` accepts inline timestamps instead of `--kills-json`. The
chorus/drop is auto-detected from the song's energy (override with
`--music-start`); NVENC is used when available, falling back to libx264.
Freeze-finisher extras: `--caption` puts a banner over the freeze (`auto` names
it from the kill count, `''` for none), `--aftermath`/`--freeze-dur` set the
play-out and hold lengths, and `--no-spotlight` drops the heavy vignette.

## Montage Maker (one-click GUI)
For a no-command-line workflow, double-click **`Montage Maker.bat`** (or run
`python app.py`): pick a clip and a song, detect or paste the kill timestamps,
choose **Beat-match** or **Freeze-finisher**, and click **Make Montage**. A
YouTube/web link can be pasted in place of a local file.

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

Built in phases (beats → kills → render [beat-match + freeze-finisher] → GUI).
