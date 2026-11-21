"""Чтение служебных файлов AVCHD: BDMV/PLAYLIST/*.MPL и BDMV/CLIPINF/*.CPI.

Что там лежит (проверено на Sony HDR-CX400E, формат тот же, что у Blu-ray: MPLS/CLPI):

* ``PLAYLIST/xxxxx.MPL`` — список воспроизведения. Каждый элемент (PlayItem) ссылается на клип по
  имени (``00142``) и содержит время IN/OUT и ``connection_condition``:
  5 (или 1) — начало новой записи, 6 — бесшовное продолжение предыдущего клипа. Каждая новая
  запись дополнительно отмечена меткой (PlayListMark, тип 1), а в расширении ``PLEX`` у каждой
  метки хранится дата и время начала записи (BCD).
* ``CLIPINF/xxxxx.CPI`` — описание клипа: точный размер MTS-файла (число 192-байтных пакетов)
  и время начала/конца. По размеру можно узнать файл, даже если его переименовали.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CC_SEAMLESS = 6


@dataclass
class ClipInfo:
    name: str
    size: int          # точный размер MTS-файла, байт
    start: float       # секунды (PTS)
    end: float


@dataclass
class PlayItem:
    clip: str
    cc: int
    t_in: float
    t_out: float

    @property
    def duration(self) -> float:
        return self.t_out - self.t_in


@dataclass
class Recording:
    """Одна запись камеры (одно нажатие REC)."""
    items: list[PlayItem] = field(default_factory=list)
    start_dt: datetime | None = None
    playlist: str = ""


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from(">H", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def find_bdmv(path: Path, depth: int = 4) -> Path | None:
    """Найти папку с PLAYLIST и CLIPINF внутри/над указанной (карта, PRIVATE, AVCHD, BDMV…)."""
    path = Path(path)
    if not path.exists():
        return None
    if path.is_file():
        path = path.parent
    # сама папка, её родитель (если указали STREAM/PLAYLIST/CLIPINF)
    for p in (path, path.parent):
        if (p / "PLAYLIST").is_dir() and (p / "CLIPINF").is_dir():
            return p
    # поиск вниз
    frontier = [path]
    for _ in range(depth):
        nxt = []
        for d in frontier:
            try:
                subs = [s for s in d.iterdir() if s.is_dir()]
            except OSError:
                continue
            for s in subs:
                if (s / "PLAYLIST").is_dir() and (s / "CLIPINF").is_dir():
                    return s
            nxt += subs
        frontier = nxt
    return None


def _find_file(folder: Path, stem: str, exts: tuple[str, ...]) -> Path | None:
    for e in exts:
        for cand in (folder / f"{stem}.{e}", folder / f"{stem}.{e.lower()}"):
            if cand.is_file():
                return cand
    return None


def read_cpi(bdmv: Path, name: str) -> ClipInfo | None:
    p = _find_file(bdmv / "CLIPINF", name, ("CPI", "CLPI"))
    if not p:
        return None
    try:
        b = p.read_bytes()
        if b[:4] != b"HDMV":
            return None
        seq = _u32(b, 8)
        n_packets = _u32(b, 40 + 16)
        o = seq + 4 + 2  # length, reserved, number_of_ATC_sequences
        o += 6           # SPN_ATC_start, number_of_STC_sequences, offset_STC_id
        start = _u32(b, o + 6) / 45000
        end = _u32(b, o + 10) / 45000
        return ClipInfo(name=name, size=n_packets * 192, start=start, end=end)
    except (struct.error, IndexError, OSError):
        return None


def _bcd(byte: int) -> int:
    hi, lo = byte >> 4, byte & 0x0F
    if hi > 9 or lo > 9:
        raise ValueError
    return hi * 10 + lo


def _mark_datetimes(b: bytes, ext_start: int) -> list[datetime | None]:
    """Дата/время каждой метки из расширения PLEX (Sony/Panasonic AVCHD)."""
    if ext_start == 0:
        return []
    plex = b.find(b"PLEX", ext_start)
    if plex < 0:
        return []
    try:
        marks_off = plex + _u32(b, plex + 8)
        count = _u16(b, marks_off + 4)
        out = []
        for i in range(count):
            e = marks_off + 6 + i * 66
            raw = b[e + 11:e + 18]
            try:
                y = _bcd(raw[0]) * 100 + _bcd(raw[1])
                out.append(datetime(y, _bcd(raw[2]), _bcd(raw[3]),
                                    _bcd(raw[4]), _bcd(raw[5]), _bcd(raw[6])))
            except (ValueError, IndexError):
                out.append(None)
        return out
    except (struct.error, IndexError):
        return []


def read_playlist(path: Path) -> list[Recording]:
    b = path.read_bytes()
    if b[:4] != b"MPLS":
        raise ValueError("не MPLS")
    pl_start, mark_start, ext_start = _u32(b, 8), _u32(b, 12), _u32(b, 16)

    n_items = _u16(b, pl_start + 6)
    o = pl_start + 10
    items: list[PlayItem] = []
    for _ in range(n_items):
        ln = _u16(b, o)
        clip = b[o + 2:o + 7].decode("ascii", "replace")
        cc = _u16(b, o + 11) & 0x0F
        t_in, t_out = _u32(b, o + 14) / 45000, _u32(b, o + 18) / 45000
        items.append(PlayItem(clip, cc, t_in, t_out))
        o += 2 + ln

    n_marks = _u16(b, mark_start + 4)
    entry_marks: list[tuple[int, int]] = []  # (номер метки, номер PlayItem)
    for i in range(n_marks):
        m = mark_start + 6 + i * 14
        if b[m + 1] == 1:
            entry_marks.append((i, _u16(b, m + 2)))
    dts = _mark_datetimes(b, ext_start)
    item_dt: dict[int, datetime | None] = {}
    item_has_mark: set[int] = set()
    for mark_no, item_no in entry_marks:
        item_has_mark.add(item_no)
        item_dt.setdefault(item_no, dts[mark_no] if mark_no < len(dts) else None)

    recs: list[Recording] = []
    for i, it in enumerate(items):
        new = not recs or it.cc != CC_SEAMLESS or i in item_has_mark
        if new:
            recs.append(Recording(start_dt=item_dt.get(i), playlist=path.name))
        recs[-1].items.append(it)
    return recs


def read_recordings(bdmv: Path) -> tuple[list[Recording], list[str]]:
    """Все записи из всех плейлистов (по порядку), без повторов клипов. + предупреждения."""
    warnings: list[str] = []
    seen: set[str] = set()
    result: list[Recording] = []
    files = sorted(p for p in (bdmv / "PLAYLIST").iterdir()
                   if p.is_file() and p.suffix.upper() in (".MPL", ".MPLS"))
    for p in files:
        try:
            recs = read_playlist(p)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{p.name}: не удалось прочитать ({e})")
            continue
        for r in recs:
            r.items = [it for it in r.items if it.clip not in seen]
            seen.update(it.clip for it in r.items)
            if r.items:
                result.append(r)
    return result, warnings
