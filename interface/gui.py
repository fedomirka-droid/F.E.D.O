from config import APP_NAME, APP_VERSION

import tkinter as tk
from tkinter import ttk
import os
import subprocess
import sys

from ai.llm_client import ask_llm, get_model_name, is_lm_studio_online, clear_chat_history
from core.commands import handle_command
from core.logger import log
from voice.tts import speak
from voice.stt import listen_microphone
from core.settings import load_settings, save_settings


def run_gui():
    window = tk.Tk()
    window.title(f"{APP_NAME} {APP_VERSION}")
    window.geometry("1300x750")
    window.configure(bg="#111111")
    settings = load_settings()
    style = ttk.Style()
    style.theme_use("clam")

    style.configure(
        "Fedo.TNotebook",
        background="#111111",
        borderwidth=0,
        relief="flat",
        tabmargins=[0, 0, 0, 0]
    )

    style.configure(
        "Fedo.TNotebook.Tab",
        background="#222222",
        foreground="#FFA500",
        borderwidth=0,
        padding=(10, 4),
        font=("Consolas", 10)
    )

    style.map(
        "Fedo.TNotebook.Tab",
        background=[("selected", "#111111")],
        foreground=[("selected", "#FFA500")]
    )

    voice_enabled = tk.BooleanVar(value=settings.get("voice_enabled", True))
    status_bar_text = tk.StringVar(value="LM: CHECKING | MODEL: UNKNOWN | VOICE: ON | MODE: NORMAL")

    status_label = tk.Label(
        window,
        text="STATUS: READY | MODE: LOCAL",
        bg="#111111",
        fg="#FFA500",
        font=("Consolas", 10, "bold"),
        anchor="w"
    )
    notebook = ttk.Notebook(window, style="Fedo.TNotebook")
    notebook.pack(padx=12, pady=12, fill=tk.BOTH, expand=True)

    chat_tab = tk.Frame(notebook, bg="#111111", bd=0, highlightthickness=0)
    settings_tab = tk.Frame(notebook, bg="#111111", bd=0, highlightthickness=0)
    logs_tab = tk.Frame(notebook, bg="#111111", bd=0, highlightthickness=0)
    terminal_tab = tk.Frame(notebook, bg="#111111", bd=0, highlightthickness=0)
    about_tab = tk.Frame(notebook, bg="#111111", bd=0, highlightthickness=0)

    notebook.add(chat_tab, text="Чат")
    notebook.add(settings_tab, text="Настройки")
    notebook.add(logs_tab, text="Логи")
    notebook.add(terminal_tab, text="Терминал")
    notebook.add(about_tab, text="О системе")

    chat = tk.Text(
        chat_tab,
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

    bottom_frame = tk.Frame(chat_tab, bg="#111111")
    bottom_frame.pack(padx=12, pady=(0, 8), fill=tk.X)

    buttons_frame = tk.Frame(chat_tab, bg="#111111")
    buttons_frame.pack(padx=12, pady=(0, 12), fill=tk.X)

    entry = tk.Entry(
        bottom_frame,
        bg="#222222",
        fg="#FFA500",
        insertbackground="#FFA500",
        font=("Consolas", 12)
    )
    entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

    # =========================
    # F.E.D.O v1.1 Comfort Controls
    # ПКМ меню + Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A
    # =========================

    def copy_selected():
        try:
            focused = window.focus_get()

            if focused == entry:
                selected_text = entry.selection_get()
            else:
                selected_text = chat.selection_get()

            window.clipboard_clear()
            window.clipboard_append(selected_text)
            window.update()

        except tk.TclError:
            pass

        return "break"

    def paste_to_entry():
        try:
            text = window.clipboard_get()
            entry.focus_set()
            entry.insert(tk.INSERT, text)
        except tk.TclError:
            pass

        return "break"

    def cut_from_entry():
        try:
            selected_text = entry.selection_get()

            window.clipboard_clear()
            window.clipboard_append(selected_text)
            window.update()

            entry.delete(tk.SEL_FIRST, tk.SEL_LAST)

        except tk.TclError:
            pass

        return "break"

    def select_all_entry():
        try:
            entry.focus_set()
            entry.select_range(0, tk.END)
            entry.icursor(tk.END)
        except tk.TclError:
            pass

        return "break"

    def select_all_chat():
        try:
            chat.focus_set()
            chat.tag_add(tk.SEL, "1.0", tk.END)
            chat.mark_set(tk.INSERT, "1.0")
            chat.see(tk.INSERT)
        except tk.TclError:
            pass

        return "break"

    def select_all_current():
        focused = window.focus_get()

        if focused == entry:
            return select_all_entry()

        return select_all_chat()

    def clear_entry():
        entry.delete(0, tk.END)

    def show_entry_menu(event):
        entry.focus_set()

        menu = tk.Menu(window, tearoff=0, bg="#222222", fg="#FFA500")
        menu.add_command(label="Вырезать", command=cut_from_entry)
        menu.add_command(label="Копировать", command=copy_selected)
        menu.add_command(label="Вставить", command=paste_to_entry)
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=select_all_entry)
        menu.add_command(label="Очистить ввод", command=clear_entry)

        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def show_chat_menu(event):
        chat.focus_set()

        menu = tk.Menu(window, tearoff=0, bg="#222222", fg="#FFA500")
        menu.add_command(label="Копировать", command=copy_selected)
        menu.add_command(label="Выделить всё", command=select_all_chat)

        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    entry.bind("<Button-3>", show_entry_menu)
    chat.bind("<Button-3>", show_chat_menu)

    window.bind_all("<Control-c>", lambda event: copy_selected())
    window.bind_all("<Control-C>", lambda event: copy_selected())

    window.bind_all("<Control-v>", lambda event: paste_to_entry())
    window.bind_all("<Control-V>", lambda event: paste_to_entry())

    window.bind_all("<Control-x>", lambda event: cut_from_entry())
    window.bind_all("<Control-X>", lambda event: cut_from_entry())

    window.bind_all("<Control-a>", lambda event: select_all_current())
    window.bind_all("<Control-A>", lambda event: select_all_current())

    # =========================
    # F.E.D.O v1.1 Settings Tab
    # =========================

    settings_title = tk.Label(
        settings_tab,
        text="НАСТРОЙКИ F.E.D.O",
        bg="#111111",
        fg="#FFA500",
        font=("Consolas", 16, "bold")
    )
    settings_title.pack(anchor="w", padx=16, pady=(16, 12))

    voice_setting = tk.Checkbutton(
        settings_tab,
        text="Голосовой ответ VOICE",
        variable=voice_enabled,
        onvalue=True,
        offvalue=False,
        bg="#111111",
        fg="#FFA500",
        selectcolor="#222222",
        activebackground="#111111",
        activeforeground="#FFA500",
        font=("Consolas", 12, "bold")
    )
    voice_setting.pack(anchor="w", padx=16, pady=8)


    lm_label = tk.Label(
        settings_tab,
        text="LM Studio URL:",
        bg="#111111",
        fg="#777777",
        font=("Consolas", 11)
    )
    lm_label.pack(anchor="w", padx=16, pady=(16, 4))

    lm_url_var = tk.StringVar(value=settings.get("lm_studio_url", "http://127.0.0.1:1234/v1/chat/completions"))

    lm_url_entry = tk.Entry(
        settings_tab,
        textvariable=lm_url_var,
        bg="#222222",
        fg="#FFA500",
        insertbackground="#FFA500",
        font=("Consolas", 11),
        width=70
    )
    lm_url_entry.pack(anchor="w", padx=16, pady=(0, 12), fill=tk.X)

    style_label = tk.Label(
        settings_tab,
        text="Стиль обращения:",
        bg="#111111",
        fg="#777777",
        font=("Consolas", 11)
    )
    style_label.pack(anchor="w", padx=16, pady=(8, 4))

    style_mode_var = tk.StringVar(value=settings.get("style_mode", "soviet"))

    style_frame = tk.Frame(settings_tab, bg="#111111")
    style_frame.pack(anchor="w", padx=16, pady=(0, 12))

    for text, value in [
        ("Советский / товарищ", "soviet"),
        ("Современный", "modern"),
        ("Американский / сэр", "american"),
    ]:
        tk.Radiobutton(
            style_frame,
            text=text,
            variable=style_mode_var,
            value=value,
            bg="#111111",
            fg="#FFA500",
            selectcolor="#222222",
            activebackground="#111111",
            activeforeground="#FFA500",
            font=("Consolas", 10)
        ).pack(anchor="w")

    answer_label = tk.Label(
        settings_tab,
        text="Режим ответа:",
        bg="#111111",
        fg="#777777",
        font=("Consolas", 11)
    )
    answer_label.pack(anchor="w", padx=16, pady=(8, 4))

    answer_mode_var = tk.StringVar(value=settings.get("answer_mode", "normal"))

    answer_frame = tk.Frame(settings_tab, bg="#111111")
    answer_frame.pack(anchor="w", padx=16, pady=(0, 12))

    for text, value in [
        ("Кратко", "short"),
        ("Нормально", "normal"),
        ("Подробно", "detailed"),
    ]:
        tk.Radiobutton(
            answer_frame,
            text=text,
            variable=answer_mode_var,
            value=value,
            bg="#111111",
            fg="#FFA500",
            selectcolor="#222222",
            activebackground="#111111",
            activeforeground="#FFA500",
            font=("Consolas", 10)
        ).pack(anchor="w")

    settings_status = tk.Label(
        settings_tab,
        text="",
        bg="#111111",
        fg="#00FFFF",
        font=("Consolas", 10)
    )
    settings_status.pack(anchor="w", padx=16, pady=(8, 4))

    def save_current_settings():
        new_settings = {
            "voice_enabled": voice_enabled.get(),
            "lm_studio_url": lm_url_var.get().strip(),
            "style_mode": style_mode_var.get(),
            "answer_mode": answer_mode_var.get()
        }

        save_settings(new_settings)
        clear_chat_history()
        update_status_bar()

        settings_status.config(text="Настройки сохранены. История диалога очищена.")
        status_label.config(text="STATUS: SETTINGS SAVED | MODE: LOCAL")

        log(f"[SYSTEM] Настройки сохранены: {new_settings}")

    save_settings_button = tk.Button(
        settings_tab,
        text="Сохранить настройки",
        command=save_current_settings,
        bg="#FFA500",
        fg="#111111",
        activebackground="#FFB52E",
        activeforeground="#111111",
        font=("Consolas", 11, "bold"),
        relief=tk.FLAT,
        padx=10,
        pady=6
    )
    save_settings_button.pack(anchor="w", padx=16, pady=(8, 16))
    system_check_title = tk.Label(
        settings_tab,
        text="ДИАГНОСТИКА СИСТЕМЫ",
        bg="#111111",
        fg="#FFA500",
        font=("Consolas", 13, "bold")
    )
    system_check_title.pack(anchor="w", padx=16, pady=(10, 6))

    system_check_output = tk.Text(
        settings_tab,
        bg="#050505",
        fg="#00FFFF",
        insertbackground="#FFA500",
        font=("Consolas", 10),
        wrap=tk.WORD,
        height=12,
        state=tk.DISABLED
    )
    system_check_output.pack(anchor="w", padx=16, pady=(0, 10), fill=tk.X)

    def system_check_print(text: str):
        system_check_output.config(state=tk.NORMAL)
        system_check_output.insert(tk.END, text + "\n")
        system_check_output.config(state=tk.DISABLED)
        system_check_output.see(tk.END)

    def run_system_check():
        system_check_output.config(state=tk.NORMAL)
        system_check_output.delete("1.0", tk.END)
        system_check_output.config(state=tk.DISABLED)

        system_check_print("F.E.D.O SYSTEM CHECK")
        system_check_print("=" * 40)

        # Python
        system_check_print(f"[PYTHON] {sys.version.split()[0]}")
        system_check_print(f"[EXECUTABLE] {sys.executable}")

        # Virtual environment
        if ".venv" in sys.executable.lower():
            system_check_print("[VENV] OK: используется .venv")
        else:
            system_check_print("[VENV] WARNING: .venv не обнаружен в пути Python")

        # Required files
        required_files = [
            "main.py",
            "config.py",
            "requirements.txt",
            os.path.join("data", "settings.json"),
            os.path.join("data", "memory.json"),
            os.path.join("logs", "session.log"),
            os.path.join("logs", "fedo.log"),
        ]

        system_check_print("")
        system_check_print("[FILES]")

        for file_path in required_files:
            if os.path.exists(file_path):
                system_check_print(f"OK: {file_path}")
            else:
                system_check_print(f"MISSING: {file_path}")

        # Required folders
        required_folders = [
            "ai",
            "core",
            "interface",
            "voice",
            "data",
            "logs"
        ]

        system_check_print("")
        system_check_print("[FOLDERS]")

        for folder_path in required_folders:
            if os.path.isdir(folder_path):
                system_check_print(f"OK: {folder_path}")
            else:
                system_check_print(f"MISSING: {folder_path}")

        # LM Studio
        system_check_print("")
        system_check_print("[LM STUDIO]")

        lm_status = "ONLINE" if is_lm_studio_online() else "OFFLINE"
        model_name = get_model_name()

        system_check_print(f"STATUS: {lm_status}")
        system_check_print(f"MODEL: {model_name}")

        # Settings
        system_check_print("")
        system_check_print("[SETTINGS]")

        current_settings = load_settings()

        system_check_print(f"VOICE: {current_settings.get('voice_enabled', True)}")
        system_check_print(f"LM URL: {current_settings.get('lm_studio_url', 'NOT SET')}")
        system_check_print(f"STYLE: {current_settings.get('style_mode', 'soviet')}")
        system_check_print(f"ANSWER MODE: {current_settings.get('answer_mode', 'normal')}")

        # Voice module
        system_check_print("")
        system_check_print("[VOICE]")

        if os.path.isdir("voice"):
            system_check_print("VOICE FOLDER: OK")
        else:
            system_check_print("VOICE FOLDER: MISSING")

        # Final
        system_check_print("")
        system_check_print("=" * 40)

        if lm_status == "ONLINE":
            system_check_print("RESULT: КОНТУР СТАБИЛЕН. СИСТЕМА ГОТОВА.")
        else:
            system_check_print("RESULT: LM STUDIO OFFLINE. ОСНОВНОЙ ИИ-КОНТУР НЕДОСТУПЕН.")

        log("[SYSTEM] Выполнена диагностика системы через интерфейс.")

    system_check_button = tk.Button(
        settings_tab,
        text="Проверить систему",
        command=run_system_check,
        bg="#222222",
        fg="#00FFFF",
        activebackground="#333333",
        activeforeground="#00FFFF",
        font=("Consolas", 11, "bold"),
        relief=tk.FLAT,
        padx=10,
        pady=6
    )
    system_check_button.pack(anchor="w", padx=16, pady=(0, 12))

    # =========================
    # F.E.D.O v1.1 Logs Tab
    # =========================

    LOG_FILE = os.path.join("logs", "fedo.log")

    logs_title = tk.Label(
        logs_tab,
        text="ЖУРНАЛ СИСТЕМЫ F.E.D.O",
        bg="#111111",
        fg="#FFA500",
        font=("Consolas", 16, "bold")
    )
    logs_title.pack(anchor="w", padx=16, pady=(16, 8))

    logs_buttons_frame = tk.Frame(logs_tab, bg="#111111")
    logs_buttons_frame.pack(anchor="w", padx=16, pady=(0, 8), fill=tk.X)

    logs_text_frame = tk.Frame(logs_tab, bg="#111111")
    logs_text_frame.pack(padx=16, pady=(0, 16), fill=tk.BOTH, expand=True)

    logs_scrollbar = tk.Scrollbar(logs_text_frame)
    logs_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    logs_text = tk.Text(
        logs_text_frame,
        bg="#050505",
        fg="#FFA500",
        insertbackground="#FFA500",
        font=("Consolas", 10),
        wrap=tk.WORD,
        state=tk.DISABLED,
        yscrollcommand=logs_scrollbar.set
    )
    logs_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    logs_scrollbar.config(command=logs_text.yview)

    def refresh_logs():
        logs_text.config(state=tk.NORMAL)
        logs_text.delete("1.0", tk.END)

        try:
            if not os.path.exists("logs"):
                os.makedirs("logs")

            log_files = [
                os.path.join("logs", "fedo.log"),
                os.path.join("logs", "session.log")
            ]

            has_content = False

            for file_path in log_files:
                file_name = os.path.basename(file_path)

                logs_text.insert(tk.END, f"===== {file_name} =====\n")

                if not os.path.exists(file_path):
                    logs_text.insert(tk.END, "[SYSTEM] Файл журнала не найден.\n\n")
                    continue

                with open(file_path, "r", encoding="utf-8", errors="replace") as file:
                    content = file.read()

                if content.strip():
                    logs_text.insert(tk.END, content + "\n\n")
                    has_content = True
                else:
                    logs_text.insert(tk.END, "[SYSTEM] Журнал пуст.\n\n")

            if not has_content:
                logs_text.insert(tk.END, "[SYSTEM] Активные записи журнала не обнаружены.")

        except Exception as e:
            logs_text.insert(tk.END, f"[ERROR] Не удалось прочитать журналы: {e}")

        logs_text.config(state=tk.DISABLED)
        logs_text.see(tk.END)

    def clear_logs():
        try:
            if not os.path.exists("logs"):
                os.makedirs("logs")

            log_files = [
                os.path.join("logs", "fedo.log"),
                os.path.join("logs", "session.log")
            ]

            for file_path in log_files:
                with open(file_path, "w", encoding="utf-8") as file:
                    file.write("[SYSTEM] Журнал очищен.\n")

            refresh_logs()
            log("[SYSTEM] Журналы очищены через интерфейс.")

        except Exception as e:
            logs_text.config(state=tk.NORMAL)
            logs_text.insert(tk.END, f"\n[ERROR] Не удалось очистить журналы: {e}")
            logs_text.config(state=tk.DISABLED)

    def open_logs_folder():
        try:
            if not os.path.exists("logs"):
                os.makedirs("logs")

            subprocess.Popen(f'explorer "{os.path.abspath("logs")}"')

        except Exception as e:
            logs_text.config(state=tk.NORMAL)
            logs_text.insert(tk.END, f"\n[ERROR] Не удалось открыть папку logs: {e}")
            logs_text.config(state=tk.DISABLED)

    refresh_logs_button = tk.Button(
        logs_buttons_frame,
        text="Обновить логи",
        command=refresh_logs,
        bg="#222222",
        fg="#00FFFF",
        activebackground="#333333",
        activeforeground="#00FFFF",
        font=("Consolas", 10),
        relief=tk.FLAT,
        padx=8,
        pady=4
    )
    refresh_logs_button.pack(side=tk.LEFT, padx=(0, 8))

    clear_logs_button = tk.Button(
        logs_buttons_frame,
        text="Очистить логи",
        command=clear_logs,
        bg="#222222",
        fg="#FFA500",
        activebackground="#333333",
        activeforeground="#FFA500",
        font=("Consolas", 10),
        relief=tk.FLAT,
        padx=8,
        pady=4
    )
    clear_logs_button.pack(side=tk.LEFT, padx=(0, 8))

    open_logs_button = tk.Button(
        logs_buttons_frame,
        text="Открыть папку logs",
        command=open_logs_folder,
        bg="#222222",
        fg="#FFA500",
        activebackground="#333333",
        activeforeground="#FFA500",
        font=("Consolas", 10),
        relief=tk.FLAT,
        padx=8,
        pady=4
    )
    open_logs_button.pack(side=tk.LEFT, padx=(0, 8))

    refresh_logs()

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
        if command == "покажи лог":
            notebook.select(logs_tab)
            refresh_logs()
            return

        process_text(command)

    def on_tab_changed(event):
        selected_tab = notebook.select()
        tab_text = notebook.tab(selected_tab, "text")

        if tab_text == "Логи":
            refresh_logs()

    notebook.bind("<<NotebookTabChanged>>", on_tab_changed)

    # =========================
    # F.E.D.O v1.1 Terminal Tab
    # =========================

    terminal_title = tk.Label(
        terminal_tab,
        text="ВСТРОЕННЫЙ ТЕРМИНАЛ F.E.D.O",
        bg="#111111",
        fg="#FFA500",
        font=("Consolas", 16, "bold")
    )
    terminal_title.pack(anchor="w", padx=16, pady=(16, 8))

    terminal_hint = tk.Label(
        terminal_tab,
        text="Команды выполняются в рабочей папке проекта. Осторожно с командами удаления файлов.",
        bg="#111111",
        fg="#777777",
        font=("Consolas", 10)
    )
    terminal_hint.pack(anchor="w", padx=16, pady=(0, 8))

    terminal_output_frame = tk.Frame(terminal_tab, bg="#111111")
    terminal_output_frame.pack(padx=16, pady=(0, 8), fill=tk.BOTH, expand=True)

    terminal_scrollbar = tk.Scrollbar(terminal_output_frame)
    terminal_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    terminal_output = tk.Text(
        terminal_output_frame,
        bg="#050505",
        fg="#00FFFF",
        insertbackground="#FFA500",
        font=("Consolas", 10),
        wrap=tk.WORD,
        state=tk.DISABLED,
        yscrollcommand=terminal_scrollbar.set
    )
    terminal_output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    terminal_scrollbar.config(command=terminal_output.yview)

    terminal_input_frame = tk.Frame(terminal_tab, bg="#111111")
    terminal_input_frame.pack(padx=16, pady=(0, 16), fill=tk.X)

    terminal_entry = tk.Entry(
        terminal_input_frame,
        bg="#222222",
        fg="#FFA500",
        insertbackground="#FFA500",
        font=("Consolas", 11)
    )
    terminal_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

    def terminal_print(text: str):
        terminal_output.config(state=tk.NORMAL)
        terminal_output.insert(tk.END, text + "\n")
        terminal_output.config(state=tk.DISABLED)
        terminal_output.see(tk.END)

    def run_terminal_command():
        command = terminal_entry.get().strip()
        aliases = {
            "ls": "dir",
            "ll": "dir",
            "pwd": "cd",
            "clear": "cls",
            "py": "python",
            "pip": ".\\.venv\\Scripts\\pip.exe",
            "python": ".\\.venv\\Scripts\\python.exe"
        }

        original_command = command
        command_parts = command.split()

        if command_parts:
            first_word = command_parts[0].lower()

            if first_word in aliases:
                command_parts[0] = aliases[first_word]
                command = " ".join(command_parts)

        if not command:
            return

        terminal_entry.delete(0, tk.END)

        if original_command != command:
            terminal_print(f"> {original_command}")
            terminal_print(f"[ALIAS] {original_command} → {command}")
            log(f"[TERMINAL ALIAS] {original_command} -> {command}")
        else:
            terminal_print(f"> {command}")

        log(f"[TERMINAL] {command}")

        dangerous_words = [
            "del ",
            "erase ",
            "rmdir ",
            "rd ",
            "remove-item",
            "rm ",
            "format ",
            "shutdown",
            "restart-computer"
        ]

        lower_command = command.lower()

        for word in dangerous_words:
            if word in lower_command:
                terminal_print("[BLOCKED] Потенциально опасная команда заблокирована.")
                log(f"[TERMINAL BLOCKED] {command}")
                return

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=os.getcwd(),
                timeout=30
            )

            if result.stdout:
                terminal_print(result.stdout.strip())

            if result.stderr:
                terminal_print("[ERROR]")
                terminal_print(result.stderr.strip())

            if not result.stdout and not result.stderr:
                terminal_print("[OK] Команда выполнена без вывода.")

            log(f"[TERMINAL RESULT] code={result.returncode}")

        except subprocess.TimeoutExpired:
            terminal_print("[ERROR] Команда выполнялась слишком долго и была остановлена.")
            log("[TERMINAL ERROR] Timeout")

        except Exception as e:
            terminal_print(f"[ERROR] Не удалось выполнить команду: {e}")
            log(f"[TERMINAL ERROR] {e}")

    def clear_terminal():
        terminal_output.config(state=tk.NORMAL)
        terminal_output.delete("1.0", tk.END)
        terminal_output.config(state=tk.DISABLED)

    terminal_run_button = tk.Button(
        terminal_input_frame,
        text="Выполнить",
        command=run_terminal_command,
        bg="#FFA500",
        fg="#111111",
        activebackground="#FFB52E",
        activeforeground="#111111",
        font=("Consolas", 10, "bold"),
        relief=tk.FLAT,
        padx=10
    )
    terminal_run_button.pack(side=tk.RIGHT)

    terminal_clear_button = tk.Button(
        terminal_input_frame,
        text="Очистить",
        command=clear_terminal,
        bg="#222222",
        fg="#00FFFF",
        activebackground="#333333",
        activeforeground="#00FFFF",
        font=("Consolas", 10),
        relief=tk.FLAT,
        padx=10
    )
    terminal_clear_button.pack(side=tk.RIGHT, padx=(0, 8))

    terminal_entry.bind("<Return>", lambda event: run_terminal_command())

    terminal_print("F.E.D.O Terminal ready.")
    terminal_print("Рабочая директория: " + os.getcwd())

    # =========================
    # F.E.D.O v1.1 About Tab
    # =========================

    about_title = tk.Label(
        about_tab,
        text=f"{APP_NAME} {APP_VERSION}",
        bg="#111111",
        fg="#FFA500",
        font=("Consolas", 22, "bold")
    )
    about_title.pack(anchor="w", padx=24, pady=(24, 4))

    about_subtitle = tk.Label(
        about_tab,
        text="Functional Event Detection Operator",
        bg="#111111",
        fg="#00FFFF",
        font=("Consolas", 12, "bold")
    )
    about_subtitle.pack(anchor="w", padx=24, pady=(0, 18))

    about_text_frame = tk.Frame(about_tab, bg="#111111")
    about_text_frame.pack(padx=24, pady=(0, 12), fill=tk.BOTH, expand=True)

    about_scrollbar = tk.Scrollbar(about_text_frame)
    about_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    about_text = tk.Text(
        about_text_frame,
        bg="#050505",
        fg="#FFA500",
        insertbackground="#FFA500",
        font=("Consolas", 11),
        wrap=tk.WORD,
        state=tk.NORMAL,
        yscrollcommand=about_scrollbar.set
    )
    about_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    about_scrollbar.config(command=about_text.yview)

    about_content = f"""
    ОПИСАНИЕ СИСТЕМЫ
    ================

    F.E.D.O — локальный ИИ-ассистент на Python.
    Полное название: Functional Event Detection Operator.

    Версия: {APP_VERSION}
    Автор проекта: fedomirka

    СТИЛЬ СИСТЕМЫ
    =============

    F.E.D.O выполнен в стилистике инженерного вычислительного комплекса:
    - советский научно-технический терминал;
    - закрытый НИИ;
    - диспетчерский пункт;
    - локальный операторский модуль;
    - ретрофутуристическая система анализа и команд.

    ССЫЛКИ
    ======

    GitHub:
    https://github.com/fedomirka-droid/F.E.D.O

    Telegram:
    https://t.me/fedo_project

    АКТИВНЫЕ МОДУЛИ V1.1
    ====================

    [OK] AI-контур через LM Studio
    [OK] Определение локальной модели
    [OK] Системный промпт F.E.D.O
    [OK] Память через data/memory.json
    [OK] Настройки через data/settings.json
    [OK] Голосовой модуль VOICE
    [OK] Логи fedo.log и session.log
    [OK] Встроенный терминал
    [OK] Диагностика системы
    [OK] Копировать / вставить / выделить всё
    [OK] Быстрые команды

    СОСТОЯНИЕ
    =========

    Контур стабилен.
    Система готова к работе.
    """.strip()

    about_text.insert(tk.END, about_content)
    about_text.config(state=tk.DISABLED)

    def open_github():
        try:
            subprocess.Popen('start https://github.com/fedomirka-droid/F.E.D.O', shell=True)
            log("[SYSTEM] Открыта ссылка GitHub.")
        except Exception as e:
            log(f"[ERROR] Не удалось открыть GitHub: {e}")

    def open_telegram():
        try:
            subprocess.Popen('start https://t.me/fedo_project', shell=True)
            log("[SYSTEM] Открыта ссылка Telegram.")
        except Exception as e:
            log(f"[ERROR] Не удалось открыть Telegram: {e}")

    about_buttons_frame = tk.Frame(about_tab, bg="#111111")
    about_buttons_frame.pack(anchor="w", padx=24, pady=(0, 24))

    github_button = tk.Button(
        about_buttons_frame,
        text="Открыть GitHub",
        command=open_github,
        bg="#222222",
        fg="#00FFFF",
        activebackground="#333333",
        activeforeground="#00FFFF",
        font=("Consolas", 10, "bold"),
        relief=tk.FLAT,
        padx=10,
        pady=6
    )
    github_button.pack(side=tk.LEFT, padx=(0, 8))

    telegram_button = tk.Button(
        about_buttons_frame,
        text="Открыть Telegram",
        command=open_telegram,
        bg="#222222",
        fg="#FFA500",
        activebackground="#333333",
        activeforeground="#FFA500",
        font=("Consolas", 10, "bold"),
        relief=tk.FLAT,
        padx=10,
        pady=6
    )
    telegram_button.pack(side=tk.LEFT, padx=(0, 8))

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






    comfort_buttons = [
        ("Копировать", copy_selected),
        ("Вставить", paste_to_entry),
        ("Вырезать", cut_from_entry),
        ("Выделить всё", select_all_current),
        ("Очистить ввод", clear_entry),
    ]

    for title, action in comfort_buttons:
        btn = tk.Button(
            buttons_frame,
            text=title,
            command=action,
            bg="#1A1A1A",
            fg="#00FFFF",
            activebackground="#333333",
            activeforeground="#00FFFF",
            font=("Consolas", 10),
            relief=tk.FLAT
        )
        btn.pack(side=tk.LEFT, padx=4)

    quick_buttons = [
        ("Браузер", "открой браузер"),
        ("YouTube", "открой ютуб"),
        ("Папка", "открой папку проекта"),
        ("Память", "память"),
        ("Очистить память", "очистить"),
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

    status_bar = tk.Label(
        window,
        textvariable=status_bar_text,
        bg="#050505",
        fg="#00FFFF",
        font=("Consolas", 9),
        anchor="w",
        padx=10,
        pady=4
    )
    status_bar.pack(side=tk.BOTTOM, fill=tk.X)


    def update_status_bar():
        lm_status = "ONLINE" if is_lm_studio_online() else "OFFLINE"
        model_name = get_model_name()
        voice_state = "ON" if voice_enabled.get() else "OFF"
        answer_mode = load_settings().get("answer_mode", "normal").upper()

        status_bar_text.set(
            f"LM: {lm_status} | MODEL: {model_name} | VOICE: {voice_state} | MODE: {answer_mode}"
        )

    voice_button = tk.Checkbutton(
        bottom_frame,
        text="VOICE",
        variable=voice_enabled,
        command=update_status_bar,
        onvalue=True,
        offvalue=False,
        bg="#111111",
        fg="#FFA500",
        selectcolor="#222222",
        activebackground="#111111",
        activeforeground="#FFA500",
        font=("Consolas", 10, "bold")
    )
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
    update_status_bar()

    entry.bind("<Return>", lambda event: send())
    entry.focus()

    window.mainloop()