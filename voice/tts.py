"""
F.E.D.O Core — TTS (v1.4.5)

Двуязычный голос:
  - Русский: Silero v4_ru (спикер из настройки tts_speaker: aidar, eugene, ...)
  - Английский: Silero v3_en (голос из настройки tts_speaker_en,
    подгружается лениво при первом английском ответе;
    у Silero английского v4/v5 нет — последний английский — v3)
  - Другие письменности (например, китайский): молчим —
    F.E.D.O. умеет писать, но говорить на них пока не научился.

Озвучка — ОДНОЙ непрерывной записью, на любом языке и при смешении:
текст разбивается на сегменты по письменности, каждый синтезируется
своей моделью (кириллица → v4_ru, латиница → v3_en),
сегменты склеиваются в один аудиопоток.
Озвучки строго последовательны (одна запись не перебивает другую).
"""
import sys
import os
import re
import threading

from config import VOICE_ENABLED
from core.settings import load_settings

if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")

try:
    import torch
    import sounddevice as sd
except Exception as error:
    torch = None
    sd = None
    print(f"[VOICE] Ошибка импорта torch/sounddevice: {error}")


sample_rate = 48000

# v1.4.3: модели по языкам (ленивая загрузка + кэш)
tts_models = {}
tts_failed = set()

tts_available = False
tts_error = None

_tts_lock = threading.Lock()


def _get_speaker():
    """
    Голос русской модели — из настройки tts_speaker.
    Голоса v4_ru: aidar, eugene, baya, kseniya, xenia, random.
    Пустое значение = голос модели по умолчанию.
    """
    try:
        speaker = str(load_settings().get("tts_speaker", "") or "").strip()
        return speaker or None
    except Exception:
        return None


def _get_speaker_en():
    """
    Голос английской модели (v3_en: en_0..en_117) — из настройки tts_speaker_en.
    """
    try:
        speaker = str(load_settings().get("tts_speaker_en", "en_10") or "").strip()
        return speaker or "en_10"
    except Exception:
        return "en_10"


def _detect_lang(text: str) -> str:
    """
    Определить язык по письменности:
      "ru"    — кириллица преобладает
      "en"    — латиница преобладает
      "other" — остальное (CJK и т.п.) / пусто
    """
    cyrillic = 0
    latin = 0

    for ch in str(text or ""):
        if "а" <= ch <= "я" or "А" <= ch <= "Я" or ch in "ёЁ":
            cyrillic += 1
        elif "a" <= ch <= "z" or "A" <= ch <= "Z":
            latin += 1

    if cyrillic == 0 and latin == 0:
        return "other"

    return "ru" if cyrillic >= latin else "en"


def _load_model(lang: str):
    """
    Загрузить Silero-модель для lang ("ru" / "en"), закэшировать.
    Вызывать, держа _tts_lock (сам лок не берёт).
    Повторные загрузки не выполняются; после сбоя в рамках сессии
    не повторяются (чтобы не hammer'ить скачивание).
    """
    if lang in tts_models:
        return tts_models[lang]

    if lang in tts_failed:
        return None

    if torch is None or sd is None:
        tts_failed.add(lang)
        return None

    if lang == "ru":
        print("[VOICE] Загрузка Silero TTS (русский, v4_ru)...")
        hub_kwargs = dict(language="ru", speaker="v4_ru")
    else:
        print("[VOICE] Загрузка Silero TTS (английский, v3_en)...")
        # v4_en/v5_en в Silero не существует — английский = v3_en
        hub_kwargs = dict(language="en", speaker="v3_en")

    try:
        loaded_model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            trust_repo=True,
            **hub_kwargs
        )

        if loaded_model is None:
            raise RuntimeError("Silero TTS вернул пустую модель.")

        tts_models[lang] = loaded_model
        print(f"[VOICE] Silero TTS {lang.upper()} активен.")
        return loaded_model

    except Exception as error:
        tts_failed.add(lang)
        print(f"[VOICE] Не удалось загрузить TTS {lang}: {error}")
        return None


def init_tts():
    """Инициализация русской модели (первый голос / запуск)."""
    global tts_available, tts_error

    with _tts_lock:
        if not VOICE_ENABLED:
            tts_available = False
            tts_error = "Голос отключён в config.py."
            print(f"[VOICE] {tts_error}")
            return False

        model = _load_model("ru")
        tts_available = model is not None
        if model is None:
            tts_error = tts_error or "Не удалось загрузить модель TTS."
        else:
            tts_error = None

        return tts_available


