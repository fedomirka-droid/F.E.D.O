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


model = None
sample_rate = 48000


def _get_speaker():
    """
    v1.4: голос Silero берётся из настроек (tts_speaker).
    Пустое значение = голос по умолчанию модели (совместимо с v4).
    """
    try:
        speaker = str(load_settings().get("tts_speaker", "") or "").strip()
        return speaker or None
    except Exception:
        return None

tts_available = False
tts_initialized = False
tts_error = None

_tts_lock = threading.Lock()


def init_tts():
    global model, tts_available, tts_initialized, tts_error

    with _tts_lock:
        if tts_initialized:
            return tts_available

        tts_initialized = True

        if not VOICE_ENABLED:
            tts_available = False
            tts_error = "Голос отключён в config.py."
            print(f"[VOICE] {tts_error}")
            return False

        if torch is None or sd is None:
            model = None
            tts_available = False
            tts_error = "Модули torch или sounddevice недоступны."
            print(f"[VOICE] {tts_error}")
            print("[VOICE] Голосовой модуль отключён. F.E.D.O продолжит работу без озвучки.")
            return False

        try:
            print("[VOICE] Загрузка Silero TTS...")

            loaded_model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="ru",
                speaker="v4_ru",
                trust_repo=True
            )

            if loaded_model is None:
                raise RuntimeError("Silero TTS вернул пустую модель.")

            model = loaded_model
            tts_available = True
            tts_error = None

            print("[VOICE] Silero TTS активен.")
            return True

        except Exception as error:
            model = None
            tts_available = False
            tts_error = str(error)

            print(f"[VOICE] Ошибка TTS: {tts_error}")
            print("[VOICE] Голосовой модуль отключён. F.E.D.O продолжит работу без озвучки.")
            return False


def _speak_blocking(text: str):
    if not text:
        return

    if not init_tts():
        return

    if model is None:
        return

    try:
        safe_text = str(text).strip()

        if not safe_text:
            return

        # v1.4: speaker задаётся в настройках (tts_speaker).
        # Голоса v4_ru: aidar, eugene, baya, kseniya, xenia, random.
        # Пустое значение — голос модели по умолчанию.
        tts_kwargs = {
            "text": safe_text,
            "sample_rate": sample_rate,
        }

        speaker = _get_speaker()
        if speaker:
            tts_kwargs["speaker"] = speaker

        audio = model.apply_tts(**tts_kwargs)

        sd.play(audio, sample_rate)
        sd.wait()

    except Exception as error:
        print(f"[VOICE] Ошибка озвучки: {error}")


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

    if tts_available:
        return "ACTIVE"

    if tts_initialized and not tts_available:
        return "ERROR"

    return "WAIT"


def get_tts_error():
    return tts_error