"""Ядро MTS Joiner: поиск ffmpeg, разбор MTS-файлов на дубли, сборка команд и запуск ffmpeg.

Камеры AVCHD (Sony CX400E и т.п.) пишут одну запись непрерывным MPEG-TS потоком и режут его на
файлы по ~2 ГБ. Куски одной записи идут встык: временные метки следующего файла продолжают
предыдущий. Звук в TS-мультиплексе лежит ~0.77 с «впереди» видео, поэтому при раздельном
импорте в монтажку на стыках появляются чёрный экран со звуком и видео без звука. Побайтовая
склейка кусков (протокол concat) полностью убирает эти разрывы без перекодирования.

Состав дублей определяется двумя способами:
* по служебным файлам камеры (PLAYLIST/CLIPINF) — точно, с датой/временем записи, узнаёт
  переименованные файлы по размеру и показывает, каких кусков не хватает;
* без них — по непрерывности временных меток внутри самих MTS.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from . import avchd, tsprobe
from .i18n import T, get_lang

VIDEO_EXTS = {".mts", ".m2ts"}
CONTINUITY_TOLERANCE = 0.2   # с
NEW_RECORDING_START = 2.0    # новая запись AVCHD начинается с метки ~1.02 с

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

KNOWN_FFMPEG_DIRS = [
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"D:\Bitwig Studio\bin",
    r"C:\Program Files\Bitwig Studio\bin",
    r"C:\Program Files\EibolSoft\FFmpeg Batch AV Converter",
    r"C:\Program Files\Shutter Encoder\Library",
    r"C:\Program Files (x86)\FFmpeg\bin",
]


# =========================================================================== ffmpeg


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _ffmpeg_in(folder: Path) -> str | None:
    ff = folder / "ffmpeg.exe"
    return str(ff) if ff.is_file() else None


def _ffprobe_in(folder: Path) -> str | None:
    fp = folder / "ffprobe.exe"
    return str(fp) if fp.is_file() else None


def ffmpeg_candidates() -> list[Path]:
    base = app_dir()
    dirs = [base, base / "ffmpeg", base / "ffmpeg" / "bin"]
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    pk = local / "Microsoft" / "WinGet" / "Packages"
    if pk.is_dir():
        for d in sorted(pk.glob("*FFmpeg*"), reverse=True):
            dirs += sorted((p.parent for p in d.glob("*/bin/ffmpeg.exe")), reverse=True)
    which = shutil.which("ffmpeg")
    if which and "devkitpro" not in which.lower() and "msys" not in which.lower():
        dirs.append(Path(which).resolve().parent)
    dirs.append(local / "Microsoft" / "WinGet" / "Links")
    dirs += [Path(d) for d in KNOWN_FFMPEG_DIRS]
    return dirs


def find_ffmpeg(manual: str | None = None) -> tuple[str, str | None] | None:
    """Вернуть (ffmpeg, ffprobe или None). manual — путь, выбранный пользователем.

    ffprobe не обязателен: без него файлы разбирает встроенный анализатор (tsprobe). Если рядом
    с выбранным ffmpeg нет ffprobe, берётся ffprobe из другой найденной сборки.
    """
    cands = ffmpeg_candidates()
    ff = None
    if manual:
        m = Path(manual)
        ff = _ffmpeg_in(m.parent if m.suffix else m)
    if not ff:
        ff = next((x for x in map(_ffmpeg_in, cands) if x), None)
    if not ff:
        return None
    fp = _ffprobe_in(Path(ff).parent) or next((x for x in map(_ffprobe_in, cands) if x), None)
    return ff, fp


def _run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=CREATE_NO_WINDOW, timeout=timeout)


def ffmpeg_version(ffmpeg: str) -> str:
    try:
        first = _run([ffmpeg, "-hide_banner", "-version"], 20).stdout.splitlines()[0]
        return first.replace("ffmpeg version ", "").split(" Copyright")[0]
    except Exception:
        return "?"


def ffmpeg_encoders(ffmpeg: str) -> set[str]:
    try:
        out = _run([ffmpeg, "-hide_banner", "-encoders"], 30).stdout
    except Exception:
        return set()
    return set(re.findall(r"^\s*[VAS][\w.]{5}\s+(\S+)", out, re.M))


# Кодировщики в порядке предпочтения (качество/скорость) для каждого кодека
# (видеокарта по качеству на равном битрейте почти не уступает x264/x265, но в 3–8 раз быстрее)
ENCODER_PREFS = {
    "h264": ["h264_nvenc", "h264_amf", "h264_qsv", "libx264", "h264_mf"],
    "hevc": ["hevc_nvenc", "hevc_amf", "hevc_qsv", "libx265", "hevc_mf"],
}
def encoder_name(enc: str) -> str:
    if enc.startswith("lib"):
        return T(f"enc.{enc}")
    return T(f"enc.{enc.split('_')[-1]}")


def working_encoders(ffmpeg: str) -> dict[str, list[str]]:
    """Какие кодировщики есть в сборке И реально запускаются на этом компьютере."""
    have = ffmpeg_encoders(ffmpeg)
    result: dict[str, list[str]] = {}
    for codec, prefs in ENCODER_PREFS.items():
        ok = []
        for enc in prefs:
            if enc not in have:
                continue
            if enc.startswith("lib"):
                ok.append(enc)
                continue
            try:  # аппаратные — пробное кодирование (драйвер может быть старым)
                r = _run([ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                          "color=s=1280x720:r=25:d=0.2", "-c:v", enc, "-f", "null", "-"], 30)
                if r.returncode == 0:
                    ok.append(enc)
            except Exception:
                pass
        result[codec] = ok
    return result


# =========================================================================== анализ


@dataclass
class Clip:
    path: Path
    number: int | None
    size: int
    mtime: float
    v_start: float | None = None
    v_dur: float | None = None
    width: int | None = None
    height: int | None = None
    fps: str | None = None
    a_codec: str | None = None
    a_channels: int | None = None
    a_start: float | None = None
    a_dur: float | None = None
    interlaced: bool = False
    error: str | None = None
    meta_name: str | None = None      # имя клипа по метаданным камеры

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
    """Строка списка = один выходной файл: целая запись или её часть (если не хватает кусков)."""
    index: int                     # уникальный номер строки
    rec_no: int                    # номер записи (дубля)
    clips: list[Clip] = field(default_factory=list)
    part: int = 1
    parts_total: int = 1
    note: str = ""                 # что не так (пропущенные куски)
    start_dt: datetime | None = None
    from_meta: bool = False
    selected: bool = True

    @property
    def label(self) -> str:
        return f"{self.rec_no}.{self.part}" if self.parts_total > 1 else str(self.rec_no)

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
        if self.start_dt:
            return self.start_dt
        c = self.clips[0]
        return datetime.fromtimestamp(c.mtime) - timedelta(seconds=c.v_dur or 0)

    @property
    def has_error(self) -> bool:
        return any(c.error for c in self.clips)

    def trim(self) -> tuple[float, float | None]:
        """(обрезка в начале, длительность или None) — чтобы убрать края без пары «видео+звук».

        Звук в MTS идёт на ~0.77 с раньше видео. У целой записи это незаметно, но если соседний
        кусок потерян, в начале части остаётся звук без картинки, а в конце — картинка без звука.
        """
        first, last = self.clips[0], self.clips[-1]
        if None in (first.v_start, first.a_start, last.v_end, last.a_start, last.a_dur):
            return 0.0, None
        file_start = min(first.v_start, first.a_start)
        start = max(first.v_start, first.a_start)
        end = min(last.v_end, last.a_start + last.a_dur)
        head = start - file_start
        tail_cut = max(last.v_end, last.a_start + last.a_dur) - end
        if head < 0.05 and tail_cut < 0.05:
            return 0.0, None
        return head, end - start


@dataclass
class ScanResult:
    takes: list[Take]
    skipped: list[str]             # строки для журнала
    meta_used: Path | None = None
    meta_warnings: list[str] = field(default_factory=list)


def list_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


def probe_clip_builtin(ffmpeg: str, clip: Clip) -> Clip:
    """Без ffprobe: метки времени — встроенным анализатором, формат — из `ffmpeg -i`."""
    try:
        tm = tsprobe.ts_timing(clip.path)
        info = tsprobe.ffmpeg_info(ffmpeg, clip.path, CREATE_NO_WINDOW)
    except Exception as e:  # noqa: BLE001
        clip.error = str(e)
        return clip
    if "v_start" not in tm:
        clip.error = T("core.novideo")
        return clip
    clip.v_start, clip.v_dur = tm["v_start"], tm["v_dur"]
    clip.a_start, clip.a_dur = tm.get("a_start"), tm.get("a_dur")
    clip.width, clip.height, clip.fps = info.get("width"), info.get("height"), info.get("fps")
    clip.interlaced = bool(info.get("interlaced"))
    clip.a_codec, clip.a_channels = info.get("a_codec"), info.get("a_channels")
    return clip


def probe_clip(ffprobe: str | None, clip: Clip, ffmpeg: str | None = None) -> Clip:
    if not ffprobe:
        return probe_clip_builtin(ffmpeg, clip)
    cmd = [ffprobe, "-v", "error", "-show_entries",
           "stream=codec_type,codec_name,start_time,duration,width,height,r_frame_rate,channels,field_order",
           "-of", "json", str(clip.path)]
    try:
        res = _run(cmd, 120)
        data = json.loads(res.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        clip.error = f"ffprobe: {e}"
        return clip
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not v:
        clip.error = T("core.novideo")
        return clip
    try:
        clip.v_start = float(v.get("start_time"))
        clip.v_dur = float(v.get("duration"))
    except (TypeError, ValueError):
        clip.error = T("core.nodur")
    clip.width, clip.height, clip.fps = v.get("width"), v.get("height"), v.get("r_frame_rate")
    clip.interlaced = v.get("field_order") in ("tt", "bb", "tb", "bt")
    if a:
        clip.a_codec, clip.a_channels = a.get("codec_name"), a.get("channels")
        try:
            clip.a_start, clip.a_dur = float(a.get("start_time")), float(a.get("duration"))
        except (TypeError, ValueError):
            pass
    return clip


def _fmt_missing(names: list[str], seconds: float) -> str:
    if not names:
        return T("core.missing_noname", dur=fmt_dur(seconds))
    shown = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
    return T("core.missing", names=shown, dur=fmt_dur(seconds))


def _finish_parts(rec_no: int, parts: list[tuple[list[Clip], str, datetime | None]],
                  takes: list[Take], from_meta: bool):
    for i, (clips, note, dt) in enumerate(parts, 1):
        takes.append(Take(index=len(takes) + 1, rec_no=rec_no, clips=clips, part=i,
                          parts_total=len(parts), note=note, start_dt=dt, from_meta=from_meta))


def group_by_timestamps(clips: list[Clip], takes: list[Take], rec_no: int) -> int:
    """Группировка без метаданных. Возвращает последний использованный номер записи."""
    clips = sorted(clips, key=lambda c: (c.number is None, c.number or 0, c.path.name))
    parts: list[tuple[list[Clip], str, datetime | None]] = []
    prev: Clip | None = None

    def flush():
        nonlocal parts, rec_no
        if parts:
            rec_no += 1
            _finish_parts(rec_no, parts, takes, False)
        parts = []

    for c in clips:
        ok = not c.error and c.v_start is not None
        cont = (prev is not None and ok and not prev.error and prev.v_end is not None
                and c.signature == prev.signature
                and (c.number is None or prev.number is None or c.number > prev.number))
        if cont and abs(c.v_start - prev.v_end) <= CONTINUITY_TOLERANCE and c.number == (prev.number or -9) + 1:
            parts[-1][0].append(c)
        elif (cont and c.v_start > NEW_RECORDING_START and c.v_start > prev.v_end + CONTINUITY_TOLERANCE
              # по часам: начало этого куска ≈ конец предыдущего + длительность пропуска
              and abs((c.mtime - (c.v_dur or 0)) - prev.mtime - (c.v_start - prev.v_end)) < 30):
            # продолжение той же записи, но между кусками чего-то не хватает
            gap = c.v_start - prev.v_end
            missing = []
            if c.number is not None and prev.number is not None:
                missing = [f"{n:05d}" for n in range(prev.number + 1, c.number)]
            parts.append(([c], _fmt_missing(missing, gap), None))
        else:
            flush()
            note = ""
            if ok and c.v_start > NEW_RECORDING_START:
                note = T("core.no_start", dur=fmt_dur(c.v_start - 1.02))
            parts = [([c], note, None)]
        prev = c
    flush()
    return rec_no


def group_by_metadata(clips: list[Clip], bdmv: Path, takes: list[Take],
                      skipped: list[str]) -> tuple[list[Clip], list[str]]:
    """Группировка по PLAYLIST/CLIPINF. Возвращает (клипы, не найденные в метаданных, предупреждения)."""
    recs, warnings = avchd.read_recordings(bdmv)
    names = [it.clip for r in recs for it in r.items]
    cpis: dict[str, avchd.ClipInfo] = {}
    for n in names:
        ci = avchd.read_cpi(bdmv, n)
        if ci:
            cpis[n] = ci
    by_size: dict[int, list[str]] = {}
    for n, ci in cpis.items():
        by_size.setdefault(ci.size, []).append(n)

    # 1) точное совпадение имени и размера, 2) по размеру (переименованные файлы)
    assigned: dict[str, Clip] = {}
    rest: list[Clip] = []
    for c in clips:
        ci = cpis.get(c.path.stem)
        if ci and ci.size == c.size and c.path.stem not in assigned:
            c.meta_name = c.path.stem
            assigned[c.meta_name] = c
        else:
            rest.append(c)
    unmatched: list[Clip] = []
    for c in rest:
        cands = [n for n in by_size.get(c.size, []) if n not in assigned]
        if c.v_start is not None:
            cands = [n for n in cands if abs(cpis[n].start - c.v_start) < 0.1] or cands
        if cands:
            c.meta_name = cands[0]
            assigned[c.meta_name] = c
        elif any(n in assigned for n in by_size.get(c.size, [])):
            skipped.append(T("core.dup", name=c.path.name,
                             other=assigned[by_size[c.size][0]].path.name))
        elif c.path.stem in cpis and c.path.stem not in assigned:
            # имя есть в метаданных, но размер другой — файл обрезан/повреждён при копировании?
            c.meta_name = c.path.stem
            assigned[c.meta_name] = c
            skipped.append(T("core.badsize", name=c.path.name, size=c.size, meta=cpis[c.path.stem].size))
        else:
            unmatched.append(c)

    rec_no = 0
    for r in recs:
        if not any(it.clip in assigned for it in r.items):
            continue
        rec_no += 1
        parts: list[tuple[list[Clip], str, datetime | None]] = []
        missing: list[str] = []
        missing_sec = 0.0
        t0 = r.items[0].t_in
        for it in r.items:
            c = assigned.get(it.clip)
            if c is None:
                missing.append(it.clip)
                missing_sec += it.duration
                continue
            if c.v_start is None and not c.error:
                c.v_start, c.v_dur = it.t_in, it.duration
            if parts and not missing:
                parts[-1][0].append(c)
            else:
                note = ""
                if missing:
                    note = _fmt_missing(missing, missing_sec)
                    if not parts:
                        note = T("core.start_of", what=note)
                dt = r.start_dt + timedelta(seconds=it.t_in - t0) if r.start_dt else None
                parts.append(([c], note, dt))
                missing, missing_sec = [], 0.0
        if missing and parts:  # нет хвоста записи
            last = parts[-1]
            tail = _fmt_missing(missing, missing_sec)
            parts[-1] = (last[0], (last[1] + "; " if last[1] else "") + T("core.end_of", what=tail), last[2])
        _finish_parts(rec_no, parts, takes, True)
    return unmatched, warnings


def scan_folder(folder: Path, ffprobe: str | None, meta: Path | None = None,
                progress: Callable[[int, int], None] | None = None,
                ffmpeg: str | None = None) -> ScanResult:
    paths = list_files(folder)
    skipped: list[str] = []
    clips: list[Clip] = []
    for p in paths:
        st = p.stat()
        num = int(p.stem) if p.stem.isdigit() else None
        clips.append(Clip(path=p, number=num, size=st.st_size, mtime=st.st_mtime))

    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for _ in ex.map(lambda c: probe_clip(ffprobe, c, ffmpeg), clips):
            done += 1
            if progress:
                progress(done, len(clips))

    takes: list[Take] = []
    bdmv = avchd.find_bdmv(meta) if meta else None
    warnings: list[str] = []
    if meta and not bdmv:
        warnings.append(T("core.nometa", path=meta))
    if bdmv:
        rest, warnings = group_by_metadata(clips, bdmv, takes, skipped)
        if rest:
            warnings.append(T("core.notinmeta", n=len(rest)))
            numbered = [c for c in rest if c.number is not None]
            for c in rest:
                if c.number is None:
                    skipped.append(T("core.nonum_meta", name=c.path.name))
            last_rec = max((t.rec_no for t in takes), default=0)
            group_by_timestamps(numbered, takes, last_rec)
    else:
        numbered = []
        for c in clips:
            if c.number is None:
                dup = next((o for o in clips if o is not c and o.number is not None and o.size == c.size), None)
                skipped.append(T("core.dup2", name=c.path.name, other=dup.path.name) if dup
                               else T("core.nonum", name=c.path.name))
            else:
                numbered.append(c)
        group_by_timestamps(numbered, takes, 0)
    for i, t in enumerate(takes, 1):
        t.index = i
    return ScanResult(takes, skipped, bdmv, warnings)


# =========================================================================== настройки вывода


@dataclass
class Options:
    container: str = "mov"          # mp4 / mov / mkv
    video: str = "copy"             # copy / h264 / hevc
    encoder: str = ""               # конкретный кодировщик ("" = лучший доступный)
    rate_mode: str = "quality"      # quality / size
    quality: int = 21               # CRF-подобная шкала: меньше — лучше
    size_limit_mb: int = 1950       # для rate_mode == size
    height: int = 0                 # 0 = как в исходнике, иначе 1080/720 (-1 = авто по битрейту)
    audio: str = "pcm"              # copy / pcm / aac
    audio_kbps: int = 512
    stereo: bool = False
    faststart: bool = False
    single_file: bool = False
    proxies: bool = False
    out_dir: Path = Path(".")


@dataclass
class Preset:
    key: str
    opts: dict

    @property
    def title(self) -> str:
        return T(f"p.{self.key}")

    @property
    def hint(self) -> str:
        return T(f"p.{self.key}.hint")


PRESETS = [
    Preset("premiere", dict(container="mov", video="copy", audio="pcm", stereo=False, faststart=False)),
    Preset("archive", dict(container="mp4", video="copy", audio="copy", stereo=False, faststart=False)),
    Preset("youtube", dict(container="mp4", video="copy", audio="aac", audio_kbps=512, stereo=False,
                           faststart=True)),
    Preset("telegram", dict(container="mp4", video="h264", rate_mode="size", size_limit_mb=1950, height=-1,
                            audio="aac", audio_kbps=192, stereo=True, faststart=True)),
    Preset("economy", dict(container="mp4", video="hevc", rate_mode="quality", quality=23, height=0,
                           audio="aac", audio_kbps=384, stereo=False, faststart=True)),
]
CUSTOM_PRESET = "custom"


def apply_preset(opts: Options, key: str) -> Options:
    p = next((p for p in PRESETS if p.key == key), None)
    return replace(opts, **p.opts) if p else opts


def effective_container(opts: Options) -> str:
    # PCM в MP4 Premiere/плееры не читают — пишем MOV
    if opts.audio == "pcm" and opts.container == "mp4":
        return "mov"
    return opts.container


def pick_encoder(opts: Options, available: dict[str, list[str]]) -> str | None:
    lst = available.get(opts.video, [])
    if opts.encoder and opts.encoder in lst:
        return opts.encoder
    return lst[0] if lst else None


AUDIO_COPY_BPS = 448_000 / 8
PCM_BPS = 48_000 * 3 * 6
SOURCE_VIDEO_KBPS = 25_000


def audio_bps(opts: Options) -> float:
    ch = 2 if opts.stereo else 6
    if opts.audio == "copy":
        return AUDIO_COPY_BPS
    if opts.audio == "pcm":
        return 48_000 * 3 * ch
    return opts.audio_kbps * 1000 / 8


def quality_kbps_guess(opts: Options, height: int) -> int:
    """Грубая оценка битрейта режима «качество» для 50p (для расчёта места на диске)."""
    # замер на освещённой сцене 1080p50: x264 crf20 ≈ 13 Мбит/с, x265 crf22 ≈ 5 Мбит/с
    base = 13000 if opts.video == "h264" else 5000
    ref = 20 if opts.video == "h264" else 22
    k = 2 ** ((ref - opts.quality) / 6)
    scale = 1.0 if height in (0, 1080) else 0.5
    return int(base * k * scale)


@dataclass
class EncodePlan:
    height: int                  # 0 = как есть
    video_kbps: int | None       # для size-режима
    parts: int = 1
    deinterlace: bool = False    # 1080i (многие AVCHD-камеры) → 50p/60p


def plan_size_mode(duration: float, opts: Options) -> EncodePlan:
    limit_bytes = opts.size_limit_mb * 1024 * 1024 * 0.96
    a_kbps = audio_bps(opts) * 8 / 1000
    overhead = 40
    max_v = {1080: 10_000, 720: 5_000}

    def kbps_for(parts: int) -> float:
        return limit_bytes * 8 / 1000 / (duration / parts) - a_kbps - overhead

    parts = 1
    v = kbps_for(1)
    want_h = opts.height
    if want_h == -1:  # авто: 1080p если ≥ 4.5 Мбит/с, иначе 720p, а если < 1.8 — делим на части
        if v < 1800:
            parts = math.ceil(duration * (1800 + a_kbps + overhead) * 1000 / 8 / limit_bytes)
            v = kbps_for(parts)
        want_h = 1080 if v >= 4500 else 720
    else:
        if v < 1000:
            parts = math.ceil(duration * (1000 + a_kbps + overhead) * 1000 / 8 / limit_bytes)
            v = kbps_for(parts)
    cap = max_v.get(want_h or 1080, 10_000)
    return EncodePlan(height=want_h, video_kbps=int(min(v, cap)), parts=parts)


def video_args(opts: Options, enc: str, plan: EncodePlan) -> list[str]:
    a: list[str] = []
    vf = []
    if plan.deinterlace:
        vf.append("bwdif=mode=send_field")  # каждое поле → кадр: 1080i50 → 1080p50
    if plan.height and plan.height > 0:
        vf.append(f"scale=-2:{plan.height}:flags=lanczos")
    vf.append("format=yuv420p")
    a += ["-vf", ",".join(vf), "-c:v", enc]
    q = opts.quality
    b = plan.video_kbps
    size_mode = opts.rate_mode == "size" and b
    if enc == "libx264":
        a += ["-preset", "medium", "-profile:v", "high"]
        a += ["-b:v", f"{b}k", "-maxrate", f"{int(b * 1.5)}k", "-bufsize", f"{b * 2}k"] if size_mode \
            else ["-crf", str(q)]
    elif enc == "libx265":
        a += ["-preset", "fast", "-tag:v", "hvc1", "-x265-params", "log-level=error"]
        a += ["-b:v", f"{b}k", "-maxrate", f"{int(b * 1.5)}k", "-bufsize", f"{b * 2}k"] if size_mode \
            else ["-crf", str(q)]
    elif enc.endswith("_nvenc"):
        a += ["-preset", "p6", "-tune", "hq", "-spatial-aq", "1", "-rc-lookahead", "32"]
        a += ["-rc", "vbr", "-b:v", f"{b}k", "-maxrate", f"{int(b * 1.5)}k", "-bufsize", f"{b * 2}k",
              "-multipass", "fullres"] if size_mode else ["-rc", "vbr", "-cq", str(q), "-b:v", "0"]
    elif enc.endswith("_amf"):
        a += ["-quality", "quality"]
        if size_mode:
            a += ["-rc", "vbr_peak", "-b:v", f"{b}k", "-maxrate", f"{int(b * 1.5)}k"]
        else:
            # у AMF шкала обратная (больше — лучше); 46 - q даёт то же качество, что CRF q у x265
            guess = quality_kbps_guess(opts, plan.height)
            a += ["-rc", "qvbr", "-qvbr_quality_level", str(max(1, min(51, 46 - q))),
                  "-b:v", f"{guess}k", "-maxrate", f"{guess * 2}k"]
    elif enc.endswith("_qsv"):
        a += ["-preset", "slower"]
        a += ["-b:v", f"{b}k", "-maxrate", f"{int(b * 1.5)}k"] if size_mode \
            else ["-global_quality", str(q)]
    else:  # *_mf — только битрейт
        kb = b if size_mode else quality_kbps_guess(opts, plan.height)
        a += ["-rate_control", "u_vbr", "-b:v", f"{kb}k", "-hw_encoding", "1"]
    if enc.startswith(("h264", "libx264")):
        a += ["-g", "100"]  # ключевой кадр каждые 2 с — удобная перемотка
    if opts.video == "hevc" and "-tag:v" not in a:
        a += ["-tag:v", "hvc1"]
    return a


def audio_args(opts: Options) -> list[str]:
    ch = ["-ac", "2"] if opts.stereo and opts.audio != "copy" else []
    if opts.audio == "copy":
        return ["-c:a", "copy"]
    if opts.audio == "pcm":
        return ["-c:a", "pcm_s24le", *ch]
    kbps = opts.audio_kbps
    if not opts.stereo:
        kbps = max(kbps, 256)
    return ["-c:a", "aac", "-b:a", f"{kbps}k", *ch]


@dataclass
class Job:
    kind: str                  # "join" | "proxy"
    title: str
    cmd: list[str]
    output: Path
    duration: float            # секунд, для прогресса
    temp_files: list[Path] = field(default_factory=list)


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


def estimate_output_size(takes: list[Take], opts: Options) -> int:
    dur = sum(t.duration for t in takes)
    if opts.video == "copy":
        total = sum(t.size for t in takes) - dur * AUDIO_COPY_BPS + dur * audio_bps(opts)
    elif opts.rate_mode == "size":
        total = 0
        for t in takes:
            pl = plan_size_mode(t.duration, opts)
            total += t.duration * ((pl.video_kbps or 0) * 1000 / 8 + audio_bps(opts))
    else:
        total = dur * (quality_kbps_guess(opts, opts.height) * 1000 / 8 + audio_bps(opts))
    if opts.proxies:
        total += dur * 2_300_000  # ProRes Proxy 540p50 ≈ 18 Мбит/с
    return int(total)


def build_jobs(ffmpeg: str, takes: list[Take], opts: Options, prefix: str,
               available: dict[str, list[str]] | None = None) -> list[Job]:
    total_rows = len(takes)
    takes = [t for t in takes if t.selected]
    ext = effective_container(opts)
    reserved: set[Path] = set()
    base = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-progress", "pipe:1", "-nostats"]
    enc = None
    if opts.video != "copy":
        enc = pick_encoder(opts, available or {})
        if not enc:
            raise RuntimeError(T("core.noenc", codec=opts.video.upper()))

    # источники: (название, аргументы входа, начальный сдвиг, длительность, имя файла, обрезка)
    sources: list[tuple[str, list[str], float, float, str, bool]] = []
    if opts.single_file and len(takes) > 1:
        name = (f"{prefix}_{T('file.concert')}" if len(takes) == total_rows
                else f"{prefix}_{T('file.takes')}_{takes[0].label}-{takes[-1].label}")
        lines = ["ffconcat version 1.0"]
        total = 0.0
        for t in takes:
            lines.append(f"file {_ffconcat_quote(concat_url(t).replace(chr(92), '/'))}")
            head, dur = t.trim()
            if dur is not None:
                # inpoint/outpoint concat-демуксера — абсолютные метки времени потока
                c0 = t.clips[0]
                fs = min(c0.v_start, c0.a_start)
                if head > 0:
                    lines.append(f"inpoint {fs + head:.6f}")
                lines.append(f"outpoint {fs + head + dur:.6f}")
            total += dur if dur is not None else t.duration
        fd, list_path = tempfile.mkstemp(prefix="mtsjoiner_", suffix=".ffconcat")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        inp = ["-f", "concat", "-safe", "0", "-protocol_whitelist", "file,concat", "-i", list_path]
        sources.append((T("core.all_takes"), inp, 0.0, total, name, False))
        temp = [Path(list_path)]
    else:
        temp = []
        for t in takes:
            span = t.first_name + (f"-{t.last_name}" if len(t.clips) > 1 else "")
            part = f"_{T('file.part')}{t.part}" if t.parts_total > 1 else ""
            head, dur = t.trim()
            sources.append((T("core.take", label=t.label), ["-i", concat_url(t)], head,
                            dur if dur is not None else t.duration,
                            f"{prefix}_{T('file.take')}{t.rec_no:02d}{part}_{span}", dur is not None))

    interlaced = any(c.interlaced for t in takes for c in t.clips)
    jobs: list[Job] = []
    for title, inp, head, dur, stem, trimmed in sources:
        plan = EncodePlan(height=0 if opts.height == -1 else opts.height, video_kbps=None)
        if opts.video != "copy" and opts.rate_mode == "size":
            plan = plan_size_mode(dur, opts)
        plan.deinterlace = interlaced
        if opts.video == "copy":
            vargs = ["-c:v", "copy"]
        else:
            vargs = video_args(opts, enc, plan)
        tail = ["-map", "0:v:0", "-map", "0:a:0?", *vargs, *audio_args(opts),
                "-map_metadata", "-1"]
        if opts.faststart and ext in ("mp4", "mov"):
            tail += ["-movflags", "+faststart"]
        seg = dur / plan.parts
        for k in range(plan.parts):
            suffix = "_" + T("file.piece", k=k + 1, n=plan.parts) if plan.parts > 1 else ""
            out = unique_path(opts.out_dir / f"{stem}{suffix}.{ext}", reserved)
            cut = []
            if plan.parts > 1:
                cut = ["-ss", f"{head + k * seg:.3f}",
                       "-t", f"{seg + (0.5 if k < plan.parts - 1 else 0):.3f}"]
            elif trimmed:
                cut = (["-ss", f"{head:.3f}"] if head > 0 else []) + ["-t", f"{dur:.3f}"]
            cmd = [*base, *cut, *inp, *tail, str(out)]
            jt = f"{title} → {out.name}"
            if plan.height or plan.video_kbps:
                jt += f"  [{(str(plan.height) + 'p ') if plan.height else ''}" \
                      f"{(str(plan.video_kbps) + ' ' + T('core.kbps')) if plan.video_kbps else ''}]"
            jobs.append(Job("join", jt, cmd, out, seg, temp if k == plan.parts - 1 else []))

    if opts.proxies:
        proxy_dir = opts.out_dir / "Proxies"
        for j in list(jobs):
            out = unique_path(proxy_dir / f"{j.output.stem}.mov", reserved)
            cmd = [*base, "-i", str(j.output), "-map", "0:v:0", "-map", "0:a:0?",
                   "-vf", "scale=960:540:flags=bilinear,format=yuv422p10le",
                   "-c:v", "prores_ks", "-profile:v", "0", "-vendor", "apl0",
                   # Premiere требует у прокси то же число аудиоканалов — копируем звук как есть
                   "-c:a", "copy", str(out)]
            jobs.append(Job("proxy", f"{T('core.proxy')} → {out.name}", cmd, out, j.duration))
    return jobs


# =========================================================================== запуск


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
        try:
            for i, job in enumerate(jobs, 1):
                if self.cancelled:
                    return False
                job.output.parent.mkdir(parents=True, exist_ok=True)
                self.on_log(f"▶ {job.title}")
                ok = self._run_one(i, len(jobs), job)
                if not ok:
                    ok_all = False
                    try:
                        if job.output.exists():
                            job.output.unlink()
                    except OSError:
                        pass
                    if self.cancelled:
                        self.on_log(T("run.stopped"))
                        return False
                    continue
                self.on_log(T("run.done", path=job.output))
            return ok_all
        finally:
            for job in jobs:
                for t in job.temp_files:
                    try:
                        t.unlink()
                    except OSError:
                        pass

    def _run_one(self, i: int, n: int, job: Job) -> bool:
        if job.kind == "proxy" and not Path(job.cmd[job.cmd.index("-i") + 1]).exists():
            self.on_log(T("run.noproxy"))
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
            self.on_log(T("run.fail", rc=rc))
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
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ") if get_lang() == "ru" else ("B", "KB", "MB", "GB", "TB")
    for i, unit in enumerate(units):
        if b < 1024 or i == len(units) - 1:
            return f"{b:.1f} {unit}" if i >= 3 else f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} {units[-1]}"
