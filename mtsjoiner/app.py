"""Окно программы MTS Joiner (tkinter)."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, avchd, core
from .i18n import HELP, LANGS, T, detect_lang, get_lang, set_lang

APP_NAME = "MTS Joiner"
SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home())) / "MtsJoiner" / "settings.json"
CHECK_ON, CHECK_OFF = "☑", "☐"
FFMPEG_PAGE = "https://www.gyan.dev/ffmpeg/builds/"
CREATE_NEW_CONSOLE = 0x00000010

VIDEO_KEYS = ["copy", "h264", "hevc"]
AUDIO_KEYS = ["pcm", "copy", "aac"]
HEIGHT_KEYS = [0, 1080, 720, -1]
KBPS_CHOICES = ["128", "192", "256", "320", "384", "512"]


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def video_label(k): return T(f"video.{k}")
def audio_label(k): return T(f"audio.{k}")
def height_label(k): return T(f"height.{k}")


def key_by_label(keys, label_fn, label):
    return next((k for k in keys if label_fn(k) == label), keys[0])


class Tooltip:
    """Всплывающая подсказка при наведении мыши."""

    def __init__(self, widget, key: str):
        self.widget, self.key = widget, key
        self.tip: tk.Toplevel | None = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self.after_id = self.widget.after(450, self._show)

    def _cancel(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def _show(self):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        tk.Label(tw, text=T(self.key), justify="left", wraplength=460, background="#fffbe6",
                 foreground="#222222", relief="solid", borderwidth=1, padx=8, pady=5,
                 font=("Segoe UI", 9)).pack()
        tw.update_idletasks()
        sw = self.widget.winfo_screenwidth()
        x = min(x, sw - tw.winfo_width() - 10)
        tw.wm_geometry(f"+{x}+{y}")

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        s = self.settings = load_settings()
        set_lang(s.get("lang") or detect_lang())
        self.takes: list[core.Take] = []
        self.ff: tuple[str, str | None] | None = None
        self.ff_ver = ""
        self.encoders: dict[str, list[str]] = {}
        self.msgs: queue.Queue = queue.Queue()
        self.runner: core.Runner | None = None
        self.busy = False
        self._applying = False
        self._ff_manual = bool(s.get("ffmpeg_manual"))
        self.saved_encoder = s.get("encoder", "")
        self.preset_key = s.get("preset", "premiere")
        self.log_lines: list[str] = []

        d = core.Options()
        self.var_src = tk.StringVar(value=s.get("src", ""))
        self.var_meta = tk.StringVar(value=s.get("meta", ""))
        self.var_out = tk.StringVar(value=s.get("out", ""))
        self.var_out_auto = tk.BooleanVar(value=s.get("out_auto", True))
        self.var_ffmpeg = tk.StringVar(value=s.get("ffmpeg_manual", ""))
        self.var_mode = tk.StringVar(value=s.get("mode", "per_take"))
        self.var_lang = tk.StringVar(value=LANGS[get_lang()])
        self.var_preset = tk.StringVar()
        self.var_container = tk.StringVar(value=s.get("container", d.container))
        self.var_video = tk.StringVar()
        self.var_encoder = tk.StringVar()
        self.var_rate = tk.StringVar(value=s.get("rate_mode", d.rate_mode))
        self.var_quality = tk.IntVar(value=s.get("quality", d.quality))
        self.var_size = tk.IntVar(value=s.get("size_limit_mb", d.size_limit_mb))
        self.var_height = tk.StringVar()
        self.var_audio = tk.StringVar()
        self.var_kbps = tk.StringVar(value=str(s.get("audio_kbps", d.audio_kbps)))
        self.var_stereo = tk.BooleanVar(value=s.get("stereo", d.stereo))
        self.var_faststart = tk.BooleanVar(value=s.get("faststart", d.faststart))
        self.var_proxies = tk.BooleanVar(value=s.get("proxies", False))
        self.var_status = tk.StringVar()
        self.var_meta_info = tk.StringVar()
        self.var_ff_info = tk.StringVar()
        self._keys = dict(video=s.get("video", d.video), audio=s.get("audio", d.audio),
                          height=s.get("height", d.height))

        self._build_all()
        if self.preset_key != core.CUSTOM_PRESET:
            self._apply_preset(self.preset_key)
        self._fit_window(initial=True)
        self._detect_ffmpeg(initial=True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        if self.var_src.get() and Path(self.var_src.get()).is_dir():
            self.after(300, self.scan)

    # ================================================================== построение окна
    def _build_all(self):
        """(Пере)строить всё окно — вызывается и при смене языка."""
        for w in self.winfo_children():
            w.destroy()
        self.title(f"{APP_NAME} {__version__} — {T('app.subtitle')}")
        self.var_video.set(video_label(self._keys["video"]))
        self.var_audio.set(audio_label(self._keys["audio"]))
        self.var_height.set(height_label(self._keys["height"]))
        self._build_ui()
        self.var_preset.set(T(f"p.{self.preset_key}") if self.preset_key != core.CUSTOM_PRESET
                            else T("preset.custom"))
        self._on_controls_change()
        self._update_meta_info()
        self._show_ff_info()
        if self.takes:
            self._fill_tree()
        else:
            self.var_status.set(T("empty.hint"))
        for line in self.log_lines:
            self._log_insert(line)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 3}
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=24)
        style.configure("Big.TButton", padding=(18, 6), font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Warn.TLabel", foreground="#a05a00")
        style.configure("Title.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Step.TLabelframe.Label", font=("Segoe UI", 10, "bold"))

        # --- заголовок
        head = ttk.Frame(self)
        head.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(head, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="  " + T("app.subtitle"), style="Hint.TLabel").pack(side="left", pady=(4, 0))
        ttk.Button(head, text=T("help"), command=self.show_help).pack(side="right")
        cb = ttk.Combobox(head, textvariable=self.var_lang, values=list(LANGS.values()),
                          state="readonly", width=10)
        cb.pack(side="right", padx=6)
        cb.bind("<<ComboboxSelected>>", self._on_lang)
        ttk.Label(head, text=T("lang")).pack(side="right")

        # --- ① источник
        top = ttk.LabelFrame(self, text=T("step1"), style="Step.TLabelframe")
        top.pack(fill="x", **pad)
        top.columnconfigure(1, weight=1)
        lbl = ttk.Label(top, text=T("src.label"))
        lbl.grid(row=0, column=0, sticky="w", padx=6, pady=3)
        ent = ttk.Entry(top, textvariable=self.var_src)
        ent.grid(row=0, column=1, sticky="ew", pady=3)
        b = ttk.Button(top, text=T("browse"), command=self.pick_src)
        b.grid(row=0, column=2, padx=4)
        for w in (lbl, ent, b):
            Tooltip(w, "src.tip")
        self.btn_scan = ttk.Button(top, text=T("scan"), command=self.scan)
        self.btn_scan.grid(row=0, column=3, rowspan=2, sticky="ns", padx=6, pady=3)
        Tooltip(self.btn_scan, "scan.tip")
        lbl = ttk.Label(top, text=T("meta.label"))
        lbl.grid(row=1, column=0, sticky="w", padx=6, pady=3)
        ent = ttk.Entry(top, textvariable=self.var_meta)
        ent.grid(row=1, column=1, sticky="ew", pady=3)
        ent.bind("<FocusOut>", lambda e: self._update_meta_info())
        b = ttk.Button(top, text=T("browse"), command=self.pick_meta)
        b.grid(row=1, column=2, padx=4)
        for w in (lbl, ent, b):
            Tooltip(w, "meta.tip")
        ttk.Label(top, textvariable=self.var_meta_info, style="Hint.TLabel").grid(
            row=2, column=1, columnspan=3, sticky="w")

        # --- ② список дублей
        mid = ttk.LabelFrame(self, text=T("step2"), style="Step.TLabelframe")
        mid.pack(fill="both", expand=True, **pad)
        cols = ("sel", "take", "files", "start", "dur", "size", "note")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended", height=9)
        heads = {"sel": ("", 36), "take": (T("col.take"), 60), "files": (T("col.files"), 270),
                 "start": (T("col.start"), 130), "dur": (T("col.dur"), 110),
                 "size": (T("col.size"), 85), "note": (T("col.note"), 250)}
        for c, (t, w) in heads.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w" if c in ("files", "note") else "center",
                             stretch=c in ("files", "note"))
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        vsb.pack(side="left", fill="y", pady=6)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)
        self.tree.tag_configure("off", foreground="#999999")
        self.tree.tag_configure("err", foreground="#b00020")
        self.tree.tag_configure("warn", foreground="#a05a00")
        Tooltip(self.tree, "tree.tip")

        selbar = ttk.Frame(self)
        selbar.pack(fill="x", padx=8)
        ttk.Button(selbar, text=T("sel.all"), command=lambda: self._select(lambda t: True)).pack(side="left")
        ttk.Button(selbar, text=T("sel.none"), command=lambda: self._select(lambda t: False)).pack(side="left", padx=4)
        b = ttk.Button(selbar, text=T("sel.long"), command=lambda: self._select(lambda t: t.duration >= 60))
        b.pack(side="left")
        Tooltip(b, "sel.long.tip")
        self.lbl_sel = ttk.Label(selbar, text="")
        self.lbl_sel.pack(side="right")

        # --- ③ результат
        opt = ttk.LabelFrame(self, text=T("step3"), style="Step.TLabelframe")
        opt.pack(fill="x", **pad)
        opt.columnconfigure(1, weight=1)
        lbl = ttk.Label(opt, text=T("preset"))
        lbl.grid(row=0, column=0, sticky="w", padx=6, pady=3)
        titles = [p.title for p in core.PRESETS] + [T("preset.custom")]
        cb = ttk.Combobox(opt, textvariable=self.var_preset, values=titles, state="readonly", width=42)
        cb.grid(row=0, column=1, sticky="w", pady=3)
        cb.bind("<<ComboboxSelected>>", self._on_preset_selected)
        Tooltip(lbl, "preset.tip")
        Tooltip(cb, "preset.tip")
        self.lbl_hint = ttk.Label(opt, text="", style="Hint.TLabel", wraplength=980, justify="left")
        self.lbl_hint.grid(row=1, column=0, columnspan=2, sticky="w", padx=6)
        f = ttk.Frame(opt)
        f.grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=3)
        ttk.Label(f, text=T("mode")).pack(side="left")
        for val, key in (("per_take", "mode.per_take"), ("single", "mode.single")):
            rb = ttk.Radiobutton(f, text=T(key), value=val, variable=self.var_mode, command=self._save)
            rb.pack(side="left", padx=8)
            Tooltip(rb, "mode.tip")

        cols2 = ttk.Frame(opt)
        cols2.grid(row=3, column=0, columnspan=2, sticky="ew", padx=4)
        cols2.columnconfigure(0, weight=1)
        cols2.columnconfigure(1, weight=1)
        chg = lambda *_: self._on_controls_change(user=True)  # noqa: E731

        # видео
        vf = ttk.LabelFrame(cols2, text=T("video"))
        vf.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=2)
        ttk.Label(vf, text=T("video.mode")).grid(row=0, column=0, sticky="w", padx=6, pady=2)
        c = ttk.Combobox(vf, textvariable=self.var_video, values=[video_label(k) for k in VIDEO_KEYS],
                         state="readonly", width=34)
        c.grid(row=0, column=1, columnspan=3, sticky="w", pady=2)
        c.bind("<<ComboboxSelected>>", chg)
        Tooltip(c, "video.tip")
        ttk.Label(vf, text=T("encoder")).grid(row=1, column=0, sticky="w", padx=6, pady=2)
        self.cb_encoder = ttk.Combobox(vf, textvariable=self.var_encoder, state="readonly", width=44)
        self.cb_encoder.grid(row=1, column=1, columnspan=3, sticky="w", pady=2)
        self.cb_encoder.bind("<<ComboboxSelected>>", chg)
        Tooltip(self.cb_encoder, "encoder.tip")
        self.rb_quality = ttk.Radiobutton(vf, text=T("rate.quality"), value="quality", variable=self.var_rate,
                                          command=chg)
        self.rb_quality.grid(row=2, column=0, sticky="w", padx=6, pady=2)
        self.sp_quality = ttk.Spinbox(vf, from_=14, to=34, textvariable=self.var_quality, width=5, command=chg)
        self.sp_quality.grid(row=2, column=1, sticky="w")
        ttk.Label(vf, text=T("rate.quality.hint"), style="Hint.TLabel").grid(
            row=2, column=2, columnspan=2, sticky="w", padx=4)
        for w in (self.rb_quality, self.sp_quality):
            Tooltip(w, "rate.quality.tip")
        self.rb_size = ttk.Radiobutton(vf, text=T("rate.size"), value="size", variable=self.var_rate, command=chg)
        self.rb_size.grid(row=3, column=0, sticky="w", padx=6, pady=2)
        self.sp_size = ttk.Spinbox(vf, from_=50, to=100000, increment=50, textvariable=self.var_size, width=7,
                                   command=chg)
        self.sp_size.grid(row=3, column=1, sticky="w")
        ttk.Label(vf, text=T("rate.size.hint"), style="Hint.TLabel").grid(
            row=3, column=2, columnspan=2, sticky="w", padx=4)
        for w in (self.rb_size, self.sp_size):
            Tooltip(w, "rate.size.tip")
        ttk.Label(vf, text=T("height")).grid(row=4, column=0, sticky="w", padx=6, pady=2)
        self.cb_height = ttk.Combobox(vf, textvariable=self.var_height,
                                      values=[height_label(k) for k in HEIGHT_KEYS], state="readonly", width=22)
        self.cb_height.grid(row=4, column=1, columnspan=3, sticky="w", pady=2)
        self.cb_height.bind("<<ComboboxSelected>>", chg)
        Tooltip(self.cb_height, "rate.size.tip")
        for w in (self.sp_quality, self.sp_size):
            w.bind("<KeyRelease>", chg)

        # звук и файл
        af = ttk.LabelFrame(cols2, text=T("audio.box"))
        af.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=2)
        ttk.Label(af, text=T("audio")).grid(row=0, column=0, sticky="w", padx=6, pady=2)
        c = ttk.Combobox(af, textvariable=self.var_audio, values=[audio_label(k) for k in AUDIO_KEYS],
                         state="readonly", width=26)
        c.grid(row=0, column=1, sticky="w", pady=2)
        c.bind("<<ComboboxSelected>>", chg)
        Tooltip(c, "audio.tip")
        self.cb_kbps = ttk.Combobox(af, textvariable=self.var_kbps, values=KBPS_CHOICES, state="readonly", width=5)
        self.cb_kbps.grid(row=0, column=2, sticky="w", padx=4)
        self.cb_kbps.bind("<<ComboboxSelected>>", chg)
        ttk.Label(af, text=T("kbps")).grid(row=0, column=3, sticky="w", padx=(0, 6))
        ttk.Label(af, text=T("channels")).grid(row=1, column=0, sticky="w", padx=6, pady=2)
        f = ttk.Frame(af)
        f.grid(row=1, column=1, columnspan=3, sticky="w")
        self.rb_51 = ttk.Radiobutton(f, text=T("ch.51"), value=False, variable=self.var_stereo, command=chg)
        self.rb_51.pack(side="left")
        self.rb_st = ttk.Radiobutton(f, text=T("ch.st"), value=True, variable=self.var_stereo, command=chg)
        self.rb_st.pack(side="left", padx=8)
        for w in (self.rb_51, self.rb_st):
            Tooltip(w, "channels.tip")
        ttk.Label(af, text=T("container")).grid(row=2, column=0, sticky="w", padx=6, pady=2)
        f = ttk.Frame(af)
        f.grid(row=2, column=1, columnspan=3, sticky="w")
        for v, t in (("mp4", "MP4"), ("mov", "MOV"), ("mkv", "MKV")):
            rb = ttk.Radiobutton(f, text=t, value=v, variable=self.var_container, command=chg)
            rb.pack(side="left", padx=(0, 10))
            Tooltip(rb, "container.tip")
        cbx = ttk.Checkbutton(af, text=T("faststart"), variable=self.var_faststart, command=chg)
        cbx.grid(row=3, column=0, columnspan=4, sticky="w", padx=6, pady=2)
        Tooltip(cbx, "faststart.tip")
        cbx = ttk.Checkbutton(af, text=T("proxies"), variable=self.var_proxies, command=self._save)
        cbx.grid(row=4, column=0, columnspan=4, sticky="w", padx=6, pady=2)
        Tooltip(cbx, "proxies.tip")

        self.lbl_fmt_note = ttk.Label(opt, text="", style="Warn.TLabel", wraplength=980, justify="left")
        self.lbl_fmt_note.grid(row=4, column=0, columnspan=2, sticky="w", padx=6)

        f = ttk.Frame(opt)
        f.grid(row=5, column=0, columnspan=2, sticky="ew", padx=6, pady=3)
        f.columnconfigure(1, weight=1)
        lbl = ttk.Label(f, text=T("out"))
        lbl.grid(row=0, column=0, sticky="w")
        self.ent_out = ttk.Entry(f, textvariable=self.var_out)
        self.ent_out.grid(row=0, column=1, sticky="ew", padx=4)
        b = ttk.Button(f, text=T("browse"), command=self.pick_out)
        b.grid(row=0, column=2)
        cbx = ttk.Checkbutton(f, text=T("out.auto"), variable=self.var_out_auto, command=self._on_out_auto)
        cbx.grid(row=0, column=3, columnspan=2, sticky="w", padx=6)
        for w in (lbl, self.ent_out, b, cbx):
            Tooltip(w, "out.tip")
        lbl = ttk.Label(f, text=T("ffmpeg"))
        lbl.grid(row=1, column=0, sticky="w", pady=(3, 0))
        ent = ttk.Entry(f, textvariable=self.var_ffmpeg)
        ent.grid(row=1, column=1, sticky="ew", padx=4, pady=(3, 0))
        b = ttk.Button(f, text=T("browse"), command=self.pick_ffmpeg)
        b.grid(row=1, column=2, pady=(3, 0))
        b2 = ttk.Button(f, text=T("auto"), command=self._ffmpeg_auto)
        b2.grid(row=1, column=3, sticky="w", padx=(6, 2), pady=(3, 0))
        b3 = ttk.Button(f, text=T("ffmpeg.install"), command=self.install_ffmpeg)
        b3.grid(row=1, column=4, sticky="w", padx=2, pady=(3, 0))
        for w in (lbl, ent, b, b2, b3):
            Tooltip(w, "ffmpeg.tip")
        ttk.Label(f, textvariable=self.var_ff_info, style="Hint.TLabel").grid(
            row=2, column=1, columnspan=4, sticky="w", padx=4)

        # --- ④ запуск
        run = ttk.Frame(self)
        run.pack(fill="x", **pad)
        self.btn_start = ttk.Button(run, text="④ " + T("start").strip(), style="Big.TButton", command=self.start)
        self.btn_start.pack(side="left")
        Tooltip(self.btn_start, "start.tip")
        self.btn_stop = ttk.Button(run, text=T("stop"), command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Button(run, text=T("open"), command=self.open_out).pack(side="left")
        self.pb = ttk.Progressbar(run, mode="determinate", maximum=1000)
        self.pb.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Label(self, textvariable=self.var_status, wraplength=1050).pack(fill="x", padx=12)

        logf = ttk.LabelFrame(self, text=T("log"))
        logf.pack(fill="both", expand=False, **pad)
        self.log = tk.Text(logf, height=5, wrap="word", font=("Consolas", 9), state="disabled")
        lsb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        lsb.pack(side="left", fill="y", pady=6)
        self._on_out_auto()
        if self.busy:
            self._set_busy(True)

    def _fit_window(self, initial=False):
        """Размер окна по содержимому (тексты на разных языках разной длины)."""
        self.update_idletasks()
        cur_w = 0 if initial else self.winfo_width()
        cur_h = 0 if initial else self.winfo_height()
        w = min(max(self.winfo_reqwidth(), cur_w, 1080), self.winfo_screenwidth() - 40)
        h = min(max(self.winfo_reqheight(), cur_h), self.winfo_screenheight() - 80)
        self.geometry(f"{w}x{h}")
        self.minsize(min(self.winfo_reqwidth(), w), min(h, 600))

    # ================================================================== язык и справка
    def _on_lang(self, _e=None):
        lang = next((k for k, v in LANGS.items() if v == self.var_lang.get()), "en")
        if lang == get_lang():
            return
        self._remember_keys()
        set_lang(lang)
        self.settings["lang"] = lang
        self._build_all()
        self._fit_window()
        self._save()

    def show_help(self):
        win = tk.Toplevel(self)
        win.title(f"{APP_NAME} — {T('help').replace('❓ ', '')}")
        win.geometry("820x680")
        txt = tk.Text(win, wrap="word", font=("Segoe UI", 10), padx=14, pady=10)
        sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        lines = HELP[get_lang()].strip().splitlines()
        txt.tag_configure("h1", font=("Segoe UI", 13, "bold"), spacing3=8)
        txt.tag_configure("h2", font=("Segoe UI", 10, "bold"), spacing1=8, spacing3=2)
        for i, line in enumerate(lines):
            tag = "h1" if i == 0 else ("h2" if line and not line.startswith("•") and len(line) < 60
                                       and not line.endswith(".") else "")
            txt.insert("end", line + "\n", tag)
        txt.configure(state="disabled")

    # ================================================================== настройки
    def _remember_keys(self):
        self._keys = dict(video=key_by_label(VIDEO_KEYS, video_label, self.var_video.get()),
                          audio=key_by_label(AUDIO_KEYS, audio_label, self.var_audio.get()),
                          height=key_by_label(HEIGHT_KEYS, height_label, self.var_height.get()))
        enc_label = self.var_encoder.get()
        self.saved_encoder = enc_label.split(" — ")[0] if " — " in enc_label and \
            not enc_label.startswith(T("encoder.auto")) else ""

    def collect_options(self) -> core.Options:
        def _int(var, default):
            try:
                return int(var.get())
            except (tk.TclError, ValueError):
                return default
        enc_label = self.var_encoder.get()
        enc = enc_label.split(" — ")[0] if " — " in enc_label and \
            not enc_label.startswith(T("encoder.auto")) else ""
        return core.Options(
            container=self.var_container.get(),
            video=key_by_label(VIDEO_KEYS, video_label, self.var_video.get()),
            encoder=enc,
            rate_mode=self.var_rate.get(),
            quality=_int(self.var_quality, 22),
            size_limit_mb=_int(self.var_size, 1950),
            height=key_by_label(HEIGHT_KEYS, height_label, self.var_height.get()),
            audio=key_by_label(AUDIO_KEYS, audio_label, self.var_audio.get()),
            audio_kbps=_int(self.var_kbps, 384),
            stereo=bool(self.var_stereo.get()),
            faststart=bool(self.var_faststart.get()),
            single_file=self.var_mode.get() == "single",
            proxies=bool(self.var_proxies.get()),
            out_dir=Path(self.var_out.get().strip() or "."),
        )

    def _apply_preset(self, key: str):
        p = next((p for p in core.PRESETS if p.key == key), None)
        if not p:
            return
        o = core.apply_preset(self.collect_options(), key)
        self._applying = True
        self.preset_key = key
        self.var_preset.set(p.title)
        self.var_container.set(o.container)
        self.var_video.set(video_label(o.video))
        self.var_rate.set(o.rate_mode)
        self.var_quality.set(o.quality)
        self.var_size.set(o.size_limit_mb)
        self.var_height.set(height_label(o.height))
        self.var_audio.set(audio_label(o.audio))
        self.var_kbps.set(str(o.audio_kbps))
        self.var_stereo.set(o.stereo)
        self.var_faststart.set(o.faststart)
        self.var_encoder.set("")
        self.saved_encoder = ""
        self._applying = False
        self._on_controls_change()

    def _on_preset_selected(self, _e=None):
        p = next((p for p in core.PRESETS if p.title == self.var_preset.get()), None)
        if p:
            self._apply_preset(p.key)
        else:
            self.preset_key = core.CUSTOM_PRESET
            self._on_controls_change()

    def _refresh_encoder_list(self):
        video = key_by_label(VIDEO_KEYS, video_label, self.var_video.get())
        lst = self.encoders.get(video, [])
        if not lst:
            values = [T("encoder.none")] if video != "copy" and self.ff_ver else []
        else:
            values = [f"{T('encoder.auto')}: {lst[0]} — {core.encoder_name(lst[0])}"] + \
                     [f"{e} — {core.encoder_name(e)}" for e in lst]
        self.cb_encoder.configure(values=values)
        if self.var_encoder.get() not in values:
            want = self.saved_encoder
            match = next((v for v in values if want and v.startswith(want + " ")), None)
            self.var_encoder.set(match or (values[0] if values else ""))

    def _on_controls_change(self, user: bool = False):
        if self._applying or not hasattr(self, "cb_encoder"):
            return
        if user and self.preset_key != core.CUSTOM_PRESET:
            self.preset_key = core.CUSTOM_PRESET
            self.var_preset.set(T("preset.custom"))
        p = next((p for p in core.PRESETS if p.key == self.preset_key), None)
        self.lbl_hint.configure(text=p.hint if p else T("preset.custom.hint"))

        self._refresh_encoder_list()
        o = self.collect_options()
        copy = o.video == "copy"
        for w in (self.cb_encoder, self.cb_height):
            w.configure(state="disabled" if copy else "readonly")
        for w in (self.rb_quality, self.rb_size):
            w.configure(state="disabled" if copy else "normal")
        self.sp_quality.configure(state="disabled" if copy or o.rate_mode != "quality" else "normal")
        self.sp_size.configure(state="disabled" if copy or o.rate_mode != "size" else "normal")
        self.cb_kbps.configure(state="readonly" if o.audio == "aac" else "disabled")
        for w in (self.rb_51, self.rb_st):
            w.configure(state="disabled" if o.audio == "copy" else "normal")

        notes = []
        if o.audio == "pcm" and o.container == "mp4":
            notes.append(T("warn.pcm_mp4"))
        if o.audio == "copy":
            notes.append(T("warn.ac3"))
        if o.container == "mkv":
            notes.append(T("warn.mkv"))
        if not copy and self.ff_ver and not self.encoders.get(o.video):
            notes.append(T("warn.noenc"))
        if not copy and o.rate_mode == "size" and o.height != -1:
            notes.append(T("warn.height"))
        self.lbl_fmt_note.configure(text="  ".join(notes))
        self._save()

    def _save(self):
        if self._applying or not hasattr(self, "cb_encoder"):
            return
        o = self.collect_options()
        self.settings.update(
            lang=get_lang(), src=self.var_src.get(), meta=self.var_meta.get(), out=self.var_out.get(),
            out_auto=self.var_out_auto.get(), ffmpeg_manual=self.var_ffmpeg.get() if self._ff_manual else "",
            mode=self.var_mode.get(), preset=self.preset_key,
            container=o.container, video=o.video, encoder=o.encoder, rate_mode=o.rate_mode,
            quality=o.quality, size_limit_mb=o.size_limit_mb, height=o.height, audio=o.audio,
            audio_kbps=o.audio_kbps, stereo=o.stereo, faststart=o.faststart, proxies=o.proxies)
        save_settings(self.settings)

    # ================================================================== ffmpeg
    def _show_ff_info(self):
        if not self.ff:
            self.var_ff_info.set(T("ffmpeg.missing") if self.ff_ver == "missing" else T("ffmpeg.checking"))
            return
        if not self.ff_ver:
            self.var_ff_info.set(T("ffmpeg.checking"))
            return
        names = sorted({e for lst in self.encoders.values() for e in lst})
        txt = T("ffmpeg.ok", ver=self.ff_ver, enc=", ".join(names) if names else T("ffmpeg.noenc"))
        if not self.ff[1]:
            txt += T("ffmpeg.noprobe")
        self.var_ff_info.set(txt)

    def _detect_ffmpeg(self, initial=False):
        manual = self.var_ffmpeg.get().strip() if self._ff_manual else None
        self._ff_manual = bool(manual)
        self.ff = core.find_ffmpeg(manual)
        self.ff_ver = ""
        self.encoders = {}
        if not self.ff:
            self.ff_ver = "missing"
            self._show_ff_info()
            if not initial:
                messagebox.showerror(APP_NAME, T("ffmpeg.err"))
            return
        self.var_ffmpeg.set(self.ff[0])
        self._show_ff_info()
        ff = self.ff[0]

        def work():
            ver = core.ffmpeg_version(ff)
            enc = core.working_encoders(ff)
            self.msgs.put(("encoders", ff, ver, enc))

        threading.Thread(target=work, daemon=True).start()
        self._save()

    def _ffmpeg_auto(self):
        self._ff_manual = False
        self.var_ffmpeg.set("")
        self._detect_ffmpeg()

    def pick_ffmpeg(self):
        f = filedialog.askopenfilename(title="ffmpeg.exe", filetypes=[("ffmpeg.exe", "ffmpeg.exe"), ("exe", "*.exe")])
        if f:
            self.var_ffmpeg.set(os.path.normpath(f))
            self._ff_manual = True
            self._detect_ffmpeg()

    def install_ffmpeg(self):
        winget = shutil.which("winget")
        if not winget:
            messagebox.showinfo(APP_NAME, T("ffmpeg.install.nowinget"))
            webbrowser.open(FFMPEG_PAGE)
            return
        if not messagebox.askyesno(APP_NAME, T("ffmpeg.install.ask")):
            return
        try:
            proc = subprocess.Popen([winget, "install", "--id", "Gyan.FFmpeg", "-e",
                                     "--accept-source-agreements", "--accept-package-agreements"],
                                    creationflags=CREATE_NEW_CONSOLE)
        except OSError:
            webbrowser.open(FFMPEG_PAGE)
            return

        def wait():
            proc.wait()
            self.msgs.put(("ffmpeg_installed",))

        threading.Thread(target=wait, daemon=True).start()

    # ================================================================== прочее
    def _log_insert(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def write_log(self, text: str):
        self.log_lines.append(text)
        self._log_insert(text)

    def _auto_out(self) -> str:
        src = self.var_src.get().strip()
        return str(Path(src) / "joined") if src else ""

    def _on_out_auto(self):
        if self.var_out_auto.get():
            self.var_out.set(self._auto_out())
            self.ent_out.configure(state="disabled")
        else:
            self.ent_out.configure(state="normal")
        self._save()

    def _meta_path(self) -> Path | None:
        m = self.var_meta.get().strip()
        if m:
            return Path(m)
        src = self.var_src.get().strip()
        if src and avchd.find_bdmv(Path(src), depth=0):  # папка …\BDMV\STREAM прямо с карты
            return Path(src)
        return None

    def _update_meta_info(self):
        m = self._meta_path()
        if not m:
            self.var_meta_info.set(T("meta.none"))
            return
        b = avchd.find_bdmv(m)
        self.var_meta_info.set(T("meta.ok", path=b) if b else T("meta.bad", path=m))
        self._save()

    def pick_src(self):
        d = filedialog.askdirectory(title=T("pick.src"), initialdir=self.var_src.get() or None)
        if d:
            self.var_src.set(os.path.normpath(d))
            if self.var_out_auto.get():
                self.var_out.set(self._auto_out())
            self._update_meta_info()
            self._save()
            self.scan()

    def pick_meta(self):
        d = filedialog.askdirectory(title=T("pick.meta"), initialdir=self.var_meta.get() or None)
        if d:
            self.var_meta.set(os.path.normpath(d))
            self._update_meta_info()
            if self.var_src.get():
                self.scan()

    def pick_out(self):
        d = filedialog.askdirectory(title=T("pick.out"), initialdir=self.var_out.get() or None)
        if d:
            self.var_out_auto.set(False)
            self.var_out.set(os.path.normpath(d))
            self._on_out_auto()

    def open_out(self):
        out = self.var_out.get().strip()
        if out and Path(out).is_dir():
            os.startfile(out)
        elif self.var_src.get() and Path(self.var_src.get()).is_dir():
            os.startfile(self.var_src.get())

    # ================================================================== сканирование
    def scan(self):
        if self.busy:
            return
        src = Path(self.var_src.get().strip())
        if not src.is_dir():
            messagebox.showwarning(APP_NAME, T("dlg.nofolder"))
            return
        if not self.ff:
            self._detect_ffmpeg()
            if not self.ff:
                return
        if self.var_out_auto.get():
            self.var_out.set(self._auto_out())
        self._update_meta_info()
        meta = self._meta_path()
        self._save()
        self._set_busy(True)
        self.tree.delete(*self.tree.get_children())
        self.var_status.set(T("status.scanning", d=0, n="…"))
        self.pb.configure(value=0)
        ffmpeg, ffprobe = self.ff

        def work():
            try:
                res = core.scan_folder(src, ffprobe, meta,
                                       lambda d, n: self.msgs.put(("scanprog", d, n)), ffmpeg)
                self.msgs.put(("scanned", res))
            except Exception as e:  # noqa: BLE001
                self.msgs.put(("error", T("log.scanerr", e=e)))

        threading.Thread(target=work, daemon=True).start()

    def _tags(self, t: core.Take):
        if t.has_error:
            return ("err",)
        if not t.selected:
            return ("off",)
        return ("warn",) if t.note else ()

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        for t in self.takes:
            notes = []
            if t.note:
                notes.append("⚠ " + t.note)
            if len(t.clips) > 1:
                notes.append(T("note.seamless"))
            if t.has_error:
                notes.append("; ".join(c.error for c in t.clips if c.error))
            start = t.approx_start.strftime("%d.%m %H:%M:%S") + ("" if t.from_meta else " " + T("approx"))
            self.tree.insert("", "end", iid=str(t.index), tags=self._tags(t), values=(
                CHECK_ON if t.selected else CHECK_OFF, t.label, t.files_label, start,
                core.fmt_dur(t.duration), core.fmt_size(t.size), "; ".join(notes)))
        self._update_sel_label()

    def _update_sel_label(self):
        sel = [t for t in self.takes if t.selected]
        self.lbl_sel.configure(text=T("sel.info", n=len(sel), total=len(self.takes),
                                      dur=core.fmt_dur(sum(t.duration for t in sel)),
                                      size=core.fmt_size(sum(t.size for t in sel))))

    def _toggle(self, iids):
        if self.busy:
            return
        for iid in iids:
            t = self.takes[int(iid) - 1]
            t.selected = not t.selected
            self.tree.set(iid, "sel", CHECK_ON if t.selected else CHECK_OFF)
            self.tree.item(iid, tags=self._tags(t))
        self._update_sel_label()

    def _on_tree_click(self, ev):
        if self.tree.identify_region(ev.x, ev.y) != "cell":
            return
        if self.tree.identify_column(ev.x) == "#1":
            iid = self.tree.identify_row(ev.y)
            if iid:
                self._toggle([iid])
                return "break"

    def _on_tree_space(self, _ev):
        self._toggle(self.tree.selection())
        return "break"

    def _select(self, pred):
        if self.busy:
            return
        for t in self.takes:
            t.selected = pred(t)
        self._fill_tree()

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.btn_start.configure(state="disabled" if busy else "normal")
        self.btn_scan.configure(state="disabled" if busy else "normal")
        self.btn_stop.configure(state="normal" if busy and self.runner else "disabled")

    # ================================================================== запуск
    def start(self):
        if self.busy:
            return
        if not self.ff:
            self._detect_ffmpeg()
            if not self.ff:
                return
        sel = [t for t in self.takes if t.selected]
        if not sel:
            messagebox.showinfo(APP_NAME, T("dlg.nosel"))
            return
        out = self.var_out.get().strip()
        if not out:
            messagebox.showwarning(APP_NAME, T("dlg.noout"))
            return
        opts = self.collect_options()
        if opts.video != "copy" and not core.pick_encoder(opts, self.encoders):
            messagebox.showerror(APP_NAME, T("dlg.noenc", codec=opts.video.upper()))
            return
        if opts.single_file and len(sel) > 1:
            sigs = {t.clips[0].signature for t in sel}
            if len(sigs) > 1 and not messagebox.askyesno(APP_NAME, T("dlg.mixed")):
                return
            if any(t.note for t in sel):
                self.write_log(T("log.gapjoin"))
        need = core.estimate_output_size(sel, opts)
        try:
            Path(out).mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(out).free
        except OSError as e:
            messagebox.showerror(APP_NAME, T("dlg.outerr", e=e))
            return
        if free < need * 1.02 and not messagebox.askyesno(
                APP_NAME, T("dlg.space", need=core.fmt_size(need), free=core.fmt_size(free))):
            return

        prefix = Path(self.var_src.get()).name or "video"
        try:
            jobs = core.build_jobs(self.ff[0], self.takes, opts, prefix, self.encoders)
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self._save()
        enc = core.pick_encoder(opts, self.encoders) if opts.video != "copy" else T("log.copy")
        self.write_log(T("log.start", n=len(jobs), enc=enc, size=core.fmt_size(need)))
        self.runner = core.Runner(
            on_progress=lambda i, n, f, title: self.msgs.put(("prog", i, n, f, title)),
            on_log=lambda s: self.msgs.put(("log", s)))
        self._set_busy(True)
        self.pb.configure(value=0)
        runner = self.runner

        def work():
            ok = runner.run(jobs)
            self.msgs.put(("done", ok, runner.cancelled))

        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        if self.runner:
            self.runner.cancel()
            self.var_status.set(T("status.stopping"))

    # ================================================================== очередь сообщений
    def _poll(self):
        try:
            while True:
                msg = self.msgs.get_nowait()
                kind = msg[0]
                if kind == "scanprog":
                    _, d, n = msg
                    self.pb.configure(value=1000 * d / max(n, 1))
                    self.var_status.set(T("status.scanning", d=d, n=n))
                elif kind == "scanned":
                    res: core.ScanResult = msg[1]
                    self.takes = res.takes
                    self._fill_tree()
                    self._set_busy(False)
                    self.pb.configure(value=0)
                    files = sum(len(t.clips) for t in res.takes)
                    recs = len({t.rec_no for t in res.takes})
                    broken = sum(1 for t in res.takes if t.note)
                    src = T("status.src.meta") if res.meta_used else T("status.src.ts")
                    self.var_status.set(T("status.scanned", files=files, recs=recs, src=src,
                                          broken=T("status.broken", n=broken) if broken else ""))
                    if res.takes:
                        c = res.takes[0].clips[0]
                        self.write_log(T("log.folder", path=self.var_src.get(), files=files, recs=recs, src=src,
                                         w=c.width, h=c.height, fps=c.fps, ac=c.a_codec, ch=c.a_channels))
                    for line in res.meta_warnings + res.skipped:
                        self.write_log(line)
                elif kind == "encoders":
                    _, ff, ver, enc = msg
                    if self.ff and self.ff[0] == ff:
                        self.ff_ver = ver
                        self.encoders = enc
                        self._show_ff_info()
                        self._on_controls_change()
                elif kind == "ffmpeg_installed":
                    self.write_log(T("ffmpeg.installed"))
                    self._ffmpeg_auto()
                elif kind == "prog":
                    _, i, n, f, title = msg
                    self.pb.configure(value=1000 * ((i - 1) + f) / n)
                    self.var_status.set(T("status.progress", i=i, n=n, title=title, pct=f"{f * 100:.0f}"))
                elif kind == "log":
                    self.write_log(msg[1])
                elif kind == "done":
                    _, ok, cancelled = msg
                    self.runner = None
                    self._set_busy(False)
                    if cancelled:
                        self.var_status.set(T("status.stopped"))
                    elif ok:
                        self.pb.configure(value=1000)
                        self.var_status.set(T("status.done"))
                        self.write_log(T("log.done"))
                        if messagebox.askyesno(APP_NAME, T("dlg.done")):
                            self.open_out()
                    else:
                        self.var_status.set(T("status.failed"))
                elif kind == "error":
                    self._set_busy(False)
                    self.var_status.set(msg[1])
                    self.write_log(msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _on_close(self):
        if self.runner and self.busy:
            if not messagebox.askyesno(APP_NAME, T("dlg.quit")):
                return
            self.runner.cancel()
        self._save()
        self.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MtsJoiner")
        except Exception:
            pass
    App().mainloop()
