"""Optional Tkinter desktop interface."""

import json
import queue
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

from .config import DEFAULT_VOICE_REF, VOICE_PRESETS, VOICE_STYLES
from .pipeline import run_voice_only
from .story import check_segments, export_prompts


class ScrollableFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
    def _wheel(self, e):
        d = e.delta
        if abs(d) >= 120: d = int(d / 120)
        self.canvas.yview_scroll(-d, "units")


class App:
    def __init__(self, root):
        self.root = root
        root.title("🎙 Horror Voice Studio - Parallel Mode")
        root.geometry("760x820")
        self.q = queue.Queue()

        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="both")
        self.bar = ttk.Progressbar(bottom, mode="determinate")
        self.bar.pack(fill="x", padx=8, pady=(6, 2))
        self.log_box = scrolledtext.ScrolledText(bottom, height=10, font=("Menlo", 9))
        self.log_box.pack(fill="both", padx=8, pady=(0, 8))

        self.sf = ScrollableFrame(root)
        self.sf.pack(side="top", fill="both", expand=True)
        host = self.sf.body
        host.columnconfigure(1, weight=1)
        pad = {"padx": 8, "pady": 3}
        r = 0

        def head(t):
            nonlocal r
            ttk.Label(host, text=t, font=("Helvetica", 11, "bold")).grid(
                row=r, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2))
            r += 1

        def filerow(label, var, kind):
            nonlocal r
            ttk.Label(host, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(host, textvariable=var).grid(row=r, column=1, sticky="ew", **pad)
            ttk.Button(host, text="Browse", command=lambda: self.browse(var, kind)).grid(row=r, column=2, **pad)
            r += 1

        def entryrow(label, var, w=12):
            nonlocal r
            ttk.Label(host, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(host, textvariable=var, width=w).grid(row=r, column=1, sticky="w", **pad)
            r += 1

        def checkrow(label, var):
            nonlocal r
            ttk.Checkbutton(host, text=label, variable=var).grid(
                row=r, column=0, columnspan=3, sticky="w", **pad)
            r += 1

        def combo(label, var, vals):
            nonlocal r
            ttk.Label(host, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Combobox(host, textvariable=var, width=25, state="readonly", values=vals).grid(
                row=r, column=1, sticky="w", **pad)
            r += 1

        head("Story")
        self.json = tk.StringVar()
        filerow("Story JSON", self.json, "json")
        self.prompts_out = tk.StringVar(value="scene_prompts.txt")
        filerow("Image-prompts output (.txt)", self.prompts_out, "savetxt")
        ttk.Button(host, text="Export scene image prompts (for AI tools)",
                   command=self.do_prompts).grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        r += 1
        ttk.Button(host, text="Check segments (duration & media)",
                   command=self.do_check).grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        r += 1

        head("Voice [Chatterbox Local / VoxCPM2 + edge-tts Fallback]")
        self.voice_source = tk.StringVar(value="generate")
        combo("Voice source", self.voice_source, ["generate", "existing"])
        self.voice_backend = tk.StringVar(value="chatterbox")
        combo("Generated voice backend", self.voice_backend, ["chatterbox", "voxcpm2"])

        self.voice_preset = tk.StringVar(value="Balanced Neutral")
        combo("Voice Preset", self.voice_preset, list(VOICE_PRESETS.keys()))

        self.voice_style = tk.StringVar(value="Balanced")
        combo("Voice Style", self.voice_style, list(VOICE_STYLES.keys()))

        self.voice_ref = tk.StringVar(value=DEFAULT_VOICE_REF)
        filerow("Reference voice (wav/mp3 — optional)", self.voice_ref, "audio")
        self.voice_file = tk.StringVar()
        filerow("...or existing voice mp3/wav (source=existing)", self.voice_file, "audio")

        head("VoxCPM2 Advanced Settings")
        self.cfg_value = tk.StringVar(value="2.0")
        entryrow("CFG Guidance (English: 2.0; Khmer: 1.6-1.8)", self.cfg_value, 8)
        self.do_normalize = tk.BooleanVar(value=False)
        checkrow("Text Normalization", self.do_normalize)
        self.denoise = tk.BooleanVar(value=True)
        checkrow("Reference Audio Enhancement (denoising)", self.denoise)

        self.max_workers = tk.StringVar(value="2")
        entryrow("Parallel workers (1–2 recommended)", self.max_workers, 6)

        head("Chatterbox Local Settings")
        self.chatterbox_device = tk.StringVar(value="auto")
        combo("Compute device", self.chatterbox_device, ["auto", "mps", "cuda", "cpu"])
        self.chatterbox_exaggeration = tk.StringVar(value="0.5")
        entryrow("Emotion exaggeration (0–2)", self.chatterbox_exaggeration, 8)
        self.chatterbox_cfg_weight = tk.StringVar(value="0.5")
        entryrow("CFG weight (0–1)", self.chatterbox_cfg_weight, 8)

        head("Background Audio")
        self.bg_music = tk.StringVar()
        filerow("Background music (optional)", self.bg_music, "audio")
        self.bg_percent = tk.StringVar(value="0.18")
        entryrow("Music level (0.18)", self.bg_percent, 8)
        self.auto_amb = tk.BooleanVar(value=False)
        checkrow("Auto background ambience (generated, if no music file)", self.auto_amb)
        self.voice_out = tk.StringVar(value="voice_final.mp3")
        filerow("Voice output (.mp3)", self.voice_out, "savemp3")

        self.segments_output = tk.StringVar(value="segments_audio")
        filerow("Segments output folder (save individual MP3s)", self.segments_output, "folder")

        ttk.Button(host, text="🎙  Generate voice (.mp3) only  — PARALLEL",
                   command=self.start_voice).grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=6)
        r += 1
        ttk.Label(host, text="").grid(row=r, column=0, pady=4)
        self.root.after(100, self.drain)

    def browse(self, var, kind):
        if kind == "json":
            p = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")])
        elif kind == "audio":
            p = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav *.m4a"), ("All", "*.*")])
        elif kind == "folder":
            p = filedialog.askdirectory()
        elif kind == "savetxt":
            p = filedialog.asksaveasfilename(defaultextension=".txt")
        elif kind == "savemp3":
            p = filedialog.asksaveasfilename(defaultextension=".mp3")
        else:
            p = filedialog.asksaveasfilename()
        if p:
            var.set(p)

    def do_check(self):
        if not self.json.get():
            self.log("❌ Choose a Story JSON first.")
            return
        try:
            data = json.load(open(self.json.get(), encoding="utf-8"))
            self.log_box.delete("1.0", tk.END)
            check_segments(data, self.log)
        except Exception as e:
            self.log("❌ " + str(e))

    def do_prompts(self):
        if not self.json.get():
            self.log("❌ Choose a Story JSON first.")
            return
        def run():
            try:
                data = json.load(open(self.json.get(), encoding="utf-8"))
                export_prompts(data, self.prompts_out.get() or "scene_prompts.txt", self.log)
            except Exception as e:
                self.log("❌ " + str(e))
        threading.Thread(target=run, daemon=True).start()

    def log(self, m):
        self.q.put(str(m))

    def progress(self, v):
        self.q.put(("P", v))

    def drain(self):
        while not self.q.empty():
            it = self.q.get()
            if isinstance(it, tuple):
                self.bar["value"] = it[1]
            else:
                self.log_box.insert(tk.END, it + "\n")
                self.log_box.see(tk.END)
        self.root.after(100, self.drain)

    def f(self, v, d):
        try:
            return float(v.get())
        except ValueError:
            return d

    def _cfg(self):
        return {
            "json": self.json.get(),
            "voice_source": self.voice_source.get(),
            "voice_backend": self.voice_backend.get(),
            "voice_preset": self.voice_preset.get(),
            "voice_style": self.voice_style.get(),
            "voice_ref": self.voice_ref.get(),
            "voice_file": self.voice_file.get(),
            "cfg_value": self.f(self.cfg_value, 2.0),
            "do_normalize": self.do_normalize.get(),
            "denoise": self.denoise.get(),
            "max_workers": int(self.f(self.max_workers, 4)),
            "chatterbox_device": self.chatterbox_device.get(),
            "chatterbox_exaggeration": self.f(self.chatterbox_exaggeration, 0.5),
            "chatterbox_cfg_weight": self.f(self.chatterbox_cfg_weight, 0.5),
            "bg_music": self.bg_music.get(),
            "bg_percent": self.f(self.bg_percent, 0.18),
            "voice_out": self.voice_out.get() or "voice_final.mp3",
            "segments_output": self.segments_output.get() or "segments_audio",
            "auto_amb": self.auto_amb.get(),
        }

    def start_voice(self):
        if not self.json.get():
            self.log("❌ Choose a Story JSON.")
            return
        cfg = self._cfg()
        self.bar["value"] = 0
        self.log_box.delete("1.0", tk.END)
        def run():
            try:
                run_voice_only(cfg, self.log, self.progress)
            except Exception:
                self.log("❌ ERROR:\n" + traceback.format_exc())
        threading.Thread(target=run, daemon=True).start()
