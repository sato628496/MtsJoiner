"""Ядро MTS Joiner: поиск ffmpeg, разбор MTS-файлов на дубли, сборка команд и запуск ffmpeg.

Камеры AVCHD (Sony CX400E и т.п.) пишут одну запись непрерывным MPEG-TS потоком и режут его на
файлы по ~2 ГБ. Куски одной записи идут встык: временные метки следующего файла продолжают
предыдущий. Звук в TS-мультиплексе лежит ~0.77 с «впереди» видео, поэтому при раздельном
импорте в монтажку на стыках появляются чёрный экран со звуком и видео без звука. Побайтовая
склейка кусков (протокол concat) полностью убирает эти разрывы без перекодирования.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

VIDEO_EXTS = {".mts", ".m2ts"}
# Новая запись в AVCHD начинается с метки ~1.02 с; продолжение — с конца предыдущего куска.
CONTINUITY_TOLERANCE = 0.2

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

KNOWN_FFMPEG_DIRS = [
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"D:\Bitwig Studio\bin",
    r"C:\Program Files\Bitwig Studio\bin",
    r"C:\Program Files\Shutter Encoder\Library",
]

CONTAINERS = ("mp4", "mov", "mkv")
AUDIO_MODES = ("copy", "pcm")  # copy = оригинальный AC3, pcm = PCM 24 бит


# --------------------------------------------------------------------------- ffmpeg


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _pair_in(folder: Path) -> tuple[str, str] | None:
    ff, fp = folder / "ffmpeg.exe", folder / "ffprobe.exe"
    if ff.is_file() and fp.is_file():
        return str(ff), str(fp)
    return None


def find_ffmpeg(preferred: str | None = None) -> tuple[str, str] | None:
    """Вернуть (ffmpeg, ffprobe) или None."""
    candidates: list[Path] = []
    if preferred:
        p = Path(preferred)
        candidates.append(p.parent if p.is_file() else p)
    base = app_dir()
    candidates += [base, base / "ffmpeg", base / "ffmpeg" / "bin"]
    for c in candidates:
        pair = _pair_in(c)
        if pair:
            return pair
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    # ffmpeg из devkitPro/msys на PATH не годится для путей Windows — пропускаем его
    if ff and fp and "devkitpro" not in ff.lower() and "msys" not in ff.lower():
        return ff, fp
    for d in KNOWN_FFMPEG_DIRS:
        pair = _pair_in(Path(d))
        if pair:
            return pair
    return None


def ffmpeg_has_encoder(ffmpeg: str, name: str) -> bool:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             creationflags=CREATE_NO_WINDOW, timeout=30).stdout
    except Exception:
        return False
    return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", out, re.M) is not None


# --------------------------------------------------------------------------- анализ


@dataclass
class Clip:
    path: Path
    number: int
    size: int
    mtime: float
    v_start: float | None = None
    v_dur: float | None = None
    width: int | None = None
    height: int | None = None
    fps: str | None = None
    a_codec: str | None = None
    a_channels: int | None = None
    error: str | None = None

    @property
    def v_end(self) -> float | None:
        if self.v_start is None or self.v_dur is None:
            return None
        return self.v_start + self.v_dur

    @property
    def signature(self) -> tuple:
        return (self.width, self.height, self.fps, self.a_codec, self.a_channels)


@dataclass
class Take:
    index: int
    clips: list[Clip] = field(default_factory=list)
    selected: bool = True

    @property
    def duration(self) -> float:
        first, last = self.clips[0], self.clips[-1]
        if first.v_start is None or last.v_end is None:
            return sum(c.v_dur or 0 for c in self.clips)
        return last.v_end - first.v_start

    @property
    def size(self) -> int:
        return sum(c.size for c in self.clips)

    @property
    def first_name(self) -> str:
        return self.clips[0].path.stem

    @property
    def last_name(self) -> str:
        return self.clips[-1].path.stem

    @property
    def files_label(self) -> str:
        if len(self.clips) == 1:
            return self.clips[0].path.name
        return f"{self.clips[0].path.name} … {self.clips[-1].path.name} ({len(self.clips)})"

    @property
    def approx_start(self) -> datetime:
        """Время начала записи ≈ время изменения первого файла минус его длительность."""
        c = self.clips[0]
        return datetime.fromtimestamp(c.mtime) - timedelta(seconds=c.v_dur or 0)

    @property
    def has_error(self) -> bool:
        return any(c.error for c in self.clips)


def list_clips(folder: Path) -> tuple[list[Clip], list[Path]]:
    """Вернуть (клипы с номерными именами, пропущенные файлы)."""
    clips, skipped = [], []
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
            continue
        if not p.stem.isdigit():
            skipped.append(p)  # например «00161 — копия.MTS»
            continue
        st = p.stat()
        clips.append(Clip(path=p, number=int(p.stem), size=st.st_size, mtime=st.st_mtime))
    clips.sort(key=lambda c: c.number)
    return clips, skipped


def probe_clip(ffprobe: str, clip: Clip) -> Clip:
    cmd = [ffprobe, "-v", "error", "-show_entries",
           "stream=codec_type,codec_name,start_time,duration,width,height,r_frame_rate,channels",
           "-of", "json", str(clip.path)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", creationflags=CREATE_NO_WINDOW, timeout=120)
        data = json.loads(res.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        clip.error = f"ffprobe: {e}"
        return clip
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not v:
        clip.error = "нет видеодорожки" + (f" ({res.stderr.strip()[:200]})" if res.stderr else "")
        return clip
    try:
        clip.v_start = float(v.get("start_time"))
        clip.v_dur = float(v.get("duration"))
    except (TypeError, ValueError):
        clip.error = "не удалось прочитать длительность"
    clip.width, clip.height, clip.fps = v.get("width"), v.get("height"), v.get("r_frame_rate")
    if a:
        clip.a_codec, clip.a_channels = a.get("codec_name"), a.get("channels")
    return clip


def group_takes(clips: list[Clip]) -> list[Take]:
    takes: list[Take] = []
    prev: Clip | None = None
    for c in clips:
        cont = (
            prev is not None and takes
            and not c.error and not prev.error
            and c.number == prev.number + 1
            and prev.v_end is not None and c.v_start is not None
            and abs(c.v_start - prev.v_end) <= CONTINUITY_TOLERANCE
            and c.signature == prev.signature
        )
        if cont:
            takes[-1].clips.append(c)
        else:
            takes.append(Take(index=len(takes) + 1, clips=[c]))
        prev = c
    return takes


def scan_folder(folder: Path, ffprobe: str,
                progress: Callable[[int, int], None] | None = None) -> tuple[list[Take], list[Path]]:
    clips, skipped = list_clips(folder)
    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for _ in ex.map(lambda c: probe_clip(ffprobe, c), clips):
            done += 1
            if progress:
                progress(done, len(clips))
    return group_takes(clips), skipped


# --------------------------------------------------------------------------- задания


@dataclass
class Options:
    container: str = "mov"     # mp4 / mov / mkv
    audio: str = "pcm"         # copy / pcm
    single_file: bool = False  # все выбранные дубли в один файл
    proxies: bool = False
    out_dir: Path = Path(".")


@dataclass
class Job:
    kind: str                  # "join" | "proxy"
    title: str
    cmd: list[str]
    output: Path
    duration: float            # секунд, для прогресса
    temp_files: list[Path] = field(default_factory=list)


def effective_container(opts: Options) -> str:
    # PCM в MP4 Premiere не читает — в этом случае пишем MOV
    if opts.audio == "pcm" and opts.container == "mp4":
        return "mov"
    return opts.container


def audio_args(opts: Options) -> list[str]:
    return ["-c:a", "pcm_s24le"] if opts.audio == "pcm" else ["-c:a", "copy"]


def concat_url(take: Take) -> str:
    return "concat:" + "|".join(str(c.path) for c in take.clips)


def _ffconcat_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def unique_path(p: Path, reserved: set[Path]) -> Path:
    cand, n = p, 2
    while cand.exists() or cand in reserved:
        cand = p.with_name(f"{p.stem} ({n}){p.suffix}")
        n += 1
    reserved.add(cand)
    return cand


def estimate_output_size(takes: Iterable[Take], opts: Options) -> int:
    total = 0
    for t in takes:
        total += t.size
        if opts.audio == "pcm":
            # PCM 24 бит 5.1 48 кГц ≈ 864 000 Б/с вместо AC3 448 кбит/с (56 000 Б/с)
            total += int(t.duration * (864_000 - 56_000))
    if opts.proxies:
        total += int(sum(t.duration for t in takes) * 3_000_000)  # ProRes Proxy 540p ≈ 24 Мбит/с
    return total


def build_jobs(ffmpeg: str, takes: list[Take], opts: Options, prefix: str) -> list[Job]:
    total_takes = len(takes)
    takes = [t for t in takes if t.selected]
    ext = effective_container(opts)
    out_dir = opts.out_dir
    reserved: set[Path] = set()
    base = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-progress", "pipe:1", "-nostats"]
    stream_args = ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", *audio_args(opts),
                   "-map_metadata", "-1"]
    jobs: list[Job] = []

    if opts.single_file and len(takes) > 1:
        if len(takes) == total_takes:
            name = f"{prefix}_концерт"
        else:
            name = f"{prefix}_дубли_{takes[0].index:02d}-{takes[-1].index:02d}"
        out = unique_path(out_dir / f"{name}.{ext}", reserved)
        lines = ["ffconcat version 1.0"]
        for t in takes:
            url = concat_url(t).replace("\\", "/")
            lines.append(f"file {_ffconcat_quote(url)}")
        fd, list_path = tempfile.mkstemp(prefix="mtsjoiner_", suffix=".ffconcat")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        cmd = [*base, "-f", "concat", "-safe", "0", "-protocol_whitelist", "file,concat",
               "-i", list_path, *stream_args, str(out)]
        jobs.append(Job("join", f"Все дубли → {out.name}", cmd, out,
                        sum(t.duration for t in takes), [Path(list_path)]))
    else:
        for t in takes:
            span = t.first_name + (f"-{t.last_name}" if len(t.clips) > 1 else "")
            out = unique_path(out_dir / f"{prefix}_дубль{t.index:02d}_{span}.{ext}", reserved)
            cmd = [*base, "-i", concat_url(t), *stream_args, str(out)]
            jobs.append(Job("join", f"Дубль {t.index} → {out.name}", cmd, out, t.duration))

    if opts.proxies:
        proxy_dir = out_dir / "Proxies"
        for j in list(jobs):
            out = unique_path(proxy_dir / f"{j.output.stem}.mov", reserved)
            cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                   "-progress", "pipe:1", "-nostats", "-hwaccel", "auto",
                   "-i", str(j.output), "-map", "0:v:0", "-map", "0:a:0?",
                   "-vf", "scale=960:540:flags=bilinear,format=yuv422p10le",
                   "-c:v", "prores_ks", "-profile:v", "0", "-vendor", "apl0",
                   # Premiere требует у прокси то же число аудиоканалов — копируем звук как есть
                   "-c:a", "copy", str(out)]
            jobs.append(Job("proxy", f"Прокси → {out.name}", cmd, out, j.duration))
    return jobs


# --------------------------------------------------------------------------- запуск


class Runner:
    """Последовательно выполняет задания ffmpeg, сообщая прогресс через колбэки."""

    def __init__(self, on_progress: Callable[[int, int, float, str], None],
                 on_log: Callable[[str], None]):
        self.on_progress = on_progress  # (номер задания, всего, доля 0..1, заголовок)
        self.on_log = on_log
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self, jobs: list[Job]) -> bool:
        ok_all = True
        for i, job in enumerate(jobs, 1):
            if self.cancelled:
                return False
            job.output.parent.mkdir(parents=True, exist_ok=True)
            self.on_log(f"▶ {job.title}")
            ok = self._run_one(i, len(jobs), job)
            for t in job.temp_files:
                try:
                    t.unlink()
                except OSError:
                    pass
            if not ok:
                ok_all = False
                try:
                    if job.output.exists():
                        job.output.unlink()
                except OSError:
                    pass
                if self.cancelled:
                    self.on_log("■ Остановлено пользователем, недописанный файл удалён.")
                    return False
                # если не собрался основной файл — его прокси тоже не сделать
                continue
            self.on_log(f"✔ Готово: {job.output}")
        return ok_all

    def _run_one(self, i: int, n: int, job: Job) -> bool:
        if job.kind == "proxy" and not Path(job.cmd[job.cmd.index("-i") + 1]).exists():
            self.on_log("  пропуск: нет исходного файла для прокси")
            return False
        self._proc = subprocess.Popen(job.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                      errors="replace", creationflags=CREATE_NO_WINDOW)
        err_lines: list[str] = []

        def read_err():
            assert self._proc and self._proc.stderr
            for line in self._proc.stderr:
                line = line.rstrip()
                if line:
                    err_lines.append(line)

        th = threading.Thread(target=read_err, daemon=True)
        th.start()
        assert self._proc.stdout
        for line in self._proc.stdout:
            key, _, val = line.strip().partition("=")
            if key == "out_time_us" and val.lstrip("-").isdigit() and job.duration > 0:
                frac = max(0.0, min(1.0, int(val) / 1e6 / job.duration))
                self.on_progress(i, n, frac, job.title)
        rc = self._proc.wait()
        th.join(timeout=5)
        self._proc = None
        if rc != 0 and not self.cancelled:
            self.on_log(f"✖ ffmpeg завершился с кодом {rc}:")
            for l in err_lines[-15:]:
                self.on_log("   " + l)
            return False
        if self.cancelled:
            return False
        for l in err_lines[-5:]:
            self.on_log("   ⚠ " + l)
        self.on_progress(i, n, 1.0, job.title)
        return True


def fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(b: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if b < 1024 or unit == "ТБ":
            return f"{b:.1f} {unit}" if unit in ("ГБ", "ТБ") else f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} ТБ"
