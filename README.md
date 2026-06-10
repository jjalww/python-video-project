# valmontage

Automatically edits **Valorant highlight montages** by syncing the player's
kills to the beat of a song.

- **Inputs:** gameplay video, a song, the player's in-game name, and the agent.
- **Detects:** song beats (librosa) + the player's kills (OpenCV — the gold "you"
  killfeed highlight, or the agent's killfeed icon; manual-timestamp fallback).
- **Cuts** a montage in one of two modes with eased zooms, crossfades, color
  grading, speed ramps, and a smooth slow-motion ending (FFmpeg + NVENC).

## Montage modes
1. **Beat-match** (CLI default): kills cut ~one-per-beat in time with the song.
   Feed it **several clips** (the GUI's Browse lets you Ctrl-click many; the CLI
   takes paths separated by `;`) — kills are detected in each clip and pooled so
   there's enough action for every beat, and the clip with the biggest multikill
   is saved for the finisher.
2. **Freeze-finisher** (what the app preselects): plays kills **continuously**
   when they're close together
   and cuts past long dead stretches (walking/rotating), then eases into super
   slow-motion on the finish with a spotlight + optional banner, the song's drop
   landing as the slow-mo starts. A tight clutch stays one continuous take; a
   whole-game clip becomes a few tight scenes (`--gap-cut` sets the threshold).
   When the round-win banner (FLAWLESS / CLUTCH / ACE) pops after the final
   kill, the drop is anchored on it — the real on-screen climax, even if the
   knife never comes out (`--no-banner-sync` disables; "Drop at" still
   overrides the music side manually).

## New PC? Start here
1. **Get the project.** At <https://github.com/jjalww/python-video-project>
   click the green **Code** button → **Download ZIP**, then right-click the ZIP
   → **Extract All** (or `git clone https://github.com/jjalww/python-video-project.git`).
2. **Double-click `Setup (run once).bat`** in the project folder. It installs
   Python 3.12, FFmpeg, and the app's packages (needs internet, takes a few
   minutes). If it installs Python, it will ask you to run it a second time —
   do that.
3. **Double-click `Montage Maker.bat`.** That's all you ever do from then on.

**What does NOT come from GitHub:** your clips, songs, and finished montages
are media files and are deliberately not uploaded. Copy them to the new PC
yourself (USB/cloud) into `samples\`, or just paste a Medal.tv / YouTube link
straight into the Clip and Song boxes — the app downloads them. Douyin/TikTok
links usually won't work (they need a logged-in browser).

**Troubleshooting**
- "FFmpeg is not installed" → run `Setup (run once).bat` again; if it
  persists, restart the PC once.
- "No module named 'valmontage'" → run `Setup (run once).bat` again.
- "No kills found" → turn on "highlight my own kills" in Valorant's settings
  (it's the game default), or type the times in.

## Requirements
- **Python 3.12** (the audio/vision stack has no 3.14 wheels yet)
- **FFmpeg + ffprobe** on PATH
- NVIDIA GPU optional (uses `h264_nvenc` when available)

## Manual setup (advanced)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python -m pip install -r requirements.txt
```
`requirements.txt` includes `-e .`, which installs this project into the venv
so the app can find its own code — don't skip it.

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

# freeze-finisher: play the clutch, then ease into super slow-motion on the finish
python -m valmontage render samples\clip.mp4 samples\song.wav `
    --kills-json output\kills.json --mode freeze_finisher --caption ACE `
    --out output\montage.mp4
```
`--kills 9.4,38.3,40.7` accepts inline timestamps instead of `--kills-json`. The
chorus/drop is auto-detected from the song's energy (override with
`--music-start`); NVENC is used when available, falling back to libx264.
Freeze-finisher extras: `--caption` puts a banner over the finish (`auto` names
it from the kill count, `''` for none), `--aftermath` sets where the slow-mo
settles after the last kill, `--slowmo-dur` how long it lasts, and
`--no-spotlight` drops the heavy vignette.

## Montage Maker (one-click GUI)
For a no-command-line workflow, double-click **`Montage Maker.bat`** (or run
`python app.py`). The fully-automatic path: **pick a clip, pick a song, click
Make Montage** — it detects your kills, picks the best round, and renders, with
no trimming or timestamps on your end. You can still detect/type/load kills
yourself to override, choose **Freeze-finisher** or **Beat-match**, and paste a
YouTube/web link in place of a local file.

The CLI is automatic too — omit `--kills`/`--kills-json` and it detects + picks
the best round itself.

## Project layout
```
src/valmontage/
  audio/        beats, tempo, onsets, energy/drop
  killdetect/   OpenCV ROI template match + manual fallback
  editing/      clip windows, zoom/color/speed/slowmo effects, transitions
  modes/        beatmatch, freeze_finisher
  render/       FFmpeg filtergraph build + NVENC encode
  utils/
config/example.yaml   reference of the tunable settings (not loaded by the
                      app — use the GUI's Advanced settings or CLI flags)
assets/agent_icons/   killfeed icon templates    assets/luts/   .cube LUTs
samples/   inputs (gitignored)    output/   renders (gitignored)
```

> `venv/`, `__pycache__/`, and all video/audio media are git-ignored.

Built in phases (beats → kills → render [beat-match + freeze-finisher] → GUI).