# v1.4.6: код НЕ озвучивается — из текста перед синтезом вырезается:
#   1. markdown-блоки ``` ... ``` (и незакрытый блок в конце)
#   2. если ответ — в основном кодовые строки → молчим полностью
_FENCE_CLOSED_RE = re.compile(r"```.*?```", re.DOTALL)
_FENCE_OPEN_RE = re.compile(r"```\w*\s*\n.*$", re.DOTALL)

_CODE_STARTERS = (
    "def ", "class ", "import ", "return ", "const ",
    "function ", "if (", "for (", "while (", "else",
    "echo ", "print(", "public ", "private ",
    "ls ", "cat ", "cd ", "rm ", "sudo ", "pip ", "pip3 ",
    "python ", "python3 ", "npm ", "git ", "curl ", "wget ",
    "mkdir ", "chmod ", "apt ", "dnf ", "systemctl ",
    "#", "//", "<", ";", "{", "}",
)
_CODE_INLINE_MARKERS = (
    ";", "{", "}", "=>", "::", "()", "=",
    "import ", "def ", "self.", "C:\\", "http",
)


def _is_code_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s.startswith(_CODE_STARTERS):
        return True
    hits = sum(1 for m in _CODE_INLINE_MARKERS if m in s)
    return hits >= 2


