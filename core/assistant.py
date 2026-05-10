from ai.llm_client import ask_llm
from core.commands import handle_command
from interface.console_ui import show_banner, print_assistant, input_user


def run_assistant():
    show_banner()
    print_assistant("Система запущена. Напиши 'помощь' для списка команд.")

    while True:
        user_text = input_user()

        clean_text = user_text.lower().strip().lstrip("- ").strip()

        if clean_text in ["выход", "exit", "quit", "стоп", "пока"]:
            print_assistant("Завершение работы.")
            break

        command_answer = handle_command(user_text)

        if command_answer:
            print_assistant(command_answer)
            continue

        answer = ask_llm(user_text)
        print_assistant(answer)