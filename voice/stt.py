from config import MICROPHONE_ENABLED

try:
    import speech_recognition as sr
except Exception:
    sr = None


def listen_microphone():
    if not MICROPHONE_ENABLED:
        return "Ошибка: микрофон отключён в config.py."

    if sr is None:
        return "Ошибка: модуль SpeechRecognition не установлен."

    recognizer = sr.Recognizer()

    try:
        with sr.Microphone() as source:
            print("Слушаю...")
            recognizer.adjust_for_ambient_noise(source, duration=1)
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)

        text = recognizer.recognize_google(audio, language="ru-RU")
        return text

    except sr.WaitTimeoutError:
        return "Ошибка: команда не услышана. Микрофон молчит."
    except sr.UnknownValueError:
        return "Ошибка: не удалось распознать речь."
    except Exception as e:
        return f"Ошибка микрофона: {e}"