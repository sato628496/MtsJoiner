"""Окно программы MTS Joiner (tkinter)."""

from __future__ import annotations

import json
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, avchd, core

APP_NAME = "MTS Joiner"
SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home())) / "MtsJoiner" / "settings.json"
CHECK_ON, CHECK_OFF = "☑", "☐"

VIDEO_CHOICES = [("copy", "Копировать без изменений (1:1)"),
                 ("h264", "H.264 — перекодировать"),
                 ("hevc", "HEVC / H.265 — перекодировать")]
AUDIO_CHOICES = [("pcm", "PCM 24 бит — без потерь"),
                 ("copy", "AC3 — оригинал (копия)"),
                 ("aac", "AAC")]
HEIGHT_CHOICES = [(0, "как в исходнике"), (1080, "1080p"), (720, "720p"), (-1, "авто (под лимит)")]
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


def _label_of(choices, key):
    return next((t for k, t in choices if k == key), choices[0][1])


def _key_of(choices, label):
    return next((k for k, t in choices if t == label), choices[0][0])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {__version__}")
        s = self.settings = load_settings()
        self.takes: list[core.Take] = []
        self.ff: tuple[str, str] | None = None
        self.encoders: dict[str, list[str]] = {}
        self.msgs: queue.Queue = queue.Queue()
        self.runner: core.Runner | None = None
        self.busy = False
        self._applying = False
        self._ff_manual = bool(s.get("ffmpeg_manual"))

        d = core.Options()
        self.var_src = tk.StringVar(value=s.get("src", ""))
        self.var_meta = tk.StringVar(value=s.get("meta", ""))
        self.var_out = tk.StringVar(value=s.get("out", ""))
        self.var_out_auto = tk.BooleanVar(value=s.get("out_auto", True))
        self.var_ffmpeg = tk.StringVar(value=s.get("ffmpeg_manual", ""))
        self.var_mode = tk.StringVar(value=s.get("mode", "per_take"))
        self.var_preset = tk.StringVar()
        self.var_container = tk.StringVar(value=s.get("container", d.container))
        self.var_video = tk.StringVar(value=_label_of(VIDEO_CHOICES, s.get("video", d.video)))
        self.var_encoder = tk.StringVar()
        self.saved_encoder = s.get("encoder", "")
        self.var_rate = tk.StringVar(value=s.get("rate_mode", d.rate_mode))
        self.var_quality = tk.IntVar(value=s.get("quality", d.quality))
        self.var_size = tk.IntVar(value=s.get("size_limit_mb", d.size_limit_mb))
        self.var_height = tk.StringVar(value=_label_of(HEIGHT_CHOICES, s.get("height", d.height)))
        self.var_audio = tk.StringVar(value=_label_of(AUDIO_CHOICES, s.get("audio", d.audio)))
        self.var_kbps = tk.StringVar(value=str(s.get("audio_kbps", d.audio_kbps)))
        self.var_stereo = tk.BooleanVar(value=s.get("stereo", d.stereo))
        self.var_faststart = tk.BooleanVar(value=s.get("faststart", d.faststart))
        self.var_proxies = tk.BooleanVar(value=s.get("proxies", False))
        self.var_status = tk.StringVar(value="Выберите папку с MTS-файлами.")
        self.var_meta_info = tk.StringVar(value="")
        self.var_ff_info = tk.StringVar(value="")

        self._build_ui()
        preset_key = s.get("preset", "premiere")
        if preset_key == core.CUSTOM_PRESET:
            self.var_preset.set(self.CUSTOM_TITLE)
        else:
            self._apply_preset(preset_key)
        self.update_idletasks()
        w = min(max(self.winfo_reqwidth(), 1060), self.winfo_screenwidth() - 40)
        h = min(self.winfo_reqheight(), self.winfo_screenheight() - 80)
        self.geometry(f"{w}x{h}")
        self.minsize(min(w, 900), min(h, 600))
        self._on_controls_change()
        self._detect_ffmpeg(initial=True)
        self._update_meta_info()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        if self.var_src.get() and Path(self.var_src.get()).is_dir():
            self.after(300, self.scan)

    CUSTOM_TITLE = "Свои настройки"

    # ================================================================== UI
    def _build_ui(self):
        pad = {"padx": 8, "pady": 3}
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=24)
        style.configure("Big.TButton", padding=(16, 6))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Warn.TLabel", foreground="#a05a00")

        # --- источник
        top = ttk.LabelFrame(self, text="Источник")
        top.pack(fill="x", **pad)
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Папка с MTS:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(top, textvariable=self.var_src).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(top, text="Обзор…", command=self.pick_src).grid(row=0, column=2, padx=4)
        self.btn_scan = ttk.Button(top, text="Сканировать", command=self.scan)
        self.btn_scan.grid(row=0, column=3, rowspan=2, sticky="ns", padx=6, pady=3)
        ttk.Label(top, text="Метаданные камеры:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        ent = ttk.Entry(top, textvariable=self.var_meta)
        ent.grid(row=1, column=1, sticky="ew", pady=3)
        ent.bind("<FocusOut>", lambda e: self._update_meta_info())
        ttk.Button(top, text="Обзор…", command=self.pick_meta).grid(row=1, column=2, padx=4)
        ttk.Label(top, textvariable=self.var_meta_info, style="Hint.TLabel").grid(
            row=2, column=1, columnspan=3, sticky="w")

        # --- список дублей
        mid = ttk.LabelFrame(self, text="Дубли (одно нажатие REC = один дубль; длинная запись = несколько файлов по 2 ГБ)")
        mid.pack(fill="both", expand=True, **pad)
        cols = ("sel", "take", "files", "start", "dur", "size", "note")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended", height=9)
        heads = {"sel": ("", 36), "take": ("Дубль", 60), "files": ("Файлы", 280),
                 "start": ("Начало", 130), "dur": ("Длительность", 110),
                 "size": ("Размер", 85), "note": ("Примечание", 230)}
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

        selbar = ttk.Frame(self)
        selbar.pack(fill="x", padx=8)
        ttk.Button(selbar, text="Выбрать все", command=lambda: self._select(lambda t: True)).pack(side="left")
        ttk.Button(selbar, text="Снять все", command=lambda: self._select(lambda t: False)).pack(side="left", padx=4)
        ttk.Button(selbar, text="Только длиннее 1 мин",
                   command=lambda: self._select(lambda t: t.duration >= 60)).pack(side="left")
        self.lbl_sel = ttk.Label(selbar, text="")
        self.lbl_sel.pack(side="right")

        # --- пресет и режим
        opt = ttk.LabelFrame(self, text="Результат")
        opt.pack(fill="x", **pad)
        opt.columnconfigure(1, weight=1)
        ttk.Label(opt, text="Пресет:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        titles = [p.title for p in core.PRESETS] + [self.CUSTOM_TITLE]
        cb = ttk.Combobox(opt, textvariable=self.var_preset, values=titles, state="readonly", width=40)
        cb.grid(row=0, column=1, sticky="w", pady=3)
        cb.bind("<<ComboboxSelected>>", self._on_preset_selected)
        self.lbl_hint = ttk.Label(opt, text="", style="Hint.TLabel", wraplength=900, justify="left")
        self.lbl_hint.grid(row=1, column=0, columnspan=2, sticky="w", padx=6)
        f = ttk.Frame(opt)
        f.grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=3)
        ttk.Label(f, text="Склейка:").pack(side="left")
        ttk.Radiobutton(f, text="файл на каждый дубль", value="per_take",
                        variable=self.var_mode, command=self._save).pack(side="left", padx=8)
        ttk.Radiobutton(f, text="все выбранные дубли в один файл", value="single",
                        variable=self.var_mode, command=self._save).pack(side="left")

        cols2 = ttk.Frame(opt)
        cols2.grid(row=3, column=0, columnspan=2, sticky="ew", padx=4)
        cols2.columnconfigure(0, weight=1)
        cols2.columnconfigure(1, weight=1)

        # видео
        vf = ttk.LabelFrame(cols2, text="Видео")
        vf.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=2)
        ttk.Label(vf, text="Видео:").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        c = ttk.Combobox(vf, textvariable=self.var_video, values=[t for _, t in VIDEO_CHOICES],
                         state="readonly", width=32)
        c.grid(row=0, column=1, columnspan=3, sticky="w", pady=2)
        c.bind("<<ComboboxSelected>>", lambda e: self._on_controls_change(user=True))
        ttk.Label(vf, text="Кодировщик:").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        self.cb_encoder = ttk.Combobox(vf, textvariable=self.var_encoder, state="readonly", width=32)
        self.cb_encoder.grid(row=1, column=1, columnspan=3, sticky="w", pady=2)
        self.cb_encoder.bind("<<ComboboxSelected>>", lambda e: self._on_controls_change(user=True))
        self.rb_quality = ttk.Radiobutton(vf, text="Качество:", value="quality", variable=self.var_rate,
                                          command=lambda: self._on_controls_change(user=True))
        self.rb_quality.grid(row=2, column=0, sticky="w", padx=6, pady=2)
        self.sp_quality = ttk.Spinbox(vf, from_=14, to=34, textvariable=self.var_quality, width=5,
                                      command=lambda: self._on_controls_change(user=True))
        self.sp_quality.grid(row=2, column=1, sticky="w")
        ttk.Label(vf, text="(меньше — лучше; 18 ≈ без видимых потерь, 23 — экономно)",
                  style="Hint.TLabel").grid(row=2, column=2, columnspan=2, sticky="w", padx=4)
        self.rb_size = ttk.Radiobutton(vf, text="Лимит файла, МБ:", value="size", variable=self.var_rate,
                                       command=lambda: self._on_controls_change(user=True))
        self.rb_size.grid(row=3, column=0, sticky="w", padx=6, pady=2)
        self.sp_size = ttk.Spinbox(vf, from_=50, to=100000, increment=50, textvariable=self.var_size, width=7,
                                   command=lambda: self._on_controls_change(user=True))
        self.sp_size.grid(row=3, column=1, sticky="w")
        ttk.Label(vf, text="(Telegram: 1950, Premium: 3900)", style="Hint.TLabel").grid(
            row=3, column=2, columnspan=2, sticky="w", padx=4)
        ttk.Label(vf, text="Разрешение:").grid(row=4, column=0, sticky="w", padx=6, pady=2)
        self.cb_height = ttk.Combobox(vf, textvariable=self.var_height, values=[t for _, t in HEIGHT_CHOICES],
                                      state="readonly", width=20)
        self.cb_height.grid(row=4, column=1, columnspan=3, sticky="w", pady=2)
        self.cb_height.bind("<<ComboboxSelected>>", lambda e: self._on_controls_change(user=True))
        for w in (self.sp_quality, self.sp_size):
            w.bind("<KeyRelease>", lambda e: self._on_controls_change(user=True))

        # звук и файл
        af = ttk.LabelFrame(cols2, text="Звук и файл")
        af.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=2)
        ttk.Label(af, text="Звук:").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        c = ttk.Combobox(af, textvariable=self.var_audio, values=[t for _, t in AUDIO_CHOICES],
                         state="readonly", width=26)
        c.grid(row=0, column=1, sticky="w", pady=2)
        c.bind("<<ComboboxSelected>>", lambda e: self._on_controls_change(user=True))
        self.cb_kbps = ttk.Combobox(af, textvariable=self.var_kbps, values=KBPS_CHOICES, state="readonly", width=5)
        self.cb_kbps.grid(row=0, column=2, sticky="w", padx=4)
        self.cb_kbps.bind("<<ComboboxSelected>>", lambda e: self._on_controls_change(user=True))
        ttk.Label(af, text="кбит/с").grid(row=0, column=3, sticky="w")
        ttk.Label(af, text="Каналы:").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        f = ttk.Frame(af)
        f.grid(row=1, column=1, columnspan=3, sticky="w")
        self.rb_51 = ttk.Radiobutton(f, text="5.1 как с камеры", value=False, variable=self.var_stereo,
                                     command=lambda: self._on_controls_change(user=True))
        self.rb_51.pack(side="left")
        self.rb_st = ttk.Radiobutton(f, text="стерео (сведение)", value=True, variable=self.var_stereo,
                                     command=lambda: self._on_controls_change(user=True))
        self.rb_st.pack(side="left", padx=8)
        ttk.Label(af, text="Контейнер:").grid(row=2, column=0, sticky="w", padx=6, pady=2)
        f = ttk.Frame(af)
        f.grid(row=2, column=1, columnspan=3, sticky="w")
        for v, t in (("mp4", "MP4"), ("mov", "MOV"), ("mkv", "MKV")):
            ttk.Radiobutton(f, text=t, value=v, variable=self.var_container,
                            command=lambda: self._on_controls_change(user=True)).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(af, text="Быстрый старт (для онлайн-просмотра, Telegram)", variable=self.var_faststart,
                        command=lambda: self._on_controls_change(user=True)).grid(
            row=3, column=0, columnspan=4, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(af, text="Прокси для Premiere (ProRes Proxy 960×540 → папка Proxies)",
                        variable=self.var_proxies, command=self._save).grid(
            row=4, column=0, columnspan=4, sticky="w", padx=6, pady=2)

        self.lbl_fmt_note = ttk.Label(opt, text="", style="Warn.TLabel", wraplength=900, justify="left")
        self.lbl_fmt_note.grid(row=4, column=0, columnspan=2, sticky="w", padx=6)

        f = ttk.Frame(opt)
        f.grid(row=5, column=0, columnspan=2, sticky="ew", padx=6, pady=3)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Куда сохранить:").grid(row=0, column=0, sticky="w")
        self.ent_out = ttk.Entry(f, textvariable=self.var_out)
        self.ent_out.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(f, text="Обзор…", command=self.pick_out).grid(row=0, column=2)
        ttk.Checkbutton(f, text="подпапка «joined» у исходников", variable=self.var_out_auto,
                        command=self._on_out_auto).grid(row=0, column=3, padx=6)
        ttk.Label(f, text="ffmpeg:").grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Entry(f, textvariable=self.var_ffmpeg).grid(row=1, column=1, sticky="ew", padx=4, pady=(3, 0))
        ttk.Button(f, text="Обзор…", command=self.pick_ffmpeg).grid(row=1, column=2, pady=(3, 0))
        ttk.Button(f, text="Авто", command=self._ffmpeg_auto).grid(row=1, column=3, sticky="w", padx=6, pady=(3, 0))
        ttk.Label(f, textvariable=self.var_ff_info, style="Hint.TLabel").grid(
            row=2, column=1, columnspan=3, sticky="w", padx=4)

        # --- запуск
        run = ttk.Frame(self)
        run.pack(fill="x", **pad)
        self.btn_start = ttk.Button(run, text="▶  Склеить", style="Big.TButton", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(run, text="■  Стоп", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Button(run, text="Открыть папку", command=self.open_out).pack(side="left")
        self.pb = ttk.Progressbar(run, mode="determinate", maximum=1000)
        self.pb.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Label(self, textvariable=self.var_status).pack(fill="x", padx=12)

        logf = ttk.LabelFrame(self, text="Журнал")
        logf.pack(fill="both", expand=False, **pad)
        self.log = tk.Text(logf, height=6, wrap="word", font=("Consolas", 9), state="disabled")
        lsb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        lsb.pack(side="left", fill="y", pady=6)
        self._on_out_auto()

    # ================================================================== настройки
    def collect_options(self) -> core.Options:
        def _int(var, default):
            try:
                return int(var.get())
            except (tk.TclError, ValueError):
                return default
        enc_label = self.var_encoder.get()
        enc = enc_label.split(" — ")[0] if enc_label and not enc_label.startswith("авто") else ""
        return core.Options(
            container=self.var_container.get(),
            video=_key_of(VIDEO_CHOICES, self.var_video.get()),
            encoder=enc,
            rate_mode=self.var_rate.get(),
            quality=_int(self.var_quality, 22),
            size_limit_mb=_int(self.var_size, 1950),
            height=_key_of(HEIGHT_CHOICES, self.var_height.get()),
            audio=_key_of(AUDIO_CHOICES, self.var_audio.get()),
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
        self.var_preset.set(p.title)
        self.var_container.set(o.container)
        self.var_video.set(_label_of(VIDEO_CHOICES, o.video))
        self.var_rate.set(o.rate_mode)
        self.var_quality.set(o.quality)
        self.var_size.set(o.size_limit_mb)
        self.var_height.set(_label_of(HEIGHT_CHOICES, o.height))
        self.var_audio.set(_label_of(AUDIO_CHOICES, o.audio))
        self.var_kbps.set(str(o.audio_kbps))
        self.var_stereo.set(o.stereo)
        self.var_faststart.set(o.faststart)
        self.var_encoder.set("")
        self.saved_encoder = ""
        self._applying = False
        self._on_controls_change()

    def _on_preset_selected(self, _e=None):
        title = self.var_preset.get()
        p = next((p for p in core.PRESETS if p.title == title), None)
        if p:
            self._apply_preset(p.key)
        else:
            self._on_controls_change()

    def _refresh_encoder_list(self):
        video = _key_of(VIDEO_CHOICES, self.var_video.get())
        lst = self.encoders.get(video, [])
        if not lst:
            values = ["нет рабочих кодировщиков"] if video != "copy" else []
        else:
            values = [f"авто: {lst[0]} — {core.ENCODER_NAMES.get(lst[0], '')}"] + \
                     [f"{e} — {core.ENCODER_NAMES.get(e, '')}" for e in lst]
        self.cb_encoder.configure(values=values)
        cur = self.var_encoder.get()
        if cur not in values:
            want = self.saved_encoder
            match = next((v for v in values if want and v.startswith(want + " ")), None)
            self.var_encoder.set(match or (values[0] if values else ""))

    def _on_controls_change(self, user: bool = False):
        if self._applying:
            return
        if user and self.var_preset.get() != self.CUSTOM_TITLE:
            self.var_preset.set(self.CUSTOM_TITLE)
        title = self.var_preset.get()
        p = next((p for p in core.PRESETS if p.title == title), None)
        self.lbl_hint.configure(text=p.hint if p else "Параметры настроены вручную.")

        o = self.collect_options()
        self._refresh_encoder_list()
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
            notes.append("PCM в MP4 не поддерживается — файл будет записан как MOV.")
        if o.audio == "copy":
            notes.append("AC3: на Windows 11 24H2+ Premiere может не увидеть звук (нет системного декодера AC3).")
        if o.container == "mkv":
            notes.append("MKV Premiere не импортирует — подходит для архива и плееров.")
        if not copy and not self.encoders.get(o.video):
            notes.append("В текущем ffmpeg нет рабочего кодировщика для перекодирования — нужен полный ffmpeg "
                         "(например, winget install Gyan.FFmpeg).")
        if not copy and o.rate_mode == "size" and o.height not in (-1,):
            notes.append("Совет: разрешение «авто» само уменьшит картинку до 720p, если битрейта мало.")
        self.lbl_fmt_note.configure(text="  ".join(notes))
        self._save()

    def _save(self):
        if self._applying:
            return
        o = self.collect_options()
        title = self.var_preset.get()
        p = next((p for p in core.PRESETS if p.title == title), None)
        self.settings.update(
            src=self.var_src.get(), meta=self.var_meta.get(), out=self.var_out.get(),
            out_auto=self.var_out_auto.get(), ffmpeg_manual=self.var_ffmpeg.get() if self._ff_manual else "",
            mode=self.var_mode.get(), preset=p.key if p else core.CUSTOM_PRESET,
            container=o.container, video=o.video, encoder=o.encoder, rate_mode=o.rate_mode,
            quality=o.quality, size_limit_mb=o.size_limit_mb, height=o.height, audio=o.audio,
            audio_kbps=o.audio_kbps, stereo=o.stereo, faststart=o.faststart, proxies=o.proxies)
        save_settings(self.settings)

    # ================================================================== ffmpeg
    def _detect_ffmpeg(self, initial=False):
        manual = self.var_ffmpeg.get().strip() if self._ff_manual else None
        self._ff_manual = bool(manual)
        self.ff = core.find_ffmpeg(manual)
        if not self.ff:
            self.var_ff_info.set("✖ ffmpeg не найден — укажите ffmpeg.exe (рядом должен лежать ffprobe.exe)")
            if not initial:
                messagebox.showerror(APP_NAME, "Не найден ffmpeg.exe/ffprobe.exe.\n"
                                     "Установите полный ffmpeg (winget install Gyan.FFmpeg) "
                                     "или укажите путь вручную.")
            return
        self.var_ffmpeg.set(self.ff[0])
        self.var_ff_info.set("проверяю кодировщики…")
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

    # ================================================================== прочее
    def write_log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

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
        """Путь к метаданным: указанный пользователем или найденный рядом с папкой MTS."""
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
            self.var_meta_info.set("не указаны — дубли определяются по меткам времени в самих файлах. "
                                   "Можно указать папку карты (PRIVATE / AVCHD / BDMV) — тогда точнее.")
            return
        b = avchd.find_bdmv(m)
        self.var_meta_info.set(f"✔ PLAYLIST/CLIPINF: {b}" if b else f"✖ в «{m}» нет PLAYLIST и CLIPINF")
        self._save()

    def pick_src(self):
        d = filedialog.askdirectory(title="Папка с MTS-файлами", initialdir=self.var_src.get() or None)
        if d:
            self.var_src.set(os.path.normpath(d))
            if self.var_out_auto.get():
                self.var_out.set(self._auto_out())
            self._update_meta_info()
            self._save()
            self.scan()

    def pick_meta(self):
        d = filedialog.askdirectory(title="Папка с метаданными камеры (PRIVATE, AVCHD или BDMV)",
                                    initialdir=self.var_meta.get() or None)
        if d:
            self.var_meta.set(os.path.normpath(d))
            self._update_meta_info()
            if self.takes or self.var_src.get():
                self.scan()

    def pick_out(self):
        d = filedialog.askdirectory(title="Куда сохранять", initialdir=self.var_out.get() or None)
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
            messagebox.showwarning(APP_NAME, "Папка с MTS не найдена.")
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
        self.var_status.set("Анализ файлов…")
        self.pb.configure(value=0)
        ffprobe = self.ff[1]

        def work():
            try:
                res = core.scan_folder(src, ffprobe, meta,
                                       lambda d, n: self.msgs.put(("scanprog", d, n)))
                self.msgs.put(("scanned", res))
            except Exception as e:  # noqa: BLE001
                self.msgs.put(("error", f"Ошибка анализа: {e}"))

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
                notes.append("склейка без разрывов")
            if t.has_error:
                notes.append("; ".join(c.error for c in t.clips if c.error))
            start = t.approx_start.strftime("%d.%m %H:%M:%S") + ("" if t.from_meta else " ≈")
            self.tree.insert("", "end", iid=str(t.index), tags=self._tags(t), values=(
                CHECK_ON if t.selected else CHECK_OFF, t.label, t.files_label, start,
                core.fmt_dur(t.duration), core.fmt_size(t.size), "; ".join(notes)))
        self._update_sel_label()

    def _update_sel_label(self):
        sel = [t for t in self.takes if t.selected]
        self.lbl_sel.configure(text=f"Выбрано: {len(sel)} из {len(self.takes)} · "
                                    f"{core.fmt_dur(sum(t.duration for t in sel))} · "
                                    f"{core.fmt_size(sum(t.size for t in sel))}")

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
            messagebox.showinfo(APP_NAME, "Не выбрано ни одного дубля.")
            return
        out = self.var_out.get().strip()
        if not out:
            messagebox.showwarning(APP_NAME, "Укажите папку для сохранения.")
            return
        opts = self.collect_options()
        if opts.video != "copy" and not core.pick_encoder(opts, self.encoders):
            messagebox.showerror(APP_NAME, "Для перекодирования нужен ffmpeg с кодировщиком "
                                 f"{opts.video.upper()} (например, полный ffmpeg: winget install Gyan.FFmpeg).")
            return
        if opts.single_file and len(sel) > 1:
            sigs = {t.clips[0].signature for t in sel}
            if len(sigs) > 1 and not messagebox.askyesno(
                    APP_NAME, "У выбранных дублей разные параметры видео/звука — склейка в один "
                              "файл может получиться некорректной. Продолжить?"):
                return
            if opts.video == "copy" and any(t.note for t in sel):
                self.write_log("ℹ Части дублей с пропущенными файлами будут склеены встык "
                               "(пропущенный фрагмент восстановить невозможно).")
        need = core.estimate_output_size(sel, opts)
        try:
            Path(out).mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(out).free
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Не удаётся создать папку вывода:\n{e}")
            return
        if free < need * 1.02 and not messagebox.askyesno(
                APP_NAME, f"Нужно примерно {core.fmt_size(need)}, а свободно {core.fmt_size(free)}.\n"
                          "Всё равно продолжить?"):
            return

        prefix = Path(self.var_src.get()).name or "video"
        try:
            jobs = core.build_jobs(self.ff[0], self.takes, opts, prefix, self.encoders)
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self._save()
        enc = core.pick_encoder(opts, self.encoders) if opts.video != "copy" else "копия"
        self.write_log(f"— Старт: {len(jobs)} заданий, видео: {enc}, ожидаемый объём ≈ {core.fmt_size(need)}")
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
            self.var_status.set("Останавливаю…")

    # ================================================================== очередь сообщений
    def _poll(self):
        try:
            while True:
                msg = self.msgs.get_nowait()
                kind = msg[0]
                if kind == "scanprog":
                    _, d, n = msg
                    self.pb.configure(value=1000 * d / max(n, 1))
                    self.var_status.set(f"Анализ файлов… {d}/{n}")
                elif kind == "scanned":
                    res: core.ScanResult = msg[1]
                    self.takes = res.takes
                    self._fill_tree()
                    self._set_busy(False)
                    self.pb.configure(value=0)
                    files = sum(len(t.clips) for t in res.takes)
                    recs = len({t.rec_no for t in res.takes})
                    broken = sum(1 for t in res.takes if t.note)
                    src = "по метаданным камеры" if res.meta_used else "по меткам времени"
                    self.var_status.set(f"Файлов: {files}, дублей: {recs} ({src})"
                                        + (f", с пропусками: {broken}" if broken else "") + ".")
                    if res.takes:
                        c = res.takes[0].clips[0]
                        self.write_log(f"Папка: {self.var_src.get()} — {files} файлов, {recs} дублей {src}. "
                                       f"Видео {c.width}×{c.height} {c.fps}, звук {c.a_codec} {c.a_channels} кан.")
                    for line in res.meta_warnings + res.skipped:
                        self.write_log(line)
                elif kind == "encoders":
                    _, ff, ver, enc = msg
                    if self.ff and self.ff[0] == ff:
                        self.encoders = enc
                        names = sorted({e for lst in enc.values() for e in lst})
                        self.var_ff_info.set(f"✔ {ver}; перекодирование: " +
                                             (", ".join(names) if names else "нет (только склейка)"))
                        self._on_controls_change()
                elif kind == "prog":
                    _, i, n, f, title = msg
                    self.pb.configure(value=1000 * ((i - 1) + f) / n)
                    self.var_status.set(f"[{i}/{n}] {title} — {f * 100:.0f}%")
                elif kind == "log":
                    self.write_log(msg[1])
                elif kind == "done":
                    _, ok, cancelled = msg
                    self.runner = None
                    self._set_busy(False)
                    if cancelled:
                        self.var_status.set("Остановлено.")
                    elif ok:
                        self.pb.configure(value=1000)
                        self.var_status.set("Готово!")
                        self.write_log("— Всё готово.")
                        if messagebox.askyesno(APP_NAME, "Готово! Открыть папку с результатом?"):
                            self.open_out()
                    else:
                        self.var_status.set("Завершено с ошибками — см. журнал.")
                elif kind == "error":
                    self._set_busy(False)
                    self.var_status.set(msg[1])
                    self.write_log(msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _on_close(self):
        if self.runner and self.busy:
            if not messagebox.askyesno(APP_NAME, "Идёт обработка. Остановить и выйти?"):
                return
            self.runner.cancel()
        self._save()
        self.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()
