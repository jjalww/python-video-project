"""Desktop UI for valmontage — pick a clip + song and click "Make Montage".
No command line needed.

Launch by double-clicking "Montage Maker.bat", or:  python app.py

Heavy imports (librosa / OpenCV / FFmpeg wrappers) are done lazily inside the
worker threads so the window opens instantly. The worker threads talk back to
the UI through a queue that the main thread drains on a timer — tkinter widgets
must only be touched from the main thread.
"""

from __future__ import annotations

import ctypes
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
VIDEO_TYPES = [("Video", "*.mp4 *.mov *.mkv *.avi"), ("All files", "*.*")]
AUDIO_TYPES = [("Audio", "*.wav *.mp3 *.flac *.m4a"), ("All files", "*.*")]

# --- dark palette -----------------------------------------------------------
BG = "#1a1d24"       # window / frames / labels
FIELD = "#262b34"    # entry & spinbox fields
FG = "#e7e9ed"       # primary text
MUTED = "#8b92a0"    # secondary text
ACCENT = "#ff4655"   # Valorant red — primary action
ACCENT_HI = "#ff5d6a"
TEAL = "#27c4a8"     # section headers / secondary
BORDER = "#333a45"
LOG_BG = "#0e1014"
LOG_FG = "#bfe3dc"
OK = "#3ad29f"
ERR = "#ff6b6b"


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
        root.minsize(720, 780)
        root.configure(bg=BG)
        self._setup_theme()

        main = ttk.Frame(root, padding=(18, 14))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        r = 0

        # --- header ------------------------------------------------------
        head = ttk.Frame(main)
        head.grid(row=r, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(head, text="🎬  Montage Maker", style="Title.TLabel").pack(anchor="w")
        ttk.Label(head, text="Turn your Valorant clips into a beat-synced highlight montage.",
                  style="Sub.TLabel").pack(anchor="w")
        r += 1

        # --- 1 · Footage -------------------------------------------------
        s1 = self._card(main, r, "1 · Footage")
        s1.columnconfigure(1, weight=1)
        self.clip = self._file_row(s1, 0, "Gameplay clip", "", VIDEO_TYPES)
        song0 = str(DEFAULT_SONG) if DEFAULT_SONG.exists() else ""
        self.song = self._file_row(s1, 1, "Song", song0, AUDIO_TYPES)
        ttk.Label(s1, text="Tip: paste a YouTube / web link in place of a file.",
                  style="Muted.TLabel").grid(row=2, column=1, columnspan=2, sticky="w", pady=(2, 0))
        r += 1

        # --- 2 · Your kills ---------------------------------------------
        s2 = self._card(main, r, "2 · Your kills")
        s2.columnconfigure(0, weight=1)
        self.kills = tk.Text(s2, height=3, wrap="word", relief="flat", bd=8,
                             bg=FIELD, fg=FG, insertbackground=FG,
                             font=("Consolas", 11), highlightthickness=1,
                             highlightbackground=BORDER, highlightcolor=TEAL)
        self.kills.grid(row=0, column=0, columnspan=3, sticky="ew")
        try:
            if DEFAULT_KILLS.exists():
                self.kills.insert("1.0", ", ".join(f"{t:g}" for t in load_kill_times(DEFAULT_KILLS)))
        except Exception:
            pass
        btns = ttk.Frame(s2)
        btns.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(btns, text="🔍  Detect my kills", command=self._detect,
                   style="Soft.TButton").pack(side="left")
        ttk.Button(btns, text="Load kills.json…", command=self._load_kills_json,
                   style="Soft.TButton").pack(side="left", padx=(8, 0))
        ttk.Label(s2, text="Edit the seconds above, detect them from the clip, or load a file.",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        r += 1

        # --- 3 · Style ---------------------------------------------------
        s3 = self._card(main, r, "3 · Style")
        s3.columnconfigure(1, weight=1)
        self.mode = tk.StringVar(value="beatmatch")
        ttk.Radiobutton(s3, text="Beat-match  —  cuts land on the beat, slow-motion finisher",
                        variable=self.mode, value="beatmatch", command=self._sync_mode,
                        style="TRadiobutton").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(s3, text="Freeze-finisher  —  plays past the last kill, freezes as the song ends",
                        variable=self.mode, value="freeze_finisher", command=self._sync_mode,
                        style="TRadiobutton").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 6))

        ttk.Label(s3, text="Look").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.grade = tk.StringVar(value="teal_orange")
        ttk.Combobox(s3, textvariable=self.grade, values=GRADES, width=16,
                     state="readonly").grid(row=2, column=1, sticky="w", pady=4)
        self.vignette = tk.BooleanVar(value=False)
        ttk.Checkbutton(s3, text="Vignette", variable=self.vignette).grid(
            row=2, column=2, sticky="e", pady=4)

        self.show_adv = tk.BooleanVar(value=False)
        ttk.Checkbutton(s3, text="Advanced settings  (off = everything auto)",
                        variable=self.show_adv, command=self._toggle_adv).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.adv = ttk.Frame(s3, padding=(2, 8))
        self.adv.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.adv.columnconfigure(0, weight=1)

        shared = ttk.Frame(self.adv)
        shared.grid(row=0, column=0, sticky="ew")
        shared.columnconfigure(3, weight=1)
        self.pre_roll = self._spin(shared, 0, 0, "Pre-roll (s)", 0.25, 0, 1.0, 0.05)
        ttk.Label(shared, text="Beats per clip").grid(row=0, column=2, sticky="e", padx=(16, 6), pady=4)
        self.bpc = tk.StringVar(value="Auto")
        ttk.Combobox(shared, textvariable=self.bpc, width=8, state="readonly",
                     values=["Auto", "1", "2", "3", "4", "5", "6"]).grid(
            row=0, column=3, sticky="w", pady=4)

        # mode-specific controls live in two frames stacked in the same cell;
        # _sync_mode shows whichever one matches the chosen style.
        self.adv_bm = ttk.Frame(self.adv)
        self.adv_bm.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(self.adv_bm, text="BEAT-MATCH", style="Tag.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w")
        self.intro = self._spin(self.adv_bm, 1, 0, "Intro length (s)", 5.0, 0, 15, 0.5)
        self.finisher = self._spin(self.adv_bm, 1, 2, "Finisher speed (lower=slower)", 0.40, 0.20, 1.0, 0.05)
        self.zoom = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.adv_bm, text="Zoom punches", variable=self.zoom).grid(
            row=2, column=0, sticky="w", padx=6, pady=4)

        self.adv_ff = ttk.Frame(self.adv)
        self.adv_ff.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(self.adv_ff, text="FREEZE-FINISHER", style="Tag.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w")
        self.aftermath = self._spin(self.adv_ff, 1, 0, "Play-out after kill (s)", 5.0, 0, 15, 0.5)
        self.freeze_dur = self._spin(self.adv_ff, 1, 2, "Freeze hold (s)", 3.0, 1.0, 8.0, 0.5)
        ttk.Label(self.adv_ff, text="Caption").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.caption = tk.StringVar(value="")   # blank = no banner (type ACE, or "auto")
        ttk.Entry(self.adv_ff, textvariable=self.caption, width=14).grid(
            row=2, column=1, sticky="w", pady=4)
        self.spotlight = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.adv_ff, text="Spotlight", variable=self.spotlight).grid(
            row=2, column=2, sticky="w", padx=6, pady=4)

        self.adv.grid_remove()  # hidden until ticked
        r += 1

        # --- 4 · Render --------------------------------------------------
        s4 = self._card(main, r, "4 · Render")
        s4.columnconfigure(1, weight=1)
        self.out = self._file_row(s4, 0, "Save to", str(DEFAULT_OUT), [("MP4", "*.mp4")], save=True)
        self.go = ttk.Button(s4, text="🎬   Make Montage", command=self._render, style="Accent.TButton")
        self.go.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        self.status = ttk.Label(s4, text="Ready.", style="Muted.TLabel")
        self.status.grid(row=2, column=0, columnspan=3, sticky="w")
        main.rowconfigure(r, weight=1)
        s4.rowconfigure(3, weight=1)
        self.log = tk.Text(s4, height=10, wrap="word", state="disabled", relief="flat",
                           bd=8, bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
                           font=("Consolas", 9), highlightthickness=1, highlightbackground=BORDER)
        self.log.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        r += 1

        self._sync_mode()
        self.root.after(100, self._drain)
        self.root.after(60, self._dark_titlebar)

    # ---- theming --------------------------------------------------------
    def _setup_theme(self) -> None:
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", TEAL)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#0e1014")

        st.configure(".", background=BG, foreground=FG, fieldbackground=FIELD,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                     troughcolor=FIELD, font=("Segoe UI", 10))
        st.configure("TFrame", background=BG)
        st.configure("Inset.TFrame", background=BG)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Muted.TLabel", background=BG, foreground=MUTED)
        st.configure("Tag.TLabel", background=BG, foreground=TEAL,
                     font=("Segoe UI Semibold", 9))
        st.configure("Title.TLabel", background=BG, foreground=FG,
                     font=("Segoe UI Semibold", 19))
        st.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        st.configure("TLabelframe", background=BG, bordercolor=BORDER,
                     relief="solid", borderwidth=1)
        st.configure("TLabelframe.Label", background=BG, foreground=TEAL,
                     font=("Segoe UI Semibold", 11))

        st.configure("TButton", background=FIELD, foreground=FG, bordercolor=BORDER,
                     focuscolor=BG, padding=6, relief="flat")
        st.map("TButton", background=[("active", "#313844"), ("disabled", "#22262e")])
        st.configure("Soft.TButton", background=FIELD, foreground=FG, padding=7, relief="flat")
        st.map("Soft.TButton", background=[("active", "#313844")])
        st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                     font=("Segoe UI Semibold", 13), padding=12, relief="flat", borderwidth=0)
        st.map("Accent.TButton",
               background=[("active", ACCENT_HI), ("disabled", "#5b3338")],
               foreground=[("disabled", "#d6d9df")])

        st.configure("TEntry", fieldbackground=FIELD, foreground=FG, bordercolor=BORDER,
                     insertcolor=FG, padding=5, relief="flat")
        st.map("TEntry", bordercolor=[("focus", TEAL)])
        st.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG,
                     arrowcolor=FG, bordercolor=BORDER, padding=4, relief="flat")
        st.map("TCombobox", fieldbackground=[("readonly", FIELD)],
               foreground=[("readonly", FG)], background=[("readonly", FIELD)])
        st.configure("TCheckbutton", background=BG, foreground=FG, focuscolor=BG)
        st.map("TCheckbutton", background=[("active", BG)],
               indicatorcolor=[("selected", TEAL), ("!selected", FIELD)])
        st.configure("TRadiobutton", background=BG, foreground=FG, focuscolor=BG)
        st.map("TRadiobutton", background=[("active", BG)],
               indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])
        st.configure("TSpinbox", fieldbackground=FIELD, foreground=FG, arrowcolor=FG,
                     bordercolor=BORDER, insertcolor=FG, padding=3, relief="flat")
        st.map("TSpinbox", bordercolor=[("focus", TEAL)])

    def _dark_titlebar(self) -> None:
        """Match the Windows 11 title bar to the dark UI (best-effort)."""
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass

    # ---- small widget builders -----------------------------------------
    def _card(self, parent, row, title) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text=f"  {title}  ", padding=12)
        f.grid(row=row, column=0, sticky="nsew", pady=6)
        return f

    def _file_row(self, parent, r, label, value, types, save=False):
        ttk.Label(parent, text=label, width=12, anchor="w").grid(
            row=r, column=0, sticky="w", pady=5)
        var = tk.StringVar(value=value)
        ttk.Entry(parent, textvariable=var).grid(row=r, column=1, sticky="ew", pady=5, padx=(0, 8))

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

        ttk.Button(parent, text="Browse…", command=browse, style="Soft.TButton").grid(
            row=r, column=2, pady=5)
        return var

    def _toggle_adv(self):
        self.adv.grid() if self.show_adv.get() else self.adv.grid_remove()

    def _sync_mode(self):
        """Show only the advanced controls that apply to the chosen mode."""
        if self.mode.get() == "freeze_finisher":
            self.adv_bm.grid_remove()
            self.adv_ff.grid()
        else:
            self.adv_ff.grid_remove()
            self.adv_bm.grid()

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
        self.status.config(text=f"Loaded {len(times)} kills from {Path(p).name}.", foreground=OK)

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
                pre_roll=float(self.pre_roll.get()),
                intro_dur=float(self.intro.get()),
                finisher_factor=float(self.finisher.get()),
                aftermath_dur=float(self.aftermath.get()),
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
            zoom=bool(self.zoom.get()),
            spotlight=bool(self.spotlight.get()), caption=self.caption.get().strip(),
            **numbers,
        )
        self._start(self._work_render, params)

    # ---- threading glue -------------------------------------------------
    def _start(self, fn, *args):
        if self.busy:
            return
        self.busy = True
        self.go.config(state="disabled")
        self.status.config(text="Working…", foreground=TEAL)
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
                aftermath_dur=params["aftermath_dur"], freeze_dur=params["freeze_dur"],
                spotlight=params["spotlight"], caption=params["caption"],
                **common)
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
            print(f"Scanning {video} for your killfeed highlights… (no agent needed)")
            kills = detect_kills_by_highlight(video)
            print(f"Detected {len(kills)} of your kills.")
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
                    self.status.config(text=f"Detected {len(payload)} of your kills.", foreground=OK)
                    self._finish()
                elif kind == "done":
                    self.status.config(text=f"Done → {payload}", foreground=OK)
                    self._finish()
                    self._open_result(payload)
                elif kind == "error":
                    self.status.config(text=f"Error: {payload}", foreground=ERR)
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
    MontageApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
