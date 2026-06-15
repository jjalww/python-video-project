# Putting the Montage Maker online (free) — step by step

This turns the four files in this folder into a real website you can open on
your phone. It's free, and the only thing I can't do for you is the clicking
in the browser — so here's exactly what to do. Takes about 10 minutes, most
of it waiting for the first build.

## What you'll have at the end
A web address like `https://huggingface.co/spaces/yourname/valorant-montage`
that you open on your phone, upload clips + a song, and download a montage.
Bookmark it / "Add to Home Screen" and it feels like an app.

---

## 1. Make a free Hugging Face account
Go to **<https://huggingface.co/join>** and sign up (email + password, or
Google). Hugging Face is a free home for AI/ML apps — like GitHub, but it can
actually *run* apps, which is the part GitHub can't do.

## 2. Create a new Space
1. Go to **<https://huggingface.co/new-space>**.
2. **Owner**: your username. **Space name**: `valorant-montage` (or anything).
3. **License**: leave as is (or pick "mit").
4. **Select the Space SDK**: click **Gradio**.
5. **Space hardware**: leave **CPU basic — Free**.
6. **Visibility**: **Public** is fine (only people you give the link to will
   bother visiting; the page itself shows nothing private).
7. Click **Create Space**.

## 3. Upload the four files
On your new Space page, click the **Files** tab → **+ Add file** →
**Upload files**. Drag in **all four** files from this `huggingface_space`
folder:

- `app.py`
- `requirements.txt`
- `packages.txt`
- `README.md`

Then click **Commit changes to main** at the bottom.

> Uploading `README.md` will replace the placeholder readme the Space created —
> that's expected and correct (it carries the Space's settings at the top).

## 4. Wait for it to build
The Space switches to **Building** and installs everything (FFmpeg, the
montage engine, its libraries). The **first** build takes a few minutes —
watch the **Logs**. When it says **Running**, you're live.

If the build ever fails, open the **Logs**, copy the red error text, and send
it to me — I'll fix it. (A common one: if it complains about the Gradio
version, it's a one-line tweak in `README.md`.)

## 5. Use it on your phone
Open the Space's URL on your phone. Tap to upload clip(s), add a song (upload
or paste a YouTube link), pick a style, and hit **Make Montage**. In Safari/
Chrome you can **Share → Add to Home Screen** so it sits next to your apps.

---

## Good to know
- **It naps when idle.** After a quiet spell the first visit takes ~30s to
  wake up, then it's responsive. That's normal for free Spaces.
- **Renders take a few minutes.** The free server has no gaming GPU, so it's
  slower than your PC. If you ever want it fast-anywhere, the Space's
  **Settings → Hardware** page rents a GPU by the hour (real money — only if
  you decide it's worth it).
- **Keeping it up to date.** When I improve the engine and you push to GitHub,
  open the Space → **Settings → Factory rebuild** to pull the latest.
- **Your clips/songs aren't stored.** They're processed for your render and
  not kept on the Space.
