from config import APP_NAME, APP_VERSION

import tkinter as tk

from ai.llm_client import ask_llm, get_model_name, is_lm_studio_online
from core.commands import handle_command
from core.logger import log
from voice.tts import speak
from voice.stt import listen_microphone


def run_gui():
    window = tk.Tk()
    window.title(f"{APP_NAME} {APP_VERSION}")
    window.geometry("800x650")
    window.configure(bg="#111111")

    voice_enabled = tk.BooleanVar(value=True)

    status_label = tk.Label(
        window,
        text="STATUS: READY | MODE: LOCAL",
        bg="#111111",
        fg="#FFA500",
        font=("Consolas", 10, "bold"),
        anchor="w"
    )
    status_label.pack(padx=12, pady=(8, 0), fill=tk.X)

    chat = tk.Text(
        window,
        bg="#111111",
        fg="#FFA500",
        font=("Consolas", 12),
        wrap=tk.WORD,
        state=tk.DISABLED
    )
    chat.pack(padx=12, pady=12, fill=tk.BOTH, expand=True)

    chat.tag_config("user", foreground="#00FFFF")
    chat.tag_config("bot", foreground="#FFA500")
    chat.tag_config("system", foreground="#777777")

    bottom_frame = tk.Frame(window, bg="#111111")
    bottom_frame.pack(padx=12, pady=(0, 8), fill=tk.X)

    buttons_frame = tk.Frame(window, bg="#111111")
    buttons_frame.pack(padx=12, pady=(0, 12), fill=tk.X)

    entry = tk.Entry(
        bottom_frame,
        bg="#222222",
        fg="#FFA500",
        insertbackground="#FFA500",
        font=("Consolas", 12)
    )
    entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

    def add_message(text: str, tag: str):
        chat.config(state=tk.NORMAL)
        chat.insert(tk.END, text + "\n", tag)
        chat.config(state=tk.DISABLED)
        chat.see(tk.END)

    def process_text(user_text: str):
        if not user_text:
            return

        add_message(f"Ты: {user_text}", "user")
        log(f"[USER] {user_text}")

        clean_text = user_text.lower().strip().lstrip("- ").strip()

        if clean_text in ["выход", "exit", "quit", "стоп", "пока"]:
            answer = "Завершение работы."
            add_message(f"F.E.D.O: {answer}", "bot")
            log(f"[F.E.D.O] {answer}")
            window.destroy()
            return

        command_answer = handle_command(user_text)

        if command_answer:
            add_message(f"F.E.D.O: {command_answer}", "bot")
            log(f"[F.E.D.O] {command_answer}")

            if voice_enabled.get():
                speak(command_answer[:600])

            status_label.config(text="STATUS: READY | MODE: LOCAL")
            return

        status_label.config(text="STATUS: THINKING | MODE: LOCAL")
        window.update()

        answer = ask_llm(user_text)

        add_message(f"F.E.D.O: {answer}", "bot")
        log(f"[F.E.D.O] {answer}")

        if voice_enabled.get():
            speak(answer[:600])

        status_label.config(text="STATUS: READY | MODE: LOCAL")

    def send():
        user_text = entry.get().strip()
        entry.delete(0, tk.END)
        process_text(user_text)

    def mic_input():
        mic_button.config(text="🎙 Слушаю...")
        status_label.config(text="STATUS: LISTENING | MODE: MICROPHONE")
        window.update()

        text = listen_microphone()

        mic_button.config(text="🎙 Слушать")

        if text.startswith("Ошибка"):
            add_message(f"SYSTEM: {text}", "system")
            log(f"[SYSTEM] {text}")
            status_label.config(text="STATUS: READY | MODE: LOCAL")
            return

        process_text(text)

    def run_quick_command(command: str):
        process_text(command)

    send_button = tk.Button(
        bottom_frame,
        text="Отправить",
        command=send,
        bg="#FFA500",
        fg="#111111",
        font=("Consolas", 11, "bold"),
        relief=tk.FLAT
    )
    send_button.pack(side=tk.RIGHT)

    mic_button = tk.Button(
        bottom_frame,
        text="🎙 Слушать",
        command=mic_input,
        bg="#222222",
        fg="#FFA500",
        activebackground="#333333",
        activeforeground="#FFA500",
        font=("Consolas", 10, "bold"),
        relief=tk.FLAT,
        padx=8
    )
    mic_button.pack(side=tk.RIGHT, padx=(0, 8))

    voice_button = tk.Checkbutton(
        bottom_frame,
        text="VOICE",
        variable=voice_enabled,
        onvalue=True,
        offvalue=False,
        bg="#111111",
        fg="#FFA500",
        selectcolor="#222222",
        activebackground="#111111",
        activeforeground="#FFA500",
        font=("Consolas", 10, "bold")
    )
    voice_button.pack(side=tk.RIGHT, padx=(0, 8))

    quick_buttons = [
        ("Браузер", "открой браузер"),
        ("YouTube", "открой ютуб"),
        ("Папка", "открой папку проекта"),
        ("Память", "память"),
        ("Очистить", "очистить"),
        ("Музыка", "включи музыку"),
        ("Лог", "покажи лог"),
    ]

    for title, command in quick_buttons:
        btn = tk.Button(
            buttons_frame,
            text=title,
            command=lambda cmd=command: run_quick_command(cmd),
            bg="#222222",
            fg="#FFA500",
            activebackground="#333333",
            activeforeground="#FFA500",
            font=("Consolas", 10),
            relief=tk.FLAT
        )
        btn.pack(side=tk.LEFT, padx=4)

    def boot_sequence():
        lm_status = "ONLINE" if is_lm_studio_online() else "OFFLINE"
        model_name = get_model_name()

        boot_lines = [
            "ОКБ F.E.D.O: запуск вычислительного ядра...",
            "Проверка канала оператора...",
            "Модуль команд: АКТИВЕН",
            "Модуль памяти: АКТИВЕН",
            "Модуль голоса: АКТИВЕН",
            f"LM Studio: {lm_status}",
            f"Локальная модель: {model_name}",
            "Состояние комплекса: ГОТОВ",
            "Добро пожаловать, товарищ."
        ]

        for line in boot_lines:
            add_message(line, "system")
            log(f"[SYSTEM] {line}")
            window.update()
            window.after(250)

    boot_sequence()

    entry.bind("<Return>", lambda event: send())
    entry.focus()

    window.mainloop()