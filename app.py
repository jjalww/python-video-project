"""Desktop UI for valmontage — pick a clip + song, tweak a few sliders, and
click "Make Montage". No command line needed.

Launch by double-clicking "Montage Maker.bat", or:  python app.py

Heavy imports (librosa / OpenCV / FFmpeg wrappers) are done lazily inside the
worker threads so the window opens instantly. The worker threads talk back to
the UI through a queue that the main thread drains on a timer — tkinter widgets
must only be touched from the main thread.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

PROJECT = Path(__file__).resolve().parent
DEFAULT_SONG = PROJECT / "samples" / "song.wav"
DEFAULT_KILLS = PROJECT / "output" / "kills.json"
DEFAULT_OUT = PROJECT / "output" / "montage.mp4"
GRADES = ["teal_orange", "contrast_boost", "vignette_only", "none"]


def load_kill_times(path: str | Path) -> list[float]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        return [k["time"] for k in data.get("kills", [])]
    return [float(t) for t in data]


def parse_kill_times(text: str) -> list[float]:
    """Accept timestamps separated by commas, spaces, or newlines."""
    raw = text.replace(",", " ").split()
    return [float(t) for t in raw]


def unique_path(path: str | Path) -> Path:
    """Return a non-clobbering path so renders never overwrite each other:
    montage.mp4 -> montage 2.mp4 -> montage 3.mp4 ... A trailing number on the
    name is treated as the counter, so it doesn't pile up ("montage 2 2.mp4").
    """
    path = Path(path)
    if not path.exists():
        return path
    parent, suffix, stem = path.parent, path.suffix, path.stem
    head, _, tail = stem.rpartition(" ")
    base = head if head and tail.isdigit() else stem
    n = 2
    while (parent / f"{base} {n}{suffix}").exists():
        n += 1
    return parent / f"{base} {n}{suffix}"


class MontageApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        root.title("valmontage — Montage Maker")
        root.minsize(640, 640)

        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(frm, text="Make a beat-synced montage",
                  font=("Segoe UI", 14, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1

        # --- mode --------------------------------------------------------
        self.mode = tk.StringVar(value="beatmatch")
        mf = ttk.Frame(frm)
        mf.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(mf, text="Style:").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(mf, text="Beat-match (cut to the beat)",
                        variable=self.mode, value="beatmatch").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(mf, text="Freeze-finisher (freeze on the final kill)",
                        variable=self.mode, value="freeze_finisher").pack(side="left")
        row += 1

        # --- files -------------------------------------------------------
        self.clip = self._file_row(frm, row, "Gameplay clip", "",
                                   [("Video", "*.mp4 *.mov *.mkv *.avi"), ("All", "*.*")])
        row += 1
        song0 = str(DEFAULT_SONG) if DEFAULT_SONG.exists() else ""
        self.song = self._file_row(frm, row, "Song", song0,
                                   [("Audio", "*.wav *.mp3 *.flac *.m4a"), ("All", "*.*")])
        row += 1
        ttk.Label(frm, text="Tip: you can paste a YouTube/web link instead of browsing for a file.",
                  foreground="#777").grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        # --- kills -------------------------------------------------------
        kf = ttk.LabelFrame(frm, text="Kill timestamps (seconds)", padding=8)
        kf.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        kf.columnconfigure(0, weight=1)
        self.kills = tk.Text(kf, height=3, wrap="word")
        self.kills.grid(row=0, column=0, columnspan=4, sticky="ew")
        try:
            if DEFAULT_KILLS.exists():
                self.kills.insert("1.0", ", ".join(f"{t:g}" for t in load_kill_times(DEFAULT_KILLS)))
        except Exception:
            pass
        ttk.Label(kf, text="Edit the numbers above, or:").grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(kf, text="🔍  Detect kills from clip", command=self._detect).grid(
            row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Button(kf, text="Load kills.json…", command=self._load_kills_json).grid(
            row=1, column=2, sticky="w", padx=(6, 0), pady=(6, 0))
        row += 1

        # --- settings (auto by default; revealed only on request) --------
        self.show_adv = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="⚙  Advanced settings  (leave off — everything is auto)",
                        variable=self.show_adv, command=self._toggle_adv).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(2, 0))
        row += 1
        self.adv = ttk.LabelFrame(frm, text="Advanced", padding=8)
        self.adv.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        for c in (1, 3):
            self.adv.columnconfigure(c, weight=1)
        self.intro = self._spin(self.adv, 0, 0, "Intro length (s)", 5.0, 0, 15, 0.5)
        self.pre_roll = self._spin(self.adv, 0, 2, "Pre-roll (s)", 0.25, 0, 1.0, 0.05)
        self.finisher = self._spin(self.adv, 1, 0, "Finisher speed (lower=slower)", 0.40, 0.20, 1.0, 0.05)
        ttk.Label(self.adv, text="Beats per clip").grid(row=1, column=2, sticky="e", padx=6, pady=4)
        self.bpc = tk.StringVar(value="Auto")
        ttk.Combobox(self.adv, textvariable=self.bpc, width=8, state="readonly",
                     values=["Auto", "1", "2", "3", "4", "5", "6"]).grid(
            row=1, column=3, sticky="w", pady=4)
        ttk.Label(self.adv, text="Grade").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.grade = tk.StringVar(value="teal_orange")
        ttk.Combobox(self.adv, textvariable=self.grade, values=GRADES, width=14,
                     state="readonly").grid(row=2, column=1, sticky="w", pady=4)
        self.vignette = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.adv, text="Vignette", variable=self.vignette).grid(
            row=2, column=2, sticky="w", padx=6, pady=4)
        self.zoom = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.adv, text="Zoom punches (off)", variable=self.zoom).grid(
            row=2, column=3, sticky="w", padx=6, pady=4)
        self.freeze_dur = self._spin(self.adv, 3, 0, "Freeze hold (s)", 2.5, 1.0, 6.0, 0.5)
        self.adv.grid_remove()  # hidden until the box is ticked
        row += 1

        # --- output ------------------------------------------------------
        self.out = self._file_row(frm, row, "Save montage to", str(DEFAULT_OUT),
                                  [("MP4", "*.mp4")], save=True)
        row += 1

        # --- action + log ------------------------------------------------
        self.go = ttk.Button(frm, text="🎬  Make Montage", command=self._render)
        self.go.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        row += 1
        self.status = ttk.Label(frm, text="Ready.", foreground="#555")
        self.status.grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        frm.rowconfigure(row, weight=1)
        self.log = tk.Text(frm, height=12, wrap="word", state="disabled",
                           bg="#101317", fg="#cfe", insertbackground="#cfe")
        self.log.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(6, 0))

        self.root.after(100, self._drain)

    # ---- small widget builders -----------------------------------------
    def _file_row(self, parent, r, label, value, types, save=False):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="e", padx=8, pady=4)
        var = tk.StringVar(value=value)
        ttk.Entry(parent, textvariable=var).grid(row=r, column=1, sticky="ew", pady=4)

        def browse():
            cur = var.get().strip()
            start = str(Path(cur).parent) if cur and Path(cur).parent.exists() else str(PROJECT)
            if save:
                p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                                 initialdir=start, filetypes=types)
            else:
                p = filedialog.askopenfilename(initialdir=start, filetypes=types)
            if p:
                var.set(p)

        ttk.Button(parent, text="Browse…", command=browse).grid(row=r, column=2, padx=8, pady=4)
        return var

    def _toggle_adv(self):
        self.adv.grid() if self.show_adv.get() else self.adv.grid_remove()

    def _spin(self, parent, r, c, label, value, lo, hi, step):
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="e", padx=6, pady=4)
        var = tk.DoubleVar(value=value)
        ttk.Spinbox(parent, textvariable=var, from_=lo, to=hi, increment=step,
                    width=8).grid(row=r, column=c + 1, sticky="w", pady=4)
        return var

    # ---- actions --------------------------------------------------------
    def _load_kills_json(self):
        start = DEFAULT_KILLS.parent if DEFAULT_KILLS.parent.exists() else PROJECT
        p = filedialog.askopenfilename(
            title="Choose a kills.json file",
            initialdir=str(start),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not p:
            return
        try:
            times = load_kill_times(p)
        except Exception as e:
            messagebox.showerror("Couldn't read kills file", str(e))
            return
        self._set_kills(times)
        self.status.config(text=f"Loaded {len(times)} kills from {Path(p).name}.", foreground="#176")

    def _set_kills(self, times):
        self.kills.delete("1.0", "end")
        self.kills.insert("1.0", ", ".join(f"{t:g}" for t in times))

    def _detect(self):
        clip = self.clip.get().strip()
        if not clip:
            messagebox.showwarning("Pick a clip", "Choose your gameplay clip first.")
            return
        self._start(self._work_detect, clip)

    def _render(self):
        clip = self.clip.get().strip()
        song = self.song.get().strip()
        out = self.out.get().strip()
        if not clip or not song or not out:
            messagebox.showwarning("Missing files", "Pick a clip, a song, and an output path.")
            return
        try:
            kills = parse_kill_times(self.kills.get("1.0", "end"))
        except ValueError:
            messagebox.showerror("Bad timestamps", "Kill timestamps must be numbers like: 9.4, 12.0, 15.6")
            return
        if not kills:
            messagebox.showwarning("No kills", "Add kill timestamps, load a kills.json, or detect from the clip.")
            return
        # The Advanced spinboxes are editable, so a cleared/garbled value makes
        # .get() raise. Read them here (before touching anything) and report it
        # instead of letting the click silently do nothing.
        try:
            bpc = None if self.bpc.get() == "Auto" else int(self.bpc.get())
            numbers = dict(
                beats_per_clip=bpc,
                intro_dur=float(self.intro.get()),
                pre_roll=float(self.pre_roll.get()),
                finisher_factor=float(self.finisher.get()),
                freeze_dur=float(self.freeze_dur.get()),
            )
        except (ValueError, tk.TclError):
            messagebox.showerror("Bad number", "Advanced settings must be numbers.")
            return
        out = str(unique_path(out))   # never overwrite a previous montage
        self.out.set(out)             # show where it will actually be saved
        params = dict(
            mode=self.mode.get(),
            video=clip, audio=song, kills=kills, out_path=out,
            grade=self.grade.get(), vignette=bool(self.vignette.get()),
            zoom=bool(self.zoom.get()), **numbers,
        )
        self._start(self._work_render, params)

    # ---- threading glue -------------------------------------------------
    def _start(self, fn, *args):
        if self.busy:
            return
        self.busy = True
        self.go.config(state="disabled")
        self._clear_log()
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _work_render(self, params):
        out = self._capture_stdout(lambda: self._do_render(params))
        if out is not None:
            self.q.put(("done", str(out)))

    def _do_render(self, params):
        from valmontage.utils.fetch import fetch_audio, fetch_video, is_url
        if is_url(params["video"]):
            print("Downloading gameplay clip…")
        video = str(fetch_video(params["video"]))
        if is_url(params["audio"]):
            print("Downloading song…")
        audio = str(fetch_audio(params["audio"]))
        common = dict(grade=params["grade"], vignette=params["vignette"],
                      beats_per_clip=params["beats_per_clip"], pre_roll=params["pre_roll"])
        if params["mode"] == "freeze_finisher":
            from valmontage.modes.freeze_finisher import render_freeze_finisher
            return render_freeze_finisher(
                video, audio, params["kills"], params["out_path"],
                freeze_dur=params["freeze_dur"], **common)
        from valmontage.modes.beatmatch import render_beatmatch
        return render_beatmatch(
            video, audio, params["kills"], params["out_path"],
            zoom=params["zoom"], intro_dur=params["intro_dur"],
            finisher_factor=params["finisher_factor"], **common)

    def _work_detect(self, clip):
        def run():
            from valmontage.killdetect.highlight import detect_kills_by_highlight
            from valmontage.utils.fetch import fetch_video, is_url
            if is_url(clip):
                print("Downloading gameplay clip…")
            video = str(fetch_video(clip))
            print(f"Scanning {video} for highlighted killfeed rows… (no agent needed)")
            kills = detect_kills_by_highlight(video)
            print(f"Detected {len(kills)} kills.")
            return [round(k.time, 3) for k in kills]

        times = self._capture_stdout(run)
        if times is not None:
            self.q.put(("kills", times))

    def _capture_stdout(self, fn):
        """Run fn with stdout mirrored into the in-app log; report errors."""
        proxy = _QueueWriter(self.q)
        old = sys.stdout
        sys.stdout = proxy
        try:
            return fn()
        except Exception as e:
            self.q.put(("log", "\n" + traceback.format_exc()))
            self.q.put(("error", str(e)))
            return None
        finally:
            sys.stdout = old

    # ---- UI updates on the main thread ---------------------------------
    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append(payload)
                elif kind == "kills":
                    self._set_kills(payload)
                    self.status.config(text=f"Detected {len(payload)} kills.", foreground="#176")
                    self._finish()
                elif kind == "done":
                    self.status.config(text=f"Done → {payload}", foreground="#176")
                    self._finish()
                    self._open_result(payload)
                elif kind == "error":
                    self.status.config(text=f"Error: {payload}", foreground="#b00")
                    self._finish()
                    messagebox.showerror("Something went wrong", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _finish(self):
        self.busy = False
        self.go.config(state="normal")

    def _open_result(self, path):
        p = Path(path)
        if p.exists() and hasattr(os, "startfile"):
            try:
                os.startfile(str(p))            # noqa: S606 — play the montage
                os.startfile(str(p.parent))     # and show it in Explorer
            except Exception:
                pass

    def _append(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")


class _QueueWriter:
    """File-like object that forwards writes to the UI queue as log lines."""

    def __init__(self, q: queue.Queue) -> None:
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(("log", s))
        return len(s)

    def flush(self) -> None:
        pass


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    MontageApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
