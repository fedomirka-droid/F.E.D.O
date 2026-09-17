"""
F.E.D.O Core — Определение сложности запроса (v1.4)

Простой механизм, выбранный для v1.4:
сложность определяется по количеству слов.

    1–5 слов   → simple
    6–15 слов  → normal
    16+ слов   → complex

Пороги настраиваются в data/settings.json:
    complexity_simple_max  (по умолчанию 5)
    complexity_normal_max  (по умолчанию 15)

Более интеллектуальное определение — в следующих версиях (v1.5+).
"""
from core.settings import load_settings

LEVELS = ("simple", "normal", "complex")

LEVEL_LABELS = {
    "simple": "простой",
    "normal": "обычный",
    "complex": "сложный",
}


def get_word_count(text: str) -> int:
    """Количество слов в запросе."""
    return len([w for w in str(text or "").split() if w.strip()])


def get_thresholds() -> tuple:
    """Пороги сложности (simple_max, normal_max) из настроек."""
    settings = load_settings()

    try:
        simple_max = int(settings.get("complexity_simple_max", 5))
    except (TypeError, ValueError):
        simple_max = 5

    try:
        normal_max = int(settings.get("complexity_normal_max", 15))
    except (TypeError, ValueError):
        normal_max = 15

    if simple_max < 1 or normal_max <= simple_max:
        simple_max, normal_max = 5, 15

    return simple_max, normal_max


def classify(text: str) -> dict:
    """
    Классифицировать запрос по сложности.

    :return: {
        "level": "simple" | "normal" | "complex",
        "words": int,
        "thresholds": (simple_max, normal_max),
    }
    """
    words = get_word_count(text)
    simple_max, normal_max = get_thresholds()

    if words <= simple_max:
        level = "simple"
    elif words <= normal_max:
        level = "normal"
    else:
        level = "complex"

    return {
        "level": level,
        "words": words,
        "thresholds": (simple_max, normal_max),
    }


def describe(text: str) -> str:
    """Короткое описание для логов и Developer Mode."""
    info = classify(text)
    return f"{LEVEL_LABELS[info['level']]} ({info['words']} слов)"
