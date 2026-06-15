"""Phone-friendly web front-end for valmontage, for Hugging Face Spaces.

This is a thin Gradio wrapper around the SAME engine the desktop app uses
(the ``valmontage`` package, installed from GitHub via requirements.txt). You
upload clips and a song from your phone, it detects your kills, builds the
montage on the server (CPU / libx264 -- no gaming GPU here), and hands back a
video to play or download.

The heavy desktop bits (Tkinter window, NVENC, Windows paths) are NOT used;
only the portable engine functions are called.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import gradio as gr

from valmontage.editing.plan import pick_highlight
from valmontage.killdetect.highlight import detect_kills_by_highlight
from valmontage.modes.beatmatch import render_beatmatch
from valmontage.modes.freeze_finisher import render_freeze_finisher
from valmontage.utils.fetch import fetch_audio, is_url

GRADES = ["teal_orange", "contrast_boost", "vignette_only", "none"]
# Free Spaces have no gaming GPU, so renders are CPU/libx264. 720p30 keeps a
# montage to a few minutes; 1080p60 is much slower (and interpolated slow-mo
# is the costly part).
QUALITY = {
    "Fast — 720p, 30fps (recommended)": (1280, 720, 30.0),
    "High — 1080p, 60fps (slower)": (1920, 1080, 60.0),
}
BEATMATCH = "Beat-match — a kill on every beat (use several clips)"
FREEZE = "Freeze-finisher — one clutch into super slow-motion"


def _resolve_song(song_file: str | None, song_link: str | None) -> str:
    if song_link and song_link.strip():
        link = song_link.strip()
        if not is_url(link):
            raise gr.Error("The song link must start with http:// or https://")
        return str(fetch_audio(link))
    if song_file:
        return song_file
    raise gr.Error("Add a song: upload an audio file, or paste a YouTube / web link.")


def make_montage(clips, song_file, song_link, mode, look, quality, slowmo_len, caption):
    if not clips:
        raise gr.Error("Add at least one gameplay clip first.")
    width, height, fps = QUALITY.get(quality, next(iter(QUALITY.values())))
    work = Path(tempfile.mkdtemp(prefix="vm_work_"))
    out_path = str(Path(tempfile.mkdtemp(prefix="vm_out_")) / "montage.mp4")

    yield None, "🎵 Reading the song…"
    audio = _resolve_song(song_file, song_link)

    try:
        if mode == BEATMATCH:
            videos, kills_per = [], []
            for i, clip in enumerate(clips, 1):
                yield None, f"🔍 Finding your kills in clip {i} of {len(clips)}…"
                kills_per.append([round(k.time, 3) for k in detect_kills_by_highlight(clip)])
                videos.append(clip)
            total = sum(len(k) for k in kills_per)
            if not total:
                raise gr.Error("Couldn't find your kills in any clip. Turn on "
                               "'highlight my own kills' in Valorant's settings, "
                               "or try different clips.")
            yield None, (f"🎬 Found {total} kills across {len(videos)} clip(s). "
                         "Building your beat-matched montage — this takes a few "
                         "minutes on the free server, hang tight…")
            render_beatmatch(videos, audio, kills_per, out_path,
                             width=width, height=height, fps=fps, grade=look,
                             encoder="libx264", work_dir=str(work))
        else:
            clip = clips[0]
            extra = "" if len(clips) == 1 else " (freeze-finisher uses one clip — using the first)"
            yield None, f"🔍 Finding your kills{extra}…"
            detected = [round(k.time, 3) for k in detect_kills_by_highlight(clip)]
            if not detected:
                raise gr.Error("Couldn't find your kills in that clip. Turn on "
                               "'highlight my own kills' in Valorant's settings, "
                               "or try another clip.")
            kills = pick_highlight(detected)
            yield None, (f"🎬 Found {len(detected)} kills; using the best round "
                         f"({len(kills)}). Building your finisher — this takes a few "
                         "minutes on the free server, hang tight…")
            render_freeze_finisher(clip, audio, kills, out_path,
                                   width=width, height=height, fps=fps, grade=look,
                                   encoder="libx264", slowmo_dur=float(slowmo_len),
                                   caption=caption.strip(), work_dir=str(work))
    except gr.Error:
        raise
    except Exception as e:  # surface engine errors as a friendly toast
        raise gr.Error(f"Something went wrong while making the montage: {e}")

    yield out_path, "✅ Done! Tap to play, or use the video's ⋯ menu to download."


with gr.Blocks(title="Valorant Montage Maker") as demo:
    gr.Markdown(
        "# 🎬 Valorant Montage Maker\n"
        "Upload your clips, pick a song, and get a beat-synced highlight montage. "
        "Your kills are found automatically.\n\n"
        "*Free server: the first render after a quiet spell wakes it up (~30s), "
        "and each montage takes a few minutes (no gaming GPU here).*")

    clips = gr.File(label="Gameplay clip(s) — pick one, or several for beat-match",
                    file_count="multiple",
                    file_types=[".mp4", ".mov", ".mkv", ".avi", ".webm"],
                    type="filepath")
    with gr.Row():
        song_file = gr.File(label="Song — upload an audio file",
                            file_count="single",
                            file_types=[".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"],
                            type="filepath")
    song_link = gr.Textbox(label="…or paste a YouTube / web link instead",
                           placeholder="https://youtu.be/…")
    mode = gr.Radio([BEATMATCH, FREEZE], value=BEATMATCH, label="Style")

    with gr.Accordion("Options", open=False):
        look = gr.Dropdown(GRADES, value="teal_orange", label="Look")
        quality = gr.Dropdown(list(QUALITY), value=next(iter(QUALITY)), label="Quality")
        slowmo_len = gr.Slider(2, 8, value=4, step=0.5,
                               label="Freeze-finisher: slow-mo length (seconds)")
        caption = gr.Textbox(label="Freeze-finisher: banner over the finish "
                                   "(e.g. ACE, or 'auto'; leave blank for none)",
                             value="")

    go = gr.Button("🎬  Make Montage", variant="primary", size="lg")
    status = gr.Markdown("")
    out = gr.Video(label="Your montage")

    go.click(make_montage,
             inputs=[clips, song_file, song_link, mode, look, quality, slowmo_len, caption],
             outputs=[out, status])

demo.queue()  # one render at a time; keeps long jobs from timing out

if __name__ == "__main__":
    demo.launch()
