"""
F.E.D.O Core — Console Assistant (v1.4)

Консольный режим. Вся логика идёт через AI Router (core/ai_router.py) —
тот же конвейер, что и в GUI: команды → system → LLM.
"""
from core.ai_router import route
from interface.console_ui import show_banner, print_assistant, input_user


def run_assistant():
    show_banner()
    print_assistant("Система запущена. Напиши 'помощь' для списка команд.")

    while True:
        try:
            user_text = input_user()
        except (EOFError, KeyboardInterrupt):
            print()
            print_assistant("Завершение работы.")
            break

        clean_text = user_text.lower().strip().lstrip("- ").strip()

        if clean_text in ["выход", "exit", "quit", "стоп", "пока"]:
            print_assistant("Завершение работы.")
            break

        if not clean_text:
            continue

        try:
            answer = route(user_text)
        except Exception as e:
            answer = f"Ошибка обработки запроса: {e}"

        if answer:
            print_assistant(answer)
