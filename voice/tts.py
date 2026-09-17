"""
F.E.D.O Core — TTS (v1.4.3)

Двуязычный голос:
  - Русский: Silero v4_ru (спикер из настройки tts_speaker: aidar, eugene, ...)
  - Английский: Silero v3_en (голос en_0, подгружается лениво
    при первом английском ответе; у Silero английского v4/v5 нет —
    последний английский — v3)
  - Другие письменности (например, китайский): молчим —
    F.E.D.O. умеет писать, но говорить на них пока не научился.

Язык ответа определяется автоматически по письменности
(кириллица / латиница).
"""
import sys
import os
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


def _speak_blocking(text: str):
    if not VOICE_ENABLED or not text:
        return

    safe_text = str(text).strip()
    if not safe_text:
        return

    lang = _detect_lang(safe_text)

    if lang == "other":
        # F.E.D.O. умеет писать, но не озвучивать другие письменности
        return

    with _tts_lock:
        model = _load_model(lang)

    if model is None:
        return

    try:
        tts_kwargs = {
            "text": safe_text,
            "sample_rate": sample_rate,
        }

        if lang == "ru":
            # русский: спикер из настроек (aidar и т.д.)
            speaker = _get_speaker()
            if speaker:
                tts_kwargs["speaker"] = speaker
        else:
            # английский: голос en_0 (у v3_en 118 голосов: en_0..en_117)
            tts_kwargs["speaker"] = "en_0"

        audio = model.apply_tts(**tts_kwargs)

        sd.play(audio, sample_rate)
        sd.wait()

    except Exception as error:
        print(f"[VOICE] Ошибка озвучки ({lang}): {error}")


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


def get_tts_status():
    if not VOICE_ENABLED:
        return "OFF"

    if tts_models:
        langs = "+".join(sorted(l.upper() for l in tts_models))
        return f"ACTIVE ({langs})"

    return "WAIT"


def get_tts_error():
    return tts_error
