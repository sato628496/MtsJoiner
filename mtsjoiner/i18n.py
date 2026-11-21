"""Тексты интерфейса на русском и английском."""

from __future__ import annotations

import locale
import sys

LANGS = {"ru": "Русский", "en": "English"}
_lang = "ru"


def detect_lang() -> str:
    try:
        if sys.platform == "win32":
            import ctypes
            primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            # русский, украинский, белорусский, казахский, узбекский, киргизский, татарский
            return "ru" if primary in (0x19, 0x22, 0x23, 0x3F, 0x43, 0x40, 0x44) else "en"
        loc = (locale.getlocale()[0] or "").lower()
        return "ru" if loc.startswith(("ru", "uk", "be", "kk")) else "en"
    except Exception:
        return "en"


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGS else "en"


def get_lang() -> str:
    return _lang


def T(key: str, **kw) -> str:
    s = STRINGS.get(key, {})
    text = s.get(_lang) or s.get("en") or s.get("ru") or key
    return text.format(**kw) if kw else text


STRINGS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ общие
    "app.subtitle": {"ru": "склейка видео с AVCHD-камер без разрывов",
                     "en": "seamless joiner for AVCHD camcorder clips"},
    "lang": {"ru": "Язык:", "en": "Language:"},
    "help": {"ru": "❓ Справка", "en": "❓ Help"},
    "browse": {"ru": "Обзор…", "en": "Browse…"},
    "auto": {"ru": "Авто", "en": "Auto"},

    # ------------------------------------------------------------------ шаг 1
    "step1": {"ru": "① Где лежат видео", "en": "① Where are the videos"},
    "src.label": {"ru": "Папка с MTS:", "en": "MTS folder:"},
    "src.tip": {"ru": "Папка с файлами .MTS — прямо на карте памяти (…\\PRIVATE\\AVCHD\\BDMV\\STREAM) "
                      "или скопированная на компьютер. Порядок и состав записей программа определит сама.",
                "en": "Folder with .MTS files — on the memory card (…\\PRIVATE\\AVCHD\\BDMV\\STREAM) "
                      "or copied to your computer. The program works out the order and takes by itself."},
    "meta.label": {"ru": "Метаданные камеры:", "en": "Camera metadata:"},
    "meta.tip": {"ru": "Необязательно, но желательно. Папка PRIVATE, AVCHD или BDMV с карты (или её копия): "
                       "в ней PLAYLIST и CLIPINF — «инструкция» камеры, из каких файлов состоит каждая запись. "
                       "С ней программа точно знает дубли, время записи, узнаёт переименованные файлы и "
                       "называет пропавшие.",
                 "en": "Optional but recommended. The PRIVATE, AVCHD or BDMV folder from the card (or a copy): "
                       "its PLAYLIST and CLIPINF tell which files make up each recording. With it the program "
                       "knows the takes exactly, shows recording times, recognizes renamed files and names "
                       "missing ones."},
    "scan": {"ru": "🔍 Найти дубли", "en": "🔍 Find takes"},
    "scan.tip": {"ru": "Проанализировать файлы и показать список записей (дублей).",
                 "en": "Analyze the files and list the recordings (takes)."},
    "meta.none": {"ru": "не указаны — дубли определяются по меткам времени в самих файлах",
                  "en": "not set — takes are detected from timestamps inside the files"},
    "meta.ok": {"ru": "✔ найдены PLAYLIST/CLIPINF: {path}", "en": "✔ found PLAYLIST/CLIPINF: {path}"},
    "meta.bad": {"ru": "✖ в «{path}» нет папок PLAYLIST и CLIPINF",
                 "en": "✖ no PLAYLIST and CLIPINF folders in “{path}”"},

    # ------------------------------------------------------------------ шаг 2
    "step2": {"ru": "② Что склеить — отметьте дубли (одно нажатие REC = один дубль)",
              "en": "② What to join — tick the takes (one REC press = one take)"},
    "col.take": {"ru": "Дубль", "en": "Take"},
    "col.files": {"ru": "Файлы", "en": "Files"},
    "col.start": {"ru": "Начало", "en": "Start"},
    "col.dur": {"ru": "Длительность", "en": "Duration"},
    "col.size": {"ru": "Размер", "en": "Size"},
    "col.note": {"ru": "Примечание", "en": "Note"},
    "tree.tip": {"ru": "Щёлкните по ☑, чтобы включить/выключить дубль (или выделите строки и нажмите Пробел). "
                       "Длинная запись состоит из нескольких файлов по 2 ГБ — они склеиваются без разрывов. "
                       "Номер вида 6.1 / 6.2 — части одной записи, между которыми не хватает файла.",
                 "en": "Click ☑ to include/exclude a take (or select rows and press Space). "
                       "A long recording consists of several 2 GB files — they are joined seamlessly. "
                       "Numbers like 6.1 / 6.2 are parts of one recording with a missing file in between."},
    "sel.all": {"ru": "Выбрать все", "en": "Select all"},
    "sel.none": {"ru": "Снять все", "en": "Select none"},
    "sel.long": {"ru": "Только длиннее 1 мин", "en": "Only longer than 1 min"},
    "sel.long.tip": {"ru": "Отключить короткие случайные записи (настройка, пол, карман).",
                     "en": "Skip short accidental clips (setup, floor, pocket)."},
    "sel.info": {"ru": "Выбрано: {n} из {total} · {dur} · {size}", "en": "Selected: {n} of {total} · {dur} · {size}"},
    "note.seamless": {"ru": "склейка без разрывов", "en": "seamless join"},
    "approx": {"ru": "≈", "en": "≈"},
    "empty.hint": {"ru": "Шаг 1: выберите папку с MTS-файлами и нажмите «Найти дубли».",
                   "en": "Step 1: choose the folder with MTS files and press “Find takes”."},

    # ------------------------------------------------------------------ шаг 3
    "step3": {"ru": "③ Каким должен быть результат", "en": "③ What the result should be"},
    "preset": {"ru": "Пресет:", "en": "Preset:"},
    "preset.tip": {"ru": "Готовые наборы настроек под задачу. Любую настройку ниже можно поменять — "
                         "тогда пресет станет «Свои настройки».",
                   "en": "Ready-made settings for a task. You can change anything below — "
                         "the preset then becomes “Custom”."},
    "preset.custom": {"ru": "Свои настройки", "en": "Custom"},
    "preset.custom.hint": {"ru": "Параметры настроены вручную.", "en": "Settings adjusted manually."},
    "mode": {"ru": "Склейка:", "en": "Output:"},
    "mode.per_take": {"ru": "файл на каждый дубль", "en": "one file per take"},
    "mode.single": {"ru": "все выбранные дубли в один файл", "en": "all selected takes in one file"},
    "mode.tip": {"ru": "«Файл на каждый дубль» — каждая запись отдельным файлом (куски по 2 ГБ внутри неё "
                       "склеиваются всегда). «В один файл» — весь концерт одним видео; между дублями будет "
                       "обычная склейка (камера в это время не писала).",
                 "en": "“One file per take” — each recording as a separate file (its 2 GB pieces are always "
                       "joined). “One file” — the whole show as one video; takes are butted together "
                       "(the camera wasn’t recording in between)."},
    "video": {"ru": "Видео", "en": "Video"},
    "video.mode": {"ru": "Видео:", "en": "Video:"},
    "video.copy": {"ru": "Копировать без изменений (1:1)", "en": "Copy unchanged (1:1)"},
    "video.h264": {"ru": "H.264 — перекодировать", "en": "H.264 — re-encode"},
    "video.hevc": {"ru": "HEVC / H.265 — перекодировать", "en": "HEVC / H.265 — re-encode"},
    "video.tip": {"ru": "«Копировать» — без потери качества и очень быстро (битрейт как с камеры). "
                        "Перекодирование нужно, только чтобы уменьшить файл (Telegram, хранение).",
                  "en": "“Copy” — no quality loss and very fast (camera bitrate). "
                        "Re-encode only to make the file smaller (Telegram, storage)."},
    "encoder": {"ru": "Кодировщик:", "en": "Encoder:"},
    "encoder.tip": {"ru": "Чем кодировать. Видеокарта (NVIDIA NVENC / AMD AMF / Intel QuickSync) в 3–8 раз "
                          "быстрее процессора почти без разницы в качестве. В списке только то, что реально "
                          "работает на этом компьютере.",
                    "en": "What does the encoding. A GPU (NVIDIA NVENC / AMD AMF / Intel QuickSync) is 3–8× "
                          "faster than the CPU at almost the same quality. Only encoders that actually work "
                          "on this computer are listed."},
    "encoder.auto": {"ru": "авто", "en": "auto"},
    "encoder.none": {"ru": "нет рабочих кодировщиков", "en": "no working encoders"},
    "rate.quality": {"ru": "Качество:", "en": "Quality:"},
    "rate.quality.hint": {"ru": "(меньше — лучше; 18 ≈ без видимых потерь, 23 — экономно)",
                          "en": "(lower is better; 18 ≈ visually lossless, 23 — compact)"},
    "rate.quality.tip": {"ru": "Постоянное качество: файл получится такого размера, какой нужен сцене. "
                               "Шкала как у CRF: 16–18 — почти неотличимо, 20–23 — хорошо и компактно, 26+ — заметно хуже.",
                         "en": "Constant quality: the file gets as big as the scene needs. CRF-like scale: "
                               "16–18 — nearly identical, 20–23 — good and compact, 26+ — visibly worse."},
    "rate.size": {"ru": "Лимит файла, МБ:", "en": "File limit, MB:"},
    "rate.size.hint": {"ru": "(Telegram: 1950, Premium: 3900)", "en": "(Telegram: 1950, Premium: 3900)"},
    "rate.size.tip": {"ru": "Подобрать битрейт так, чтобы каждый файл влез в лимит. Если битрейта мало, "
                            "картинка уменьшится до 720p, а очень длинная запись разрежется на части.",
                      "en": "Pick the bitrate so every file fits the limit. If the bitrate gets too low the "
                            "picture is scaled to 720p, and a very long recording is split into parts."},
    "height": {"ru": "Разрешение:", "en": "Resolution:"},
    "height.0": {"ru": "как в исходнике", "en": "same as source"},
    "height.1080": {"ru": "1080p", "en": "1080p"},
    "height.720": {"ru": "720p", "en": "720p"},
    "height.-1": {"ru": "авто (под лимит)", "en": "auto (fit the limit)"},
    "audio.box": {"ru": "Звук и файл", "en": "Audio and file"},
    "audio": {"ru": "Звук:", "en": "Audio:"},
    "audio.pcm": {"ru": "PCM 24 бит — без потерь", "en": "PCM 24-bit — lossless"},
    "audio.copy": {"ru": "AC3 — оригинал (копия)", "en": "AC3 — original (copy)"},
    "audio.aac": {"ru": "AAC", "en": "AAC"},
    "audio.tip": {"ru": "PCM — без потерь, его читает любой видеоредактор (+≈3 ГБ на час). AC3 — бит-в-бит как с камеры, "
                        "но некоторые редакторы его не открывают (например, Premiere Pro на Windows 11 24H2+). "
                        "AAC — для YouTube/Telegram/плееров.",
                  "en": "PCM — lossless, every video editor reads it (+≈3 GB per hour). AC3 — bit-exact camera audio, "
                        "but some editors can’t open it (e.g. Premiere Pro on Windows 11 24H2+). "
                        "AAC — for YouTube/Telegram/players."},
    "kbps": {"ru": "кбит/с", "en": "kbps"},
    "channels": {"ru": "Каналы:", "en": "Channels:"},
    "ch.51": {"ru": "5.1 как с камеры", "en": "5.1 as recorded"},
    "ch.st": {"ru": "стерео (сведение)", "en": "stereo (downmix)"},
    "channels.tip": {"ru": "Камера пишет 5.1 со встроенных микрофонов. Стерео удобнее для телефонов и Telegram.",
                     "en": "The camera records 5.1 from its built-in mics. Stereo suits phones and Telegram better."},
    "container": {"ru": "Контейнер:", "en": "Container:"},
    "container.tip": {"ru": "MP4 — универсальный. MOV — для монтажа (нужен для звука PCM). "
                            "MKV — для архива и плееров (многие видеоредакторы его не открывают).",
                      "en": "MP4 — universal. MOV — for editing (needed for PCM audio). "
                            "MKV — for archives and players (many video editors can’t open it)."},
    "faststart": {"ru": "Быстрый старт (для онлайн-просмотра, Telegram)",
                  "en": "Fast start (for streaming, Telegram)"},
    "faststart.tip": {"ru": "Перенести оглавление файла в начало, чтобы видео начинало играть в чате/браузере "
                            "до полной загрузки. Требует ещё одного прохода записи.",
                      "en": "Move the file index to the beginning so the video starts playing in a chat/browser "
                            "before it is fully downloaded. Costs one extra write pass."},
    "proxies": {"ru": "Прокси для монтажа (ProRes Proxy 960×540 → папка Proxies)",
                "en": "Editing proxies (ProRes Proxy 960×540 → Proxies folder)"},
    "proxies.tip": {"ru": "Лёгкие копии для плавного монтажа даже с внешнего диска. Premiere Pro: выделить клипы → "
                          "Proxy → Attach Proxies → папка Proxies. DaVinci Resolve: правый щелчок по клипу → "
                          "Link Proxy Media. Экспорт всё равно идёт из оригиналов.",
                    "en": "Light copies for smooth editing even from an external drive. Premiere Pro: select clips → "
                          "Proxy → Attach Proxies → the Proxies folder. DaVinci Resolve: right-click a clip → "
                          "Link Proxy Media. Export still uses the originals."},
    "out": {"ru": "Куда сохранить:", "en": "Save to:"},
    "out.auto": {"ru": "подпапка «joined» у исходников", "en": "“joined” subfolder next to sources"},
    "out.tip": {"ru": "Папка для результата. По умолчанию — подпапка joined рядом с MTS-файлами.",
                "en": "Where to save. By default — a “joined” subfolder next to the MTS files."},
    "ffmpeg": {"ru": "ffmpeg:", "en": "ffmpeg:"},
    "ffmpeg.tip": {"ru": "Программа использует бесплатный ffmpeg. Нажмите «Авто», чтобы найти его, или укажите "
                         "ffmpeg.exe вручную. Если ffmpeg нет — кнопка «Установить ffmpeg».",
                   "en": "The program uses the free ffmpeg. Press “Auto” to find it, or pick ffmpeg.exe manually. "
                         "No ffmpeg? Use the “Install ffmpeg” button."},
    "ffmpeg.install": {"ru": "Установить ffmpeg", "en": "Install ffmpeg"},
    "ffmpeg.checking": {"ru": "проверяю кодировщики…", "en": "checking encoders…"},
    "ffmpeg.missing": {"ru": "✖ ffmpeg не найден — нажмите «Установить ffmpeg» или укажите ffmpeg.exe",
                       "en": "✖ ffmpeg not found — press “Install ffmpeg” or pick ffmpeg.exe"},
    "ffmpeg.ok": {"ru": "✔ {ver}; перекодирование: {enc}", "en": "✔ {ver}; re-encoding: {enc}"},
    "ffmpeg.noenc": {"ru": "нет (только склейка)", "en": "none (joining only)"},
    "ffmpeg.noprobe": {"ru": " · ffprobe нет — встроенный анализатор", "en": " · no ffprobe — built-in analyzer"},
    "ffmpeg.install.ask": {"ru": "Скачать и установить бесплатный ffmpeg (полная сборка Gyan.FFmpeg, ~90 МБ) "
                                 "через winget?\n\nОткроется окно установки; когда оно закроется, программа "
                                 "сама найдёт ffmpeg.",
                           "en": "Download and install the free ffmpeg (Gyan.FFmpeg full build, ~90 MB) "
                                 "with winget?\n\nAn installer window will open; when it closes the program "
                                 "will find ffmpeg automatically."},
    "ffmpeg.install.nowinget": {"ru": "winget не найден. Откроется страница загрузки ffmpeg — скачайте "
                                      "«ffmpeg-release-full.7z», распакуйте и укажите ffmpeg.exe в программе.",
                                "en": "winget not found. The ffmpeg download page will open — get "
                                      "“ffmpeg-release-full.7z”, unpack it and point the program to ffmpeg.exe."},
    "ffmpeg.installed": {"ru": "Установка ffmpeg завершена — ищу ffmpeg…", "en": "ffmpeg setup finished — looking for ffmpeg…"},
    "ffmpeg.err": {"ru": "Не найден ffmpeg.exe.\nНажмите «Установить ffmpeg» или укажите путь вручную.",
                   "en": "ffmpeg.exe not found.\nPress “Install ffmpeg” or set the path manually."},

    # ------------------------------------------------------------------ шаг 4
    "start": {"ru": "▶  Склеить", "en": "▶  Join"},
    "start.tip": {"ru": "Запустить обработку выбранных дублей.", "en": "Process the selected takes."},
    "stop": {"ru": "■  Стоп", "en": "■  Stop"},
    "open": {"ru": "Открыть папку", "en": "Open folder"},
    "log": {"ru": "Журнал", "en": "Log"},

    # ------------------------------------------------------------------ предупреждения формата
    "warn.pcm_mp4": {"ru": "PCM в MP4 не поддерживается — файл будет записан как MOV.",
                     "en": "PCM can’t go into MP4 — the file will be written as MOV."},
    "warn.ac3": {"ru": "AC3: некоторые видеоредакторы не читают этот звук (например, Premiere Pro на Windows 11 24H2+). "
                       "Для монтажа надёжнее PCM.",
                 "en": "AC3: some video editors can’t read this audio (e.g. Premiere Pro on Windows 11 24H2+). "
                       "PCM is safer for editing."},
    "warn.mkv": {"ru": "MKV многие видеоредакторы не импортируют — подходит для архива и плееров.",
                 "en": "Many video editors can’t import MKV — use it for archives and players."},
    "warn.noenc": {"ru": "В текущем ffmpeg нет рабочего кодировщика для перекодирования — нажмите «Установить ffmpeg».",
                   "en": "The current ffmpeg has no working encoder for re-encoding — press “Install ffmpeg”."},
    "warn.height": {"ru": "Совет: разрешение «авто» само уменьшит картинку до 720p, если битрейта мало.",
                    "en": "Tip: “auto” resolution scales down to 720p by itself when the bitrate is low."},

    # ------------------------------------------------------------------ статусы и диалоги
    "status.scanning": {"ru": "Анализ файлов… {d}/{n}", "en": "Analyzing files… {d}/{n}"},
    "status.scanned": {"ru": "Файлов: {files}, дублей: {recs} ({src}){broken}. Шаг 2: отметьте дубли, шаг 3: выберите пресет, затем «Склеить».",
                       "en": "Files: {files}, takes: {recs} ({src}){broken}. Step 2: tick the takes, step 3: pick a preset, then “Join”."},
    "status.src.meta": {"ru": "по метаданным камеры", "en": "from camera metadata"},
    "status.src.ts": {"ru": "по меткам времени", "en": "from timestamps"},
    "status.broken": {"ru": ", с пропусками: {n}", "en": ", with gaps: {n}"},
    "status.progress": {"ru": "[{i}/{n}] {title} — {pct}%", "en": "[{i}/{n}] {title} — {pct}%"},
    "status.stopping": {"ru": "Останавливаю…", "en": "Stopping…"},
    "status.stopped": {"ru": "Остановлено.", "en": "Stopped."},
    "status.done": {"ru": "Готово!", "en": "Done!"},
    "status.failed": {"ru": "Завершено с ошибками — см. журнал.", "en": "Finished with errors — see the log."},
    "dlg.nofolder": {"ru": "Папка с MTS не найдена.", "en": "MTS folder not found."},
    "dlg.nosel": {"ru": "Не выбрано ни одного дубля.", "en": "No takes selected."},
    "dlg.noout": {"ru": "Укажите папку для сохранения.", "en": "Choose where to save."},
    "dlg.noenc": {"ru": "Для перекодирования нужен ffmpeg с кодировщиком {codec}. Нажмите «Установить ffmpeg».",
                  "en": "Re-encoding needs ffmpeg with a {codec} encoder. Press “Install ffmpeg”."},
    "dlg.mixed": {"ru": "У выбранных дублей разные параметры видео/звука — склейка в один файл может получиться "
                        "некорректной. Продолжить?",
                  "en": "The selected takes have different video/audio formats — joining them into one file may "
                        "fail. Continue?"},
    "dlg.space": {"ru": "Нужно примерно {need}, а свободно {free}.\nВсё равно продолжить?",
                  "en": "About {need} is needed but only {free} is free.\nContinue anyway?"},
    "dlg.outerr": {"ru": "Не удаётся создать папку вывода:\n{e}", "en": "Can’t create the output folder:\n{e}"},
    "dlg.done": {"ru": "Готово! Открыть папку с результатом?", "en": "Done! Open the output folder?"},
    "dlg.quit": {"ru": "Идёт обработка. Остановить и выйти?", "en": "Processing is running. Stop and quit?"},
    "pick.src": {"ru": "Папка с MTS-файлами", "en": "Folder with MTS files"},
    "pick.meta": {"ru": "Папка с метаданными камеры (PRIVATE, AVCHD или BDMV)",
                  "en": "Camera metadata folder (PRIVATE, AVCHD or BDMV)"},
    "pick.out": {"ru": "Куда сохранять", "en": "Where to save"},
    "log.start": {"ru": "— Старт: {n} заданий, видео: {enc}, ожидаемый объём ≈ {size}",
                  "en": "— Start: {n} jobs, video: {enc}, expected size ≈ {size}"},
    "log.copy": {"ru": "копия", "en": "copy"},
    "log.done": {"ru": "— Всё готово.", "en": "— All done."},
    "log.folder": {"ru": "Папка: {path} — {files} файлов, {recs} дублей {src}. Видео {w}×{h} {fps}, звук {ac} {ch} кан.",
                   "en": "Folder: {path} — {files} files, {recs} takes {src}. Video {w}×{h} {fps}, audio {ac} {ch} ch."},
    "log.gapjoin": {"ru": "ℹ Части дублей с пропущенными файлами будут склеены встык (пропущенный фрагмент "
                          "восстановить невозможно).",
                    "en": "ℹ Parts of takes with missing files will be butted together (a missing piece "
                          "can’t be recovered)."},
    "log.scanerr": {"ru": "Ошибка анализа: {e}", "en": "Analysis error: {e}"},

    # ------------------------------------------------------------------ ядро
    "core.missing": {"ru": "нет файла {names} (≈{dur})", "en": "missing file {names} (≈{dur})"},
    "core.missing_noname": {"ru": "не хватает ≈{dur}", "en": "≈{dur} missing"},
    "core.no_start": {"ru": "нет начала записи (≈{dur})", "en": "recording start missing (≈{dur})"},
    "core.start_of": {"ru": "начало записи: {what}", "en": "recording start: {what}"},
    "core.end_of": {"ru": "конец записи: {what}", "en": "recording end: {what}"},
    "core.dup": {"ru": "Пропущен дубликат: {name} (тот же клип, что {other})",
                 "en": "Skipped duplicate: {name} (same clip as {other})"},
    "core.dup2": {"ru": "Пропущен дубликат: {name} (= {other})", "en": "Skipped duplicate: {name} (= {other})"},
    "core.nonum": {"ru": "Пропущен (не номерное имя): {name}", "en": "Skipped (not a numbered name): {name}"},
    "core.nonum_meta": {"ru": "Пропущен (не номерное имя и нет в метаданных): {name}",
                        "en": "Skipped (not a numbered name and not in metadata): {name}"},
    "core.badsize": {"ru": "⚠ {name}: размер {size} Б, а по метаданным {meta} Б — файл мог быть скопирован не полностью.",
                     "en": "⚠ {name}: size {size} B but metadata says {meta} B — the file may be incompletely copied."},
    "core.nometa": {"ru": "В «{path}» не найдены папки PLAYLIST и CLIPINF — дубли определены по меткам времени.",
                    "en": "No PLAYLIST and CLIPINF folders in “{path}” — takes detected from timestamps."},
    "core.notinmeta": {"ru": "Файлов нет в метаданных камеры: {n} — сгруппированы по меткам времени.",
                       "en": "{n} file(s) are not in the camera metadata — grouped by timestamps."},
    "core.noenc": {"ru": "В ffmpeg нет рабочего кодировщика {codec}.", "en": "ffmpeg has no working {codec} encoder."},
    "core.novideo": {"ru": "нет видеодорожки", "en": "no video stream"},
    "core.nodur": {"ru": "не удалось прочитать длительность", "en": "can’t read the duration"},
    "core.all_takes": {"ru": "Все дубли", "en": "All takes"},
    "core.take": {"ru": "Дубль {label}", "en": "Take {label}"},
    "core.proxy": {"ru": "Прокси", "en": "Proxy"},
    "core.kbps": {"ru": "кбит/с", "en": "kbps"},
    "file.take": {"ru": "дубль", "en": "take"},
    "file.part": {"ru": "ч", "en": "p"},
    "file.concert": {"ru": "концерт", "en": "concert"},
    "file.takes": {"ru": "дубли", "en": "takes"},
    "file.piece": {"ru": "часть{k}из{n}", "en": "part{k}of{n}"},
    "run.stopped": {"ru": "■ Остановлено пользователем, недописанный файл удалён.",
                    "en": "■ Stopped by user, the unfinished file was deleted."},
    "run.done": {"ru": "✔ Готово: {path}", "en": "✔ Done: {path}"},
    "run.fail": {"ru": "✖ ffmpeg завершился с кодом {rc}:", "en": "✖ ffmpeg exited with code {rc}:"},
    "run.noproxy": {"ru": "  пропуск: нет исходного файла для прокси", "en": "  skipped: no source file for the proxy"},

    # ------------------------------------------------------------------ кодировщики
    "enc.libx264": {"ru": "x264 (процессор, лучшее качество)", "en": "x264 (CPU, best quality)"},
    "enc.libx265": {"ru": "x265 (процессор, медленно)", "en": "x265 (CPU, slow)"},
    "enc.nvenc": {"ru": "NVIDIA NVENC (видеокарта)", "en": "NVIDIA NVENC (GPU)"},
    "enc.amf": {"ru": "AMD AMF (видеокарта)", "en": "AMD AMF (GPU)"},
    "enc.qsv": {"ru": "Intel QuickSync (видеокарта)", "en": "Intel QuickSync (GPU)"},
    "enc.mf": {"ru": "Windows Media Foundation", "en": "Windows Media Foundation"},

    # ------------------------------------------------------------------ пресеты
    "p.edit": {"ru": "Для монтажа — без потерь", "en": "For editing — lossless"},
    "p.edit.hint": {"ru": "Видео 1:1 без перекодирования, звук PCM 5.1 24 бит — открывается в любом видеоредакторе "
                          "(Premiere Pro, DaVinci Resolve, Vegas, Final Cut, Shotcut…). "
                              "Идеально и для заливки на YouTube, если не жалко объёма.",
                        "en": "Video 1:1 without re-encoding, PCM 5.1 24-bit audio — opens in any video editor "
                              "(Premiere Pro, DaVinci Resolve, Vegas, Final Cut, Shotcut…). "
                              "Also perfect for YouTube uploads if file size doesn’t matter."},
    "p.archive": {"ru": "Архив — бит-в-бит как с камеры", "en": "Archive — bit-exact as recorded"},
    "p.archive.hint": {"ru": "Видео и звук AC3 копируются без изменений, просто склеены. Минимальный объём без потерь.",
                       "en": "Video and AC3 audio are copied unchanged, just joined. Smallest lossless size."},
    "p.youtube": {"ru": "YouTube — без потерь", "en": "YouTube — lossless"},
    "p.youtube.hint": {"ru": "Видео 1:1 (≈25 Мбит/с — выше рекомендации YouTube для 1080p50), звук AAC 512 кбит/с 5.1 — "
                             "максимум из рекомендаций YouTube. YouTube всё равно перекодирует, так что лучше не сделать.",
                       "en": "Video 1:1 (≈25 Mbps — above YouTube’s 1080p50 recommendation), AAC 512 kbps 5.1 audio — "
                             "the top of YouTube’s recommendations. YouTube re-encodes anyway, so this is the best possible."},
    "p.telegram": {"ru": "Telegram — под лимит файла", "en": "Telegram — fit the file limit"},
    "p.telegram.hint": {"ru": "H.264 + AAC стерео, «быстрый старт» для просмотра в чате. Битрейт подбирается так, чтобы "
                              "файл влез в лимит (2 ГБ, с Premium — 4 ГБ); длинная запись режется на части.",
                        "en": "H.264 + stereo AAC, “fast start” for in-chat playback. The bitrate is chosen so the file "
                              "fits the limit (2 GB, Premium 4 GB); long recordings are split into parts."},
    "p.economy": {"ru": "Экономичный — в 3–5 раз меньше", "en": "Compact — 3–5× smaller"},
    "p.economy.hint": {"ru": "HEVC (H.265) 1080p50 с постоянным качеством, звук AAC 5.1 384 кбит/с. Визуально почти "
                             "без потерь — для хранения и просмотра, когда оригинал слишком тяжёлый.",
                       "en": "HEVC (H.265) 1080p50 at constant quality, AAC 5.1 384 kbps. Visually near-lossless — "
                             "for storage and viewing when the original is too heavy."},
}

