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

from . import core

APP_NAME = "MTS Joiner"
SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home())) / "MtsJoiner" / "settings.json"
CHECK_ON, CHECK_OFF = "☑", "☐"


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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.settings = load_settings()
        self.takes: list[core.Take] = []
        self.ff: tuple[str, str] | None = None
        self.msgs: queue.Queue = queue.Queue()
        self.runner: core.Runner | None = None
        self.busy = False

        self.var_src = tk.StringVar(value=self.settings.get("src", ""))
        self.var_out = tk.StringVar(value=self.settings.get("out", ""))
        self.var_out_auto = tk.BooleanVar(value=self.settings.get("out_auto", True))
        self.var_ffmpeg = tk.StringVar(value=self.settings.get("ffmpeg", ""))
        self.var_mode = tk.StringVar(value=self.settings.get("mode", "per_take"))
        self.var_container = tk.StringVar(value=self.settings.get("container", "mov"))
        self.var_audio = tk.StringVar(value=self.settings.get("audio", "pcm"))
        self.var_proxies = tk.BooleanVar(value=self.settings.get("proxies", False))
        self.var_status = tk.StringVar(value="Выберите папку с MTS-файлами.")

        self._build_ui()
        # окно по естественному размеру содержимого (с учётом масштаба экрана), но не больше экрана
        self.update_idletasks()
        w = min(max(self.winfo_reqwidth(), 1000), self.winfo_screenwidth() - 40)
        h = min(self.winfo_reqheight(), self.winfo_screenheight() - 80)
        self.geometry(f"{w}x{h}")
        self.minsize(min(w, 900), min(h, 600))
        self._detect_ffmpeg(initial=True)
        self._on_format_change()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        if self.var_src.get() and Path(self.var_src.get()).is_dir():
            self.after(300, self.scan)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=24)
        style.configure("Big.TButton", padding=(16, 6))

        # --- источник
        top = ttk.LabelFrame(self, text="Папка с файлами камеры (MTS)")
        top.pack(fill="x", **pad)
        ttk.Entry(top, textvariable=self.var_src).pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(top, text="Обзор…", command=self.pick_src).pack(side="left", padx=2)
        self.btn_scan = ttk.Button(top, text="Сканировать", command=self.scan)
        self.btn_scan.pack(side="left", padx=6)

        # --- список дублей
        mid = ttk.LabelFrame(self, text="Дубли (каждое нажатие REC; длинная запись = несколько файлов по 2 ГБ)")
        mid.pack(fill="both", expand=True, **pad)
        cols = ("sel", "take", "files", "start", "dur", "size", "note")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended", height=12)
        heads = {"sel": ("", 36), "take": ("Дубль", 60), "files": ("Файлы", 300),
                 "start": ("Начало ≈", 90), "dur": ("Длительность", 120),
                 "size": ("Размер", 90), "note": ("Примечание", 200)}
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

        selbar = ttk.Frame(self)
        selbar.pack(fill="x", padx=8)
        ttk.Button(selbar, text="Выбрать все", command=lambda: self._select(lambda t: True)).pack(side="left")
        ttk.Button(selbar, text="Снять все", command=lambda: self._select(lambda t: False)).pack(side="left", padx=4)
        ttk.Button(selbar, text="Только длиннее 1 мин",
                   command=lambda: self._select(lambda t: t.duration >= 60)).pack(side="left")
        self.lbl_sel = ttk.Label(selbar, text="")
        self.lbl_sel.pack(side="right")

        # --- настройки
        opt = ttk.LabelFrame(self, text="Настройки вывода (видео всегда копируется 1:1 — без перекодирования и потери качества)")
        opt.pack(fill="x", **pad)
        opt.columnconfigure(1, weight=1)

        ttk.Label(opt, text="Склейка:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        f = ttk.Frame(opt)
        f.grid(row=0, column=1, columnspan=3, sticky="w")
        ttk.Radiobutton(f, text="отдельный файл на каждый дубль", value="per_take",
                        variable=self.var_mode, command=self._save).pack(side="left")
        ttk.Radiobutton(f, text="все выбранные дубли в один файл", value="single",
                        variable=self.var_mode, command=self._save).pack(side="left", padx=12)

        ttk.Label(opt, text="Контейнер:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        f = ttk.Frame(opt)
        f.grid(row=1, column=1, columnspan=3, sticky="w")
        for v, t in (("mp4", "MP4"), ("mov", "MOV"), ("mkv", "MKV")):
            ttk.Radiobutton(f, text=t, value=v, variable=self.var_container,
                            command=self._on_format_change).pack(side="left", padx=(0, 12))

        ttk.Label(opt, text="Звук:").grid(row=2, column=0, sticky="w", padx=6, pady=3)
        f = ttk.Frame(opt)
        f.grid(row=2, column=1, columnspan=3, sticky="w")
        ttk.Radiobutton(f, text="PCM 5.1, 24 бит (надёжно для Premiere)", value="pcm",
                        variable=self.var_audio, command=self._on_format_change).pack(side="left")
        ttk.Radiobutton(f, text="оригинал AC3 5.1 (бит-в-бит)", value="copy",
                        variable=self.var_audio, command=self._on_format_change).pack(side="left", padx=12)
        self.lbl_fmt_note = ttk.Label(opt, text="", foreground="#a05a00")
        self.lbl_fmt_note.grid(row=3, column=1, columnspan=3, sticky="w", padx=0)

        ttk.Checkbutton(opt, text="Сделать прокси для Premiere (ProRes Proxy 960×540, папка Proxies)",
                        variable=self.var_proxies, command=self._save).grid(
            row=4, column=0, columnspan=4, sticky="w", padx=6, pady=3)

        ttk.Label(opt, text="Куда сохранить:").grid(row=5, column=0, sticky="w", padx=6, pady=3)
        self.ent_out = ttk.Entry(opt, textvariable=self.var_out)
        self.ent_out.grid(row=5, column=1, sticky="ew", pady=3)
        ttk.Button(opt, text="Обзор…", command=self.pick_out).grid(row=5, column=2, padx=4)
        ttk.Checkbutton(opt, text="подпапка «joined» рядом с исходниками", variable=self.var_out_auto,
                        command=self._on_out_auto).grid(row=5, column=3, padx=6)

        ttk.Label(opt, text="ffmpeg:").grid(row=6, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(opt, textvariable=self.var_ffmpeg).grid(row=6, column=1, sticky="ew", pady=3)
        ttk.Button(opt, text="Обзор…", command=self.pick_ffmpeg).grid(row=6, column=2, padx=4)
        self.lbl_ff = ttk.Label(opt, text="")
        self.lbl_ff.grid(row=6, column=3, sticky="w", padx=6)

        # --- запуск
        run = ttk.Frame(self)
        run.pack(fill="x", **pad)
        self.btn_start = ttk.Button(run, text="▶  Склеить", style="Big.TButton", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(run, text="■  Стоп", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_open = ttk.Button(run, text="Открыть папку", command=self.open_out)
        self.btn_open.pack(side="left")
        self.pb = ttk.Progressbar(run, mode="determinate", maximum=1000)
        self.pb.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Label(self, textvariable=self.var_status).pack(fill="x", padx=12)

        logf = ttk.LabelFrame(self, text="Журнал")
        logf.pack(fill="both", expand=False, **pad)
        self.log = tk.Text(logf, height=8, wrap="word", font=("Consolas", 9), state="disabled")
        lsb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        lsb.pack(side="left", fill="y", pady=6)
        self._on_out_auto()

    # ------------------------------------------------------------------ helpers
    def _save(self):
        self.settings.update(src=self.var_src.get(), out=self.var_out.get(),
                             out_auto=self.var_out_auto.get(), ffmpeg=self.var_ffmpeg.get(),
                             mode=self.var_mode.get(), container=self.var_container.get(),
                             audio=self.var_audio.get(), proxies=self.var_proxies.get())
        save_settings(self.settings)

    def write_log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_format_change(self):
        if self.var_audio.get() == "pcm" and self.var_container.get() == "mp4":
            note = "PCM в MP4 Premiere не читает — файл будет записан как MOV."
        elif self.var_audio.get() == "copy":
            note = "AC3: на Windows 11 24H2+ Premiere может не увидеть звук (нет системного декодера AC3)."
        elif self.var_container.get() == "mkv":
            note = "MKV Premiere не импортирует — подходит для архива/плееров."
        else:
            note = ""
        self.lbl_fmt_note.configure(text=note)
        self._save()

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

    def _detect_ffmpeg(self, initial=False):
        self.ff = core.find_ffmpeg(self.var_ffmpeg.get().strip() or None)
        if self.ff:
            self.var_ffmpeg.set(self.ff[0])
            self.lbl_ff.configure(text="✔ найден", foreground="#1b7f2a")
        else:
            self.lbl_ff.configure(text="✖ не найден", foreground="#b00020")
            if not initial:
                messagebox.showerror(APP_NAME, "Не найден ffmpeg.exe/ffprobe.exe.\n"
                                     "Положите их рядом с программой или укажите путь вручную.")
        self._save()

    # ------------------------------------------------------------------ actions
    def pick_src(self):
        d = filedialog.askdirectory(title="Папка с MTS-файлами", initialdir=self.var_src.get() or None)
        if d:
            self.var_src.set(os.path.normpath(d))
            if self.var_out_auto.get():
                self.var_out.set(self._auto_out())
            self._save()
            self.scan()

    def pick_out(self):
        d = filedialog.askdirectory(title="Куда сохранять", initialdir=self.var_out.get() or None)
        if d:
            self.var_out_auto.set(False)
            self.var_out.set(os.path.normpath(d))
            self._on_out_auto()

    def pick_ffmpeg(self):
        f = filedialog.askopenfilename(title="ffmpeg.exe", filetypes=[("ffmpeg.exe", "ffmpeg.exe"), ("exe", "*.exe")])
        if f:
            self.var_ffmpeg.set(os.path.normpath(f))
            self._detect_ffmpeg()

    def open_out(self):
        out = self.var_out.get().strip()
        if out and Path(out).is_dir():
            os.startfile(out)
        elif self.var_src.get() and Path(self.var_src.get()).is_dir():
            os.startfile(self.var_src.get())

    def scan(self):
        if self.busy:
            return
        src = Path(self.var_src.get().strip())
        if not src.is_dir():
            messagebox.showwarning(APP_NAME, "Папка не найдена.")
            return
        if not self.ff:
            self._detect_ffmpeg()
            if not self.ff:
                return
        if self.var_out_auto.get():
            self.var_out.set(self._auto_out())
        self._save()
        self._set_busy(True)
        self.tree.delete(*self.tree.get_children())
        self.var_status.set("Анализ файлов…")
        self.pb.configure(value=0)

        def work():
            try:
                takes, skipped = core.scan_folder(
                    src, self.ff[1], lambda d, n: self.msgs.put(("scanprog", d, n)))
                self.msgs.put(("scanned", takes, skipped))
            except Exception as e:  # noqa: BLE001
                self.msgs.put(("error", f"Ошибка анализа: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        for t in self.takes:
            notes = []
            if len(t.clips) > 1:
                notes.append("склейка без разрывов")
            if t.has_error:
                notes.append("; ".join(c.error for c in t.clips if c.error))
            tags = ("err",) if t.has_error else (() if t.selected else ("off",))
            self.tree.insert("", "end", iid=str(t.index), tags=tags, values=(
                CHECK_ON if t.selected else CHECK_OFF, t.index, t.files_label,
                t.approx_start.strftime("%H:%M:%S"), core.fmt_dur(t.duration),
                core.fmt_size(t.size), ", ".join(notes)))
        self._update_sel_label()

    def _update_sel_label(self):
        sel = [t for t in self.takes if t.selected]
        self.lbl_sel.configure(text=f"Выбрано дублей: {len(sel)} из {len(self.takes)} · "
                                    f"{core.fmt_dur(sum(t.duration for t in sel))} · "
                                    f"{core.fmt_size(sum(t.size for t in sel))}")

    def _toggle(self, iids):
        if self.busy:
            return
        for iid in iids:
            t = self.takes[int(iid) - 1]
            t.selected = not t.selected
            self.tree.set(iid, "sel", CHECK_ON if t.selected else CHECK_OFF)
            self.tree.item(iid, tags=("err",) if t.has_error else (() if t.selected else ("off",)))
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
        opts = core.Options(container=self.var_container.get(), audio=self.var_audio.get(),
                            single_file=self.var_mode.get() == "single",
                            proxies=self.var_proxies.get(), out_dir=Path(out))
        if opts.single_file and len(sel) > 1:
            sigs = {t.clips[0].signature for t in sel}
            if len(sigs) > 1 and not messagebox.askyesno(
                    APP_NAME, "У выбранных дублей разные параметры видео/звука — склейка в один "
                              "файл может получиться некорректной. Продолжить?"):
                return
        if opts.proxies and not core.ffmpeg_has_encoder(self.ff[0], "prores_ks"):
            messagebox.showerror(APP_NAME, "В этой сборке ffmpeg нет кодировщика ProRes — прокси не сделать.")
            return
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
        jobs = core.build_jobs(self.ff[0], self.takes, opts, prefix)
        self._save()
        self.write_log(f"— Старт: {len(jobs)} заданий, ожидаемый объём ≈ {core.fmt_size(need)}")
        self.runner = core.Runner(
            on_progress=lambda i, n, f, title: self.msgs.put(("prog", i, n, f, title)),
            on_log=lambda s: self.msgs.put(("log", s)))
        self._set_busy(True)
        self.pb.configure(value=0)

        def work():
            ok = self.runner.run(jobs)
            self.msgs.put(("done", ok, self.runner.cancelled))

        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        if self.runner:
            self.runner.cancel()
            self.var_status.set("Останавливаю…")

    # ------------------------------------------------------------------ очередь сообщений
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
                    _, takes, skipped = msg
                    self.takes = takes
                    self._fill_tree()
                    self._set_busy(False)
                    self.pb.configure(value=0)
                    files = sum(len(t.clips) for t in takes)
                    multi = sum(1 for t in takes if len(t.clips) > 1)
                    self.var_status.set(f"Найдено файлов: {files}, дублей: {len(takes)} "
                                        f"(из нескольких файлов: {multi}).")
                    if takes:
                        c = takes[0].clips[0]
                        self.write_log(f"Папка: {self.var_src.get()} — {files} файлов, {len(takes)} дублей. "
                                       f"Видео {c.width}×{c.height} {c.fps}, звук {c.a_codec} {c.a_channels} кан.")
                    for p in skipped:
                        self.write_log(f"Пропущен (не номерное имя): {p.name}")
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
