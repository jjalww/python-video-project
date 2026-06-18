---
title: Valorant Montage Maker
emoji: 🎬
colorFrom: red
colorTo: indigo
sdk: gradio
python_version: "3.12"
app_file: app.py
pinned: false
short_description: Beat-synced Valorant highlight montages from your clips
---

# 🎬 Valorant Montage Maker

Upload your Valorant clips and a song, and get a beat-synced highlight
montage back. Your kills are detected automatically — no trimming or
timestamps needed.

- **Beat-match** — a kill cut on every beat; works best with several clips.
- **Freeze-finisher** — plays one clutch, then eases into super slow-motion,
  with the music's drop landing on the round-win banner.

**For the song, upload an audio file.** Pasting a YouTube link usually fails on
this free server — YouTube blocks downloads from cloud servers (it works from
the desktop app at home). Uploading always works.

Powered by the [valmontage](https://github.com/jjalww/python-video-project)
engine. This free Space runs on CPU, so a montage takes a few minutes; the
desktop app (in the GitHub repo) is much faster on a gaming GPU.