HELP = {
    "ru": """MTS JOINER — КАК ПОЛЬЗОВАТЬСЯ

Зачем это нужно
AVCHD-камера (Sony Handycam и др.) пишет одну длинную запись кусками по 2 ГБ (~10 минут). Если поставить эти куски в видеоредактор (Premiere Pro, DaVinci Resolve, Vegas…) по отдельности, на каждом стыке ~0,77 с звука на чёрном экране и ~0,77 с картинки без звука. Программа склеивает куски обратно в цельную запись — без разрывов и без перекодирования, качество и битрейт как с камеры.

Шаг ① — где лежат видео
• «Папка с MTS» — папка с файлами .MTS (на карте: PRIVATE\\AVCHD\\BDMV\\STREAM, или их копия на диске).
• «Метаданные камеры» (желательно) — папка PRIVATE, AVCHD или BDMV с карты или её копия. С ними программа точно знает, из каких файлов состоит каждая запись, показывает время записи, узнаёт переименованные файлы и называет пропавшие.
• Нажмите «Найти дубли».

Шаг ② — что склеить
• Каждая строка — одна запись (одно нажатие REC). Щёлкните ☑, чтобы включить/выключить.
• «склейка без разрывов» — запись из нескольких файлов по 2 ГБ.
• 6.1 / 6.2 — части одной записи, между которыми не хватает файла (он указан в примечании).

Шаг ③ — каким должен быть результат
• «Для монтажа» — для любого видеоредактора (видео 1:1, звук PCM без потерь).
• «Архив» — бит-в-бит как с камеры.
• «YouTube» — заливать сразу на YouTube без потерь.
• «Telegram» — файл под лимит 2 ГБ (4 ГБ с Premium).
• «Экономичный» — в 3–5 раз меньше, почти без видимых потерь.
• «Файл на каждый дубль» или «все в один файл» — как удобнее монтировать.
• «Прокси» — лёгкие копии для плавного монтажа (Premiere Pro: Proxy → Attach Proxies; DaVinci Resolve: правый щелчок по клипу → Link Proxy Media).

Шаг ④ — «Склеить». Результат — в подпапке joined рядом с исходниками (или где укажете).

Наведите мышь на любой элемент — появится подсказка.

ffmpeg
Программа использует бесплатный ffmpeg. Если его нет — кнопка «Установить ffmpeg» (через winget). Подойдёт и уже установленный: из FFmpeg Batch AV Converter, Shutter Encoder, Bitwig и т.п. — укажите ffmpeg.exe. Для простой склейки хватает любого ffmpeg; для Telegram/Экономичного нужен ffmpeg с H.264/HEVC-кодировщиками (полная сборка).

Частые вопросы
• Камера записала много файлов вместо одного — это нормально? Да, так работают все AVCHD-камеры (лимит 2 ГБ на файл). Программа соберёт их обратно.
• Видеоредактор не видит звук в MTS (частая ситуация с Premiere Pro на Windows 11) — выберите звук PCM (пресет «Для монтажа»).
• Можно переименовать файлы, чтобы они проигрались как один? Нет, плейлист камеры ссылается на имена. А программа узнает переименованные файлы по метаданным.
• Пропал один файл — запись будет в двух частях; в режиме «в один файл» части склеятся встык.
• Тормозит предпросмотр — включите «Прокси».
""",
    "en": """MTS JOINER — HOW TO USE

Why
An AVCHD camcorder (Sony Handycam etc.) splits one long recording into 2 GB pieces (~10 minutes). Put those pieces into a video editor (Premiere Pro, DaVinci Resolve, Vegas…) one by one and every join gets ~0.77 s of audio over black and ~0.77 s of picture without sound. This program joins the pieces back into one recording — seamlessly and without re-encoding, at the camera’s quality and bitrate.

Step ① — where are the videos
• “MTS folder” — the folder with .MTS files (on the card: PRIVATE\\AVCHD\\BDMV\\STREAM, or a copy on disk).
• “Camera metadata” (recommended) — the PRIVATE, AVCHD or BDMV folder from the card or its copy. With it the program knows exactly which files form each recording, shows recording times, recognizes renamed files and names missing ones.
• Press “Find takes”.

Step ② — what to join
• Each row is one recording (one REC press). Click ☑ to include/exclude.
• “seamless join” — a recording made of several 2 GB files.
• 6.1 / 6.2 — parts of one recording with a missing file in between (named in the note).

Step ③ — what the result should be
• “For editing” — for any video editor (video 1:1, lossless PCM audio).
• “Archive” — bit-exact as recorded.
• “YouTube” — upload straight to YouTube without loss.
• “Telegram” — fits the 2 GB limit (4 GB with Premium).
• “Compact” — 3–5× smaller, nearly no visible loss.
• “One file per take” or “all in one file” — whatever is easier to edit.
• “Proxies” — light copies for smooth editing (Premiere Pro: Proxy → Attach Proxies; DaVinci Resolve: right-click a clip → Link Proxy Media).

Step ④ — “Join”. The result goes to a “joined” subfolder next to the sources (or wherever you choose).

Hover over any control to see a tip.

ffmpeg
The program uses the free ffmpeg. No ffmpeg? Use the “Install ffmpeg” button (via winget). An existing one works too: from FFmpeg Batch AV Converter, Shutter Encoder, etc. — just pick its ffmpeg.exe. Joining works with any ffmpeg; the Telegram/Compact presets need H.264/HEVC encoders (a full build).

FAQ
• My camera recorded many files instead of one — is that normal? Yes, every AVCHD camera does this (2 GB per file limit). The program joins them back.
• Your editor shows no audio for MTS (common with Premiere Pro on Windows 11) — choose PCM audio (the “For editing” preset).
• Can I rename the files so they play as one? No, the camera playlist refers to file names. The program, however, recognizes renamed files using the metadata.
• One file is missing — the recording comes out in two parts; in “one file” mode they are butted together.
• Preview stutters — enable “Proxies”.
""",
}
