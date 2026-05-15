import sys
import os
import threading

from config import VOICE_ENABLED

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

tts_available = False
tts_initialized = False
tts_error = None


def init_tts():
    global model, tts_available, tts_initialized, tts_error

    if tts_initialized:
        return tts_available

    tts_initialized = True

    if not VOICE_ENABLED:
        tts_available = False
        tts_error = "Голос отключён в config.py."
        print(f"[VOICE] {tts_error}")
        return False

    if torch is None or sd is None:
        tts_available = False
        tts_error = "Модули torch или sounddevice недоступны."
        print(f"[VOICE] {tts_error}")
        return False

    try:
        print("[VOICE] Загрузка Silero TTS...")

        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language="ru",
            speaker="v4_ru",
            trust_repo=True
        )

        tts_available = True
        tts_error = None
        print("[VOICE] Silero TTS активен.")
        return True

    except Exception as error:
        model = None
        tts_available = False
        tts_error = f"Ошибка TTS: {error}"
        print(f"[VOICE] {tts_error}")
        print("[VOICE] Голосовой модуль отключён. F.E.D.O продолжит работу без озвучки.")
        return False


def _speak_blocking(text: str):
    if not init_tts():
        return

    try:
        audio = model.apply_tts(
            text=text,
            speaker="aidar",
            sample_rate=sample_rate
        )

        sd.play(audio, sample_rate)
        sd.wait()

    except Exception as error:
        print(f"[VOICE] Ошибка озвучки: {error}")


def speak(text: str):
    if not VOICE_ENABLED:
        return

    if not text:
        return

    threading.Thread(
        target=_speak_blocking,
        args=(text,),
        daemon=True
    ).start()


def get_tts_status():
    if not VOICE_ENABLED:
        return "OFF"

    if tts_available:
        return "ACTIVE"

    if tts_initialized and not tts_available:
        return "ERROR"

    return "WAIT"