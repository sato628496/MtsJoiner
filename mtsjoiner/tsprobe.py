"""Встроенный анализатор MPEG-TS / M2TS — запасной вариант, когда рядом с ffmpeg нет ffprobe.

Читает только начало и конец файла (несколько МБ): находит видео/аудио дорожки по таблицам
PAT/PMT и берёт метки времени PTS из заголовков PES. Формат (разрешение, кадры, каналы)
дополняет разбором вывода ``ffmpeg -i`` (он читает лишь заголовок).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

HEAD_BYTES = 3 * 1024 * 1024
TAIL_BYTES = 6 * 1024 * 1024
VIDEO_TYPES = {0x01, 0x02, 0x1B, 0x24, 0xEA}           # MPEG-1/2, H.264, HEVC, VC-1
AUDIO_TYPES = {0x03, 0x04, 0x0F, 0x11, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0xA1, 0xA2}
PTS_WRAP = 1 << 33


def _packet_size(b: bytes) -> tuple[int, int]:
    for size, off in ((192, 4), (188, 0)):
        if len(b) > off + size * 3 and all(b[off + size * k] == 0x47 for k in range(4)):
            return size, off
    raise ValueError("не MPEG-TS")


def _packets(b: bytes, size: int, off: int):
    # выравнивание: найти первый sync-байт с правильным шагом
    start = None
    for i in range(off, min(len(b), off + size * 2)):
        if all(i + size * k < len(b) and b[i + size * k] == 0x47 for k in range(3)):
            start = i
            break
    if start is None:
        return
    for p in range(start, len(b) - 188 + 1, size):
        if b[p] != 0x47:
            continue
        pid = ((b[p + 1] & 0x1F) << 8) | b[p + 2]
        pusi = bool(b[p + 1] & 0x40)
        afc = (b[p + 3] >> 4) & 3
        pl = p + 4
        if afc in (2, 3):
            pl += 1 + b[p + 4]
        if afc in (0, 2) or pl >= p + 188:
            continue
        yield pid, pusi, b[pl:p + 188]


def _find_streams(b: bytes, size: int, off: int) -> tuple[int | None, int | None, int, int]:
    pmt_pid = None
    for pid, pusi, pl in _packets(b, size, off):
        if pid == 0 and pusi:
            t = pl[1 + pl[0]:]
            if t and t[0] == 0x00:
                n = ((t[1] & 0x0F) << 8 | t[2]) - 9
                for i in range(8, 8 + max(0, n), 4):
                    prog = t[i] << 8 | t[i + 1]
                    if prog != 0:
                        pmt_pid = (t[i + 2] & 0x1F) << 8 | t[i + 3]
                        break
        if pmt_pid is not None:
            break
    vpid = apid = None
    vtype = atype = 0
    if pmt_pid is None:
        return None, None, 0, 0
    for pid, pusi, pl in _packets(b, size, off):
        if pid != pmt_pid or not pusi:
            continue
        t = pl[1 + pl[0]:]
        if not t or t[0] != 0x02:
            continue
        sec_len = (t[1] & 0x0F) << 8 | t[2]
        pil = (t[10] & 0x0F) << 8 | t[11]
        i, end = 12 + pil, 3 + sec_len - 4
        while i + 5 <= end and i + 5 <= len(t):
            st, epid = t[i], (t[i + 1] & 0x1F) << 8 | t[i + 2]
            esl = (t[i + 3] & 0x0F) << 8 | t[i + 4]
            if vpid is None and st in VIDEO_TYPES:
                vpid, vtype = epid, st
            elif apid is None and st in AUDIO_TYPES:
                apid, atype = epid, st
            i += 5 + esl
        break
    return vpid, apid, vtype, atype


def _pts_list(b: bytes, size: int, off: int, pids: set[int]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {p: [] for p in pids}
    for pid, pusi, pl in _packets(b, size, off):
        if pid not in pids or not pusi or len(pl) < 14 or pl[0:3] != b"\x00\x00\x01":
            continue
        if not (pl[7] & 0x80):
            continue
        p = pl[9:14]
        pts = ((p[0] >> 1) & 7) << 30 | p[1] << 22 | (p[2] >> 1) << 15 | p[3] << 7 | p[4] >> 1
        out[pid].append(pts)
    return out


def _min_step(values: list[int]) -> int | None:
    s = sorted(set(values))
    steps = [b - a for a, b in zip(s, s[1:]) if b > a]
    return min(steps) if steps else None


def ts_timing(path: Path) -> dict:
    """{v_start, v_dur, a_start, a_dur} в секундах (ключи могут отсутствовать)."""
    size_total = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(HEAD_BYTES)
        f.seek(max(0, size_total - TAIL_BYTES))
        tail = f.read()
    size, off = _packet_size(head)
    vpid, apid, _, _ = _find_streams(head, size, off)
    pids = {p for p in (vpid, apid) if p is not None}
    if not pids:
        raise ValueError("не найдены дорожки (PAT/PMT)")
    h = _pts_list(head, size, off, pids)
    t = _pts_list(tail, size, off, pids)
    res: dict = {}
    for pid, key in ((vpid, "v"), (apid, "a")):
        if pid is None or not h[pid] or not t[pid]:
            continue
        start = min(h[pid][:64])
        step = _min_step(t[pid]) or _min_step(h[pid]) or 0
        last = max(t[pid])
        if last < start:  # переход PTS через 2^33 (≈26,5 ч)
            last += PTS_WRAP
        res[f"{key}_start"] = start / 90000
        res[f"{key}_dur"] = (last + step - start) / 90000
    return res


_RE_VIDEO = re.compile(r"Stream #0:\d+.*?: Video: (\w+).*?(?:\((?:[^)]*?)(progressive|top first|bottom first|top coded first|bottom coded first)\))?.*?, (\d{2,5})x(\d{2,5}).*?, ([\d.]+) fps", re.S)
_RE_AUDIO = re.compile(r"Stream #0:\d+.*?: Audio: (\w+)[^\n]*?, \d+ Hz, ([^,\n]+)")


def ffmpeg_info(ffmpeg: str, path: Path, creationflags: int = 0) -> dict:
    """Формат дорожек из вывода `ffmpeg -i` (без ffprobe)."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=creationflags, timeout=60)
    s = r.stderr
    info: dict = {}
    vline = next((l for l in s.splitlines() if ": Video: " in l), "")
    aline = next((l for l in s.splitlines() if ": Audio: " in l), "")
    if vline:
        m = re.search(r"Video: (\w+)", vline)
        info["v_codec"] = m.group(1) if m else None
        m = re.search(r", (\d{2,5})x(\d{2,5})", vline)
        if m:
            info["width"], info["height"] = int(m.group(1)), int(m.group(2))
        m = re.search(r", ([\d.]+) fps", vline)
        if m:
            fps = float(m.group(1))
            info["fps"] = f"{int(fps)}/1" if fps.is_integer() else m.group(1)
        info["interlaced"] = bool(re.search(r"top first|bottom first|top coded|bottom coded", vline))
    if aline:
        m = re.search(r"Audio: (\w+)", aline)
        info["a_codec"] = m.group(1) if m else None
        m = re.search(r"Hz, ([^,]+)", aline)
        layout = m.group(1).strip() if m else ""
        ch = {"mono": 1, "stereo": 2, "2.1": 3, "3.0": 3, "quad": 4, "4.0": 4, "5.0": 5,
              "5.1": 6, "6.1": 7, "7.1": 8}
        key = layout.split("(")[0]
        m2 = re.match(r"(\d+) channels", layout)
        info["a_channels"] = int(m2.group(1)) if m2 else ch.get(key)
    return info