def _strip_code_for_speech(text: str) -> str:
    """
    v1.4.6: убрать код из текста перед озвучкой.
    Возвращает текст, который можно говорить (или "" — молчим).
    """
    safe = str(text or "")

    # 1. fenced-блоки кода (включая язык после ```)
    cleaned = _FENCE_CLOSED_RE.sub(" ", safe)
    # незакрытый блок в конце (7B часто забывает закрыть)
    cleaned = _FENCE_OPEN_RE.sub(" ", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return ""

    # 2. эвристика: ответ без оградок, но по строкам — код
    lines = [l for l in cleaned.splitlines() if l.strip()]
    if lines:
        code_lines = sum(1 for l in lines if _is_code_line(l))
        if code_lines / len(lines) >= 0.4:
            return ""

    # 3. приводим переносы (много пустых строк = длинные паузы у TTS)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)

    return cleaned.strip()


def _segment_by_script(text: str):
    """
    v1.4.5: разбить текст на сегменты (lang, text) по письменности.
    Непрерывная кириллица → "ru", непрерывная латиница → "en";
    цифры/знаки/пробелы приклеиваются к ближайшему сегменту
    (в приоритете — слева). Соседние сегменты одного языка сливаются.

    Примеры:
      "Привет, hello!"    → [("ru", "Привет, "), ("en", "hello!")]
      "Загрузка CPU 42%"  → [("ru", "Загрузка "), ("en", "CPU 42%")]
      "F.E.D.O. активен." → [("en", "F.E.D.O. "), ("ru", "активен.")]
    """
    def char_lang(ch):
        if "а" <= ch <= "я" or "А" <= ch <= "Я" or ch in "ёЁ":
            return "ru"
        if "a" <= ch <= "z" or "A" <= ch <= "Z":
            return "en"
        return None

    runs = []
    for ch in str(text or ""):
        lang = char_lang(ch)
        if runs and runs[-1][0] == lang:
            runs[-1][1].append(ch)
        else:
            runs.append([lang, [ch]])

    # приклеиваем "чужие" символы (цифры/знаки/пробелы) к соседям
    merged = []
    for lang, chars in runs:
        if lang is None:
            if merged:
                merged[-1][1].extend(chars)
            else:
                # начало текста "чужими" символами — дождёмся первой
                # настоящей письменности; если её нет — текст неозвучиваемый
                merged.append([None, list(chars)])
        else:
            if merged and merged[-1][0] is None and len(merged) == 1:
                merged[-1] = [lang, merged[-1][1] + chars]
            elif merged and merged[-1][0] == lang:
                merged[-1][1].extend(chars)
            else:
                merged.append([lang, list(chars)])

    if merged and merged[0][0] is None:
        merged = []

    return [(lang, "".join(chars)) for lang, chars in merged if lang is not None]


MAX_TTS_CHARS = 1000


def _truncate_for_speech(text: str) -> str:
    """
    Ограничить текст для озвучки: до 1000 символов, разрыв —
    по границе предложения (или хотя бы слова), чтобы не
    "проглатывать" хвост слова.
    """
    if len(text) <= MAX_TTS_CHARS:
        return text

    cut = text[:MAX_TTS_CHARS]
    last_sentence = max(cut.rfind(p) for p in (".", "!", "?"))
    if last_sentence >= MAX_TTS_CHARS // 2:
        return cut[:last_sentence + 1]

    last_space = cut.rfind(" ")
    if last_space > 0:
        return cut[:last_space] + "..."

    return cut


def _synthesize(lang: str, text: str):
    """
    Синтезировать фрагмент текста моделью lang.
    Вызывать, держа _tts_lock. Возвращает torch-тензор или None.
    """
    text = (text or "").strip()
    if not text:
        return None

    model = _load_model(lang)
    if model is None:
        return None

    try:
        tts_kwargs = {
            "text": text,
            "sample_rate": sample_rate,
        }

        if lang == "ru":
            # русский: спикер из настроек (aidar и т.д.)
            speaker = _get_speaker()
            if speaker:
                tts_kwargs["speaker"] = speaker
        else:
            # английский: голос из настроек (en_0..en_117, v3_en)
            tts_kwargs["speaker"] = _get_speaker_en()

        return model.apply_tts(**tts_kwargs)

    except Exception as error:
        print(f"[VOICE] Ошибка синтеза ({lang}): {error}")
        return None


def _speak_blocking(text: str):
    if not VOICE_ENABLED or not text:
        return

    safe_text = _strip_code_for_speech(str(text).strip())
    if not safe_text:
        # чистый код (или CJK) — F.E.D.O. молчит
        return

    safe_text = _truncate_for_speech(safe_text)
    if not safe_text:
        return

    segments = _segment_by_script(safe_text)
    if not segments:
        # F.E.D.O. умеет писать, но не озвучивать другие письменности
        return

    # v1.4.5: ОДНА непрерывная запись: каждый сегмент своей моделью,
    # затем склейка в единый аудиопоток. Всё (синтез + воспроизведение)
    # под локом — озвучки строго последовательны и не перебивают друг друга.
    with _tts_lock:
        chunks = []
        for seg_lang, seg_text in segments:
            chunk = _synthesize(seg_lang, seg_text)
            if chunk is not None:
                chunks.append(chunk)

        if not chunks:
            return

        if len(chunks) == 1:
            audio = chunks[0]
        else:
            audio = torch.cat(chunks, dim=0)

        sd.play(audio, sample_rate)
        sd.wait()


def speak(text: str):
    if not VOICE_ENABLED:
        return

    if not text:
        return

    try:
        threading.Thread(
            target=_speak_blocking,
            args=(text,),
            daemon=True
        ).start()
    except Exception as error:
        print(f"[VOICE] Ошибка запуска потока озвучки: {error}")


SAMPLE_RU = "Принято, товарищ. F.E.D.O. к вашим услугам."
SAMPLE_EN = "Good day, sir. F.E.D.O. at your service."


def audition(lang: str, speaker: str) -> bool:
    """
    v1.4.5: проиграть фразу-пример голосом lang/speaker.
    Для кнопки «Прослушать» в Настройках. Блокирующая функция —
    вызывать из фонового потока.
    """
    if not VOICE_ENABLED or lang not in ("ru", "en") or not speaker:
        return False

    with _tts_lock:
        model = _load_model(lang)
        if model is None:
            return False

        try:
            audio = model.apply_tts(
                text=SAMPLE_RU if lang == "ru" else SAMPLE_EN,
                speaker=speaker,
                sample_rate=sample_rate,
            )
            sd.play(audio, sample_rate)
            sd.wait()
            return True
        except Exception as error:
            print(f"[VOICE] Ошибка прослушивания ({lang}/{speaker}): {error}")
            return False


def preload_tts_models():
    """
    v1.5: предзагрузить RU+EN модели (фоновый поток после мастера
    первой настройки) — чтобы первый ответ не ждал скачивания.
    """
    if not VOICE_ENABLED:
        return

    try:
        with _tts_lock:
            _load_model("ru")
            _load_model("en")
    except Exception as error:
        print(f"[VOICE] Ошибка предзагрузки: {error}")


def get_tts_status():
    if not VOICE_ENABLED:
        return "OFF"

    if tts_models:
        langs = "+".join(sorted(l.upper() for l in tts_models))
        return f"ACTIVE ({langs})"

    return "WAIT"


def get_tts_error():
    return tts_error
