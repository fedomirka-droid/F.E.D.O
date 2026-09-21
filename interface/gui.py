import os
import threading
import subprocess
import psutil
try:
    import GPUtil
except ImportError:
    GPUtil = None
import customtkinter as ctk

from config import APP_NAME, APP_VERSION, is_gov_build
from ai.llm_client import get_model_name, is_lm_studio_online, clear_chat_history, set_chat_history_store
from core.chat_manager import (
    DEFAULT_FOLDER,
    ensure_registry,
    active_chat,
    create_chat,
    delete_chat,
    set_active,
    add_folder,
    append_chat_line,
    read_chat_lines,
    chat_line_count,
    list_folders,
)
from core.ai_router import route
from core.logger import log
from core.system_monitor import get_primary_disk_path
from core.settings import load_settings, save_settings
from core.memory import load_memory, save_memory
from voice.tts import speak, preload_tts_models
from voice.stt import listen_microphone


BG = "#0B0B0C"
PANEL = "#151516"
PANEL_2 = "#1D1D1F"
BORDER = "#2A2A2D"
ORANGE = "#FF7A1A"
GREEN = "#00FF66"
RED = "#FF4D4D"
TEXT = "#F2F2F2"
MUTED = "#8B8B8B"


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class FedoApp(ctk.CTk):
    # v1.4.5: голоса для «мастерской» в Настройках
    RU_VOICES = [
        ("aidar", "Aidar — суровый мужской"),
        ("eugene", "Eugene — спокойный мужской"),
        ("baya", "Baya — женский"),
        ("kseniya", "Kseniya — женский"),
        ("xenia", "Xenia — женский"),
    ]
    EN_VOICES = [
        ("en_1", "Голос 1 (en_1)"),
        ("en_10", "Голос 10 (en_10)"),
        ("en_30", "Голос 30 (en_30)"),
        ("en_60", "Голос 60 (en_60)"),
        ("en_90", "Голос 90 (en_90)"),
    ]

    def __init__(self):
        super().__init__()

        # v1.5.10: ГОВ-сборка помечена в заголовке
        build_tag = " (ГОС)" if is_gov_build() else ""
        self.title(f"{APP_NAME} {APP_VERSION}{build_tag}")
        self.geometry("1050x720")
        self.minsize(900, 600)
        self.configure(fg_color=BG)

        self.settings = load_settings()

        # v1.5.10: ГОВ-сборки нет «Агрессивного» режима —
        # если в старых настройках он сохранён, тихо сбрасываем
        if is_gov_build() and self.settings.get("personality_mode") == "Агрессивный":
            self.settings["personality_mode"] = "Современный"
            save_settings(self.settings)

        # v1.5.8: много-чат (папки, свой файл и своя LLM-память на чат)
        self.chat_registry = ensure_registry()
        self.active_chat = active_chat(self.chat_registry)

        self.dev_mode = self.settings.get("developer_mode", False)
        self.is_processing = False
        self.dev_clicks = 0
        # v1.5.1: разблокировка 18+ теперь персистентна (подтверждена один раз —
        # режим доступен между запусками) и реально сохраняется в файл
        self.secret_aggressive_unlocked = self.settings.get("aggressive_unlocked", False)

        self.pages = {}
        self.tab_buttons = {}

        self._set_icon()
        self._build_layout()
        self._setup_hotkeys()
        self._setup_context_menu()
        self._build_tabs()
        self._build_chat_page()
        self._build_chats_page()
        self._build_pc_page()
        self._build_memory_page()
        self._build_settings_page()

        if self.dev_mode:
            self._build_dev_pages()

        self.show_page("Чат")
        self._boot_sequence()
        self._start_monitor()

    def _update_ai_status(self):
        try:
            online = is_lm_studio_online()
            if online:
                model = get_model_name()
                text = f"AI: {model}"
            else:
                text = "AI: OFFLINE"
        except Exception as e:
            text = f"AI: ERROR ({e})"

        if hasattr(self, "ai_label") and self.ai_label.winfo_exists():
            self.ai_label.configure(text=text)

        if hasattr(self, "ai_value") and self.ai_value.winfo_exists():
            self.ai_value.configure(text=text.replace("AI: ", ""))

    def _set_icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

    def _setup_hotkeys(self):
        self.bind_all("<KeyPress>", self._global_hotkeys, add="+")

    def _global_hotkeys(self, event=None):
        if event is None:
            return

        ctrl_pressed = (event.state & 0x4) != 0
        if not ctrl_pressed:
            return

        key = event.keycode
        widget = event.widget

        if key == 65:
            return self._hotkey_select_all(target_widget=widget)

        if key == 67:
            return self._hotkey_copy(target_widget=widget)

        if key == 86:
            return self._hotkey_paste(target_widget=widget)

        if key == 88:
            return self._hotkey_cut(target_widget=widget)

    def _hotkey_select_all(self, event=None, target_widget=None):
        widget = target_widget or (event.widget if event else self.focus_get())
        if not widget:
            return
        try:
            cls = widget.winfo_class()
            if cls in ["Entry", "TEntry"]:
                widget.selection_range(0, "end")
                widget.icursor("end")
                return "break"
            elif cls == "Text":
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "end-1c")
                widget.see("insert")
                return "break"
        except Exception as e:
            log(f"[HOTKEY CTRL+A ERROR] {e}")

    def _hotkey_copy(self, event=None, target_widget=None):
        widget = target_widget or (event.widget if event else self.focus_get())
        if not widget:
            return
        try:
            text = widget.selection_get()
            self.clipboard_clear()
            self.clipboard_append(text)
            return "break"
        except Exception:
            pass

    def _hotkey_paste(self, event=None, target_widget=None):
        widget = target_widget or (event.widget if event else self.focus_get())
        if not widget:
            return
        try:
            text = self.clipboard_get()
            cls = widget.winfo_class()
            if cls in ["Entry", "TEntry"]:
                try:
                    widget.delete("sel.first", "sel.last")
                except Exception:
                    pass
                widget.insert("insert", text)
                return "break"
            elif cls == "Text":
                if str(widget.cget("state")) == "disabled":
                    return "break"
                try:
                    widget.delete("sel.first", "sel.last")
                except Exception:
                    pass
                widget.insert("insert", text)
                return "break"
        except Exception as e:
            log(f"[HOTKEY CTRL+V ERROR] {e}")

    def _hotkey_cut(self, event=None, target_widget=None):
        widget = target_widget or (event.widget if event else self.focus_get())
        if not widget:
            return
        try:
            text = widget.selection_get()
            self.clipboard_clear()
            self.clipboard_append(text)
            cls = widget.winfo_class()
            if cls in ["Entry", "TEntry"]:
                widget.delete("sel.first", "sel.last")
                return "break"
            elif cls == "Text":
                if str(widget.cget("state")) == "disabled":
                    return "break"
                widget.delete("sel.first", "sel.last")
                return "break"
        except Exception as e:
            log(f"[HOTKEY CTRL+X ERROR] {e}")

    def _setup_context_menu(self):
        self.context_target = None

        self.context_menu = ctk.CTkToplevel(self)
        self.context_menu.withdraw()
        self.context_menu.overrideredirect(True)
        self.context_menu.configure(fg_color=PANEL)

        btn_kwargs = {
            "width": 140,
            "height": 32,
            "fg_color": PANEL,
            "hover_color": PANEL_2,
            "text_color": TEXT
        }

        self.context_copy_btn = ctk.CTkButton(self.context_menu, text="Копировать", command=self._context_copy, **btn_kwargs)
        self.context_copy_btn.pack(fill="x", padx=4, pady=(4, 2))

        self.context_paste_btn = ctk.CTkButton(self.context_menu, text="Вставить", command=self._context_paste, **btn_kwargs)
        self.context_paste_btn.pack(fill="x", padx=4, pady=2)

        self.context_cut_btn = ctk.CTkButton(self.context_menu, text="Вырезать", command=self._context_cut, **btn_kwargs)
        self.context_cut_btn.pack(fill="x", padx=4, pady=2)

        self.context_select_btn = ctk.CTkButton(self.context_menu, text="Выделить всё", command=self._context_select_all, **btn_kwargs)
        self.context_select_btn.pack(fill="x", padx=4, pady=(2, 4))

        self.bind_all("<Button-3>", self._show_context_menu, add="+")
        self.bind_all("<Button-1>", self._hide_context_menu, add="+")

    def _get_real_widget(self, widget):
        if hasattr(widget, "_entry"):
            return widget._entry
        if hasattr(widget, "_textbox"):
            return widget._textbox
        return widget

    def _show_context_menu(self, event=None):
        if event is None:
            return

        widget = self._get_real_widget(event.widget)

        try:
            cls = widget.winfo_class()
        except Exception:
            return

        if cls not in ["Entry", "Text", "TEntry"]:
            return

        self.context_target = widget

        try:
            state = str(widget.cget("state"))
            if state == "disabled":
                self.context_paste_btn.configure(state="disabled")
                self.context_cut_btn.configure(state="disabled")
            else:
                self.context_paste_btn.configure(state="normal")
                self.context_cut_btn.configure(state="normal")
        except Exception:
            pass

        self.context_menu.geometry(f"+{event.x_root}+{event.y_root}")
        self.context_menu.deiconify()
        self.context_menu.lift()

    def _hide_context_menu(self, event=None):
        try:
            self.context_menu.withdraw()
        except Exception:
            pass

    def _context_copy(self):
        self._hide_context_menu()
        if self.context_target:
            self._hotkey_copy(target_widget=self.context_target)

    def _context_paste(self):
        self._hide_context_menu()
        if self.context_target:
            self._hotkey_paste(target_widget=self.context_target)

    def _context_cut(self):
        self._hide_context_menu()
        if self.context_target:
            self._hotkey_cut(target_widget=self.context_target)

    def _context_select_all(self):
        self._hide_context_menu()
        if self.context_target:
            self._hotkey_select_all(target_widget=self.context_target)

    def _build_layout(self):
        self.header = ctk.CTkFrame(self, fg_color=BG, height=70)
        self.header.pack(fill="x", padx=18, pady=(14, 0))

        title = ctk.CTkLabel(
            self.header,
            text=f"{APP_NAME} {APP_VERSION}" + (" (ГОС)" if is_gov_build() else ""),
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT
        )
        title.pack(side="left")
        title.bind("<Button-1>", self._secret_dev_click)

        self.status_label = ctk.CTkLabel(
            self.header,
            text="STATUS: READY",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=ORANGE
        )
        self.status_label.pack(side="right", padx=10)

        self.ai_label = ctk.CTkLabel(
            self.header,
            text="AI: CHECKING...",
            font=ctk.CTkFont(size=12),
            text_color=MUTED
        )
        self.ai_label.pack(side="right", padx=10)

        # v1.5.7: кнопка выключения F.E.D.O.
        self.power_btn = ctk.CTkButton(
            self.header,
            text="ВЫКЛ",
            width=76,
            height=28,
            corner_radius=8,
            fg_color="#2A1414",
            hover_color="#3A1919",
            text_color=RED,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._confirm_shutdown
        )
        self.power_btn.pack(side="right", padx=10)

        self.tabs_frame = ctk.CTkFrame(self, fg_color=BG)
        self.tabs_frame.pack(fill="x", padx=18, pady=(10, 8))

        self.content = ctk.CTkFrame(self, fg_color=BG)
        self.content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

    def _build_tabs(self):
        for name in ["Чат", "Чаты", "ПК", "Память", "Настройки"]:
            self._add_tab_button(name)

        if self.dev_mode:
            for name in ["Терминал", "Логи", "Отладка"]:
                self._add_tab_button(name)

    def _add_tab_button(self, name):
        btn = ctk.CTkButton(
            self.tabs_frame,
            text=name,
            height=36,
            corner_radius=10,
            fg_color=PANEL,
            hover_color=PANEL_2,
            text_color=MUTED,
            command=lambda n=name: self.show_page(n)
        )
        btn.pack(side="left", padx=(0, 8))
        self.tab_buttons[name] = btn

    def _rebuild_tabs(self):
        for widget in self.tabs_frame.winfo_children():
            widget.destroy()
        self.tab_buttons.clear()
        self._build_tabs()

    def show_page(self, name):
        for page in self.pages.values():
            page.pack_forget()

        if name in self.pages:
            self.pages[name].pack(fill="both", expand=True)

        for tab_name, btn in self.tab_buttons.items():
            if tab_name == name:
                btn.configure(fg_color=ORANGE, text_color="white")
            else:
                btn.configure(fg_color=PANEL, text_color=MUTED)

        if name == "Память":
            self._refresh_memory()
        if name == "Чаты":
            self._refresh_chats_page()
        if name == "Логи" and self.dev_mode:
            self._refresh_logs()
        if name == "Отладка" and self.dev_mode:
            self._refresh_debug()

    def _make_page(self, name):
        page = ctk.CTkFrame(self.content, fg_color=BG)
        self.pages[name] = page
        return page

    # =========================
    # CHAT
    # =========================

    def _build_chat_page(self):
        page = self._make_page("Чат")

        self.chat_box = ctk.CTkTextbox(
            page,
            fg_color="#050506",
            text_color=TEXT,
            border_color=BORDER,
            border_width=1,
            corner_radius=14,
            font=ctk.CTkFont(family="Consolas", size=14)
        )
        self.chat_box.pack(fill="both", expand=True, pady=(0, 12))
        self.chat_box.configure(state="disabled")

        input_frame = ctk.CTkFrame(page, fg_color=PANEL, corner_radius=16, border_width=1, border_color=BORDER)
        input_frame.pack(fill="x")

        self.entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="Введите директиву...",
            fg_color="transparent",
            border_width=0,
            height=46,
            text_color=TEXT,
            font=ctk.CTkFont(size=14)
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=14, pady=8)
        self.entry.bind("<Return>", lambda e: self.send_message())

        mic_btn = ctk.CTkButton(
            input_frame,
            text="MIC",
            width=70,
            height=38,
            corner_radius=10,
            fg_color=PANEL_2,
            hover_color="#2A2A2D",
            command=self.mic_input
        )
        mic_btn.pack(side="right", padx=(0, 8))

        send_btn = ctk.CTkButton(
            input_frame,
            text="SEND",
            width=90,
            height=38,
            corner_radius=10,
            fg_color=ORANGE,
            hover_color="#E86D14",
            command=self.send_message
        )
        send_btn.pack(side="right", padx=(0, 10))

    def _chat_write(self, text, sender="F.E.D.O"):
        self.chat_box.configure(state="normal")

        if sender == "USER":
            prefix = "\n> USER: "
        elif sender == "SYSTEM":
            prefix = "\n[SYSTEM] "
        else:
            prefix = "\nF.E.D.O: "

        self.chat_box.insert("end", prefix + str(text).strip() + "\n")
        self.chat_box.see("end")
        self.chat_box.configure(state="disabled")

        # v1.5.8: архив диалога — файл АКТИВНОГО чата (data/chats/<папка>/<чаты>.txt)
        self._chat_log_append(text, sender)

    def _chat_log_append(self, text, sender="F.E.D.O"):
        """v1.5.8: дописать реплику в файл активного чата."""
        try:
            from datetime import datetime
            if not self.active_chat:
                return
            line = f"[{datetime.now().strftime('%H:%M:%S')}] {sender}: {str(text).strip()}"
            append_chat_line(self.active_chat, line)
        except Exception:
            pass

    def _load_chat_archive(self):
        """v1.5.8: восстановить активный чат в окно (80 последних строк)."""
        try:
            if not self.active_chat:
                return
            lines = read_chat_lines(self.active_chat, limit=80)
            self.chat_box.configure(state="normal")
            for line in lines:
                self.chat_box.insert("end", line + "\n")
            self.chat_box.see("end")
            self.chat_box.configure(state="disabled")
        except Exception:
            pass

    def send_message(self):
        if self.is_processing:
            return

        text = self.entry.get().strip()
        if not text:
            return

        self.entry.delete(0, "end")
        self._chat_write(text, "USER")
        log(f"[USER] {text}")

        if text.lower() in ["exit", "quit", "выход", "пока"]:
            self._chat_write("Завершение сессии оператора.", "SYSTEM")
            self.after(800, self.destroy)
            return

        self._set_status("THINKING")
        threading.Thread(target=self._process_message, args=(text,), daemon=True).start()

    def _process_message(self, text):
        # v1.4: GUI — только интерфейс. Вся логика идёт через AI Router.
        try:
            answer = route(text)
        except Exception as e:
            answer = f"Ошибка обработки запроса: {e}"
            log(f"[GUI ERROR] {e}")

        self.after(0, lambda: self._response_ready(answer))

    def _response_ready(self, answer):
        self._chat_write(answer, "F.E.D.O")
        self._set_status("READY")
        self._update_ai_status()

        if self.settings.get("voice_enabled", True):
            threading.Thread(target=lambda: speak(str(answer)), daemon=True).start()

    def mic_input(self):
        if self.is_processing:
            return

        self._set_status("LISTENING")

        def task():
            try:
                text = listen_microphone()
            except Exception as e:
                text = f"Ошибка микрофона: {e}"
            self.after(0, lambda: self._mic_done(text))

        threading.Thread(target=task, daemon=True).start()

    def _mic_done(self, text):
        self._set_status("READY")
        if text.startswith("Ошибка"):
            self._chat_write(text, "SYSTEM")
            return
        self.entry.insert(0, text)
        self.send_message()

    def _set_status(self, status):
        self.is_processing = status not in ["READY"]
        self.status_label.configure(text=f"STATUS: {status}")

    def _boot_sequence(self):
        # v1.5.8: LLM-память активного чата
        if self.active_chat:
            set_chat_history_store(self.active_chat.get("id", "main"))

        # v1.5.3: восстанавливаем активный чат из его файла
        self._load_chat_archive()

        self._chat_write("Платформа оператора F.E.D.O активна.", "SYSTEM")
        self._chat_write(f"Интерфейс {APP_VERSION} загружен. Linux-ready.", "SYSTEM")
        self._update_ai_status()

        # v1.5.3: предзагрузка голосовых моделей в фоне
        # (первый ответ не ждёт скачивания)
        if self.settings.get("voice_enabled", True):
            threading.Thread(target=preload_tts_models, daemon=True).start()

        # v1.5.4: имя задаёт сам пользователь — при первом запуске
        # спрашиваем один раз, дальше можно менять в чате: «меня зовут ...»
        try:
            from core.user_profile import get_field
            if not str(get_field("name") or "").strip():
                self.after(400, self._ask_user_name)
        except Exception:
            pass

    # =========================
    # USER NAME (v1.5.4)
    # =========================

    def _ask_user_name(self):
        """v1.5.4: первый запуск — пользователь вводит своё имя сам."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("F.E.D.O — Как тебя зовут?")
        dialog.geometry("440x200")
        dialog.configure(fg_color=BG)
        dialog.attributes("-topmost", True)

        try:
            ctk.CTkLabel(
                dialog,
                text="Как тебя зовут?",
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color=TEXT
            ).pack(pady=(22, 4))

            ctk.CTkLabel(
                dialog,
                text="F.E.D.O. будет обращаться к тебе по имени.\nПозже можно поменять: «меня зовут ...»",
                text_color=MUTED,
                font=ctk.CTkFont(size=12),
                justify="center"
            ).pack(pady=(0, 10))

            name_var = ctk.StringVar()
            entry = ctk.CTkEntry(
                dialog,
                textvariable=name_var,
                placeholder_text="Твоё имя",
                height=38,
                corner_radius=10,
                fg_color="#0F0F10",
                border_width=1,
                border_color=BORDER,
                text_color=TEXT
            )
            entry.pack(pady=(0, 12), padx=60, fill="x")
            entry.focus_set()
            entry.bind("<Return>", lambda e: self._save_user_name(dialog, name_var))

            ctk.CTkButton(
                dialog,
                text="Пропустить",
                height=34,
                corner_radius=10,
                fg_color=PANEL_2,
                hover_color="#2A2A2D",
                text_color=TEXT,
                command=lambda: self._save_user_name(dialog, name_var, skip=True)
            ).pack(side="left", padx=8, pady=(0, 18))

            ctk.CTkButton(
                dialog,
                text="OK",
                height=34,
                width=100,
                corner_radius=10,
                fg_color=ORANGE,
                hover_color="#E86D14",
                command=lambda: self._save_user_name(dialog, name_var)
            ).pack(side="left", padx=(0, 8), pady=(0, 18))
        except Exception as e:
            log(f"[NAME DIALOG ERROR] {e}")
            dialog.destroy()
            return

        dialog.after(100, dialog.grab_set)

    def _save_user_name(self, dialog, name_var, skip=False):
        """v1.5.4: сохранить имя из окна первого запуска."""
        from core.user_profile import set_field

        name = name_var.get().strip() if not skip else ""

        if name:
            set_field("name", name)
            try:
                self._chat_write(
                    f"Принято. Теперь я буду обращаться к тебе как «{name}».",
                    "SYSTEM"
                )
            except Exception:
                pass

        try:
            dialog.destroy()
        except Exception:
            pass

    # =========================
    # SHUTDOWN (v1.5.7)
    # =========================

    def _confirm_shutdown(self):
        """v1.5.7: кнопка ВЫКЛ — подтверждение и чистое завершение."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("F.E.D.O — Завершение работы")
        dialog.geometry("380x190")
        dialog.configure(fg_color=BG)
        dialog.attributes("-topmost", True)

        try:
            ctk.CTkLabel(
                dialog,
                text="Выключить F.E.D.O.?",
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color=TEXT
            ).pack(pady=(22, 4))

            ctk.CTkLabel(
                dialog,
                text="Чат и память сохранены.\nСистема завершит работу.",
                text_color=MUTED,
                font=ctk.CTkFont(size=12),
                justify="center"
            ).pack(pady=(0, 10))

            btns = ctk.CTkFrame(dialog, fg_color=BG)
            btns.pack(pady=18)

            ctk.CTkButton(
                btns,
                text="Отмена",
                height=34,
                width=100,
                corner_radius=10,
                fg_color=PANEL_2,
                hover_color="#2A2A2D",
                text_color=TEXT,
                command=dialog.destroy
            ).pack(side="left", padx=8)

            def power_off():
                try:
                    self._chat_write("Завершение сессии оператора. Гашу контуры.", "SYSTEM")
                except Exception:
                    pass
                dialog.destroy()
                self.after(600, self.destroy)

            ctk.CTkButton(
                btns,
                text="ВЫКЛ",
                height=34,
                width=100,
                corner_radius=10,
                fg_color=RED,
                hover_color="#D93F3F",
                text_color="white",
                command=power_off
            ).pack(side="left", padx=8)
        except Exception as e:
            log(f"[SHUTDOWN DIALOG ERROR] {e}")
            dialog.destroy()
            return

        dialog.after(100, dialog.grab_set)

    # =========================
    # CHATS PAGE (v1.5.8)
    # =========================

    def _build_chats_page(self):
        page = self._make_page("Чаты")

        title = ctk.CTkLabel(page, text="Чаты", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT)
        title.pack(anchor="w", pady=(0, 12))

        # Панель действий: выбор папки, новая папка, новый чат
        bar = ctk.CTkFrame(page, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
        bar.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(bar, text="Папка:", text_color=MUTED, font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(14, 6), pady=10
        )

        self.chats_folder_var = ctk.StringVar(value=DEFAULT_FOLDER)
        self.chats_folder_menu = ctk.CTkOptionMenu(
            bar,
            variable=self.chats_folder_var,
            values=list_folders(self.chat_registry),
            fg_color="#0F0F10",
            button_color=PANEL_2,
            button_hover_color="#2A2A2D",
            width=140
        )
        self.chats_folder_menu.pack(side="left", padx=6, pady=10)

        ctk.CTkButton(
            bar,
            text="＋ Новая папка",
            width=120,
            height=30,
            corner_radius=8,
            fg_color=PANEL_2,
            hover_color="#2A2A2D",
            text_color=TEXT,
            command=self._new_folder
        ).pack(side="left", padx=6, pady=10)

        ctk.CTkButton(
            bar,
            text="＋ Новый чат",
            width=120,
            height=30,
            corner_radius=8,
            fg_color=ORANGE,
            hover_color="#E86D14",
            command=self._new_chat
        ).pack(side="left", padx=6, pady=10)

        self.chats_list = ctk.CTkScrollableFrame(page, fg_color=BG)
        self.chats_list.pack(fill="both", expand=True)

        self._refresh_chats_page()

    def _refresh_chats_page(self):
        if not hasattr(self, "chats_list"):
            return

        for w in self.chats_list.winfo_children():
            w.destroy()

        reg = self.chat_registry = ensure_registry()
        folders = list_folders(reg)

        current = self.chats_folder_var.get()
        if current not in folders:
            current = folders[0]
        self.chats_folder_menu.configure(values=folders)
        self.chats_folder_var.set(current)

        by_folder = {}
        for chat in reg["chats"]:
            by_folder.setdefault(chat.get("folder", DEFAULT_FOLDER), []).append(chat)

        for folder in folders:
            chats = by_folder.get(folder, [])

            ctk.CTkLabel(
                self.chats_list,
                text=folder.upper(),
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=ORANGE
            ).pack(anchor="w", padx=10, pady=(14, 4))

            if not chats:
                ctk.CTkLabel(
                    self.chats_list,
                    text="пусто",
                    text_color=MUTED,
                    font=ctk.CTkFont(size=11)
                ).pack(anchor="w", padx=20, pady=2)
                continue

            for chat in chats:
                card = ctk.CTkFrame(self.chats_list, fg_color=PANEL, corner_radius=12,
                                    border_width=1, border_color=BORDER)
                card.pack(fill="x", padx=10, pady=4)

                is_active = reg.get("active") == chat.get("id")

                ctk.CTkLabel(
                    card,
                    text=chat.get("title", "чат") + ("   ● активен" if is_active else ""),
                    text_color=ORANGE if is_active else TEXT,
                    font=ctk.CTkFont(size=14, weight="bold" if is_active else "normal")
                ).pack(side="left", padx=16, pady=10)

                ctk.CTkLabel(
                    card,
                    text=f"{chat_line_count(chat)} строк · {chat.get('created', '')}",
                    text_color=MUTED,
                    font=ctk.CTkFont(size=11)
                ).pack(side="left", padx=8)

                ctk.CTkButton(
                    card,
                    text="Удалить",
                    width=80,
                    fg_color="#2A1414",
                    hover_color="#3A1919",
                    text_color=RED,
                    command=lambda c=chat: self._confirm_delete_chat(c)
                ).pack(side="right", padx=12)

                ctk.CTkButton(
                    card,
                    text="Открыть",
                    width=90,
                    fg_color=PANEL_2,
                    hover_color="#2A2A2D",
                    text_color=TEXT,
                    command=lambda c=chat: self._open_chat(c)
                ).pack(side="right", padx=(0, 8))

    def _open_chat(self, chat):
        """v1.5.8: открыть чат (активный + его LLM-память)."""
        set_active(self.chat_registry, chat["id"])
        self.active_chat = chat

        try:
            set_chat_history_store(chat.get("id", "main"))
        except Exception:
            pass

        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.configure(state="disabled")

        self.show_page("Чат")
        self._chat_write(f"Открыт чат: «{chat.get('title', 'чат')}».", "SYSTEM")
        self._load_chat_archive()

    def _new_chat(self):
        """v1.5.8: создать новый чат в выбранной папке."""
        try:
            title = ctk.CTkInputDialog(
                text="Название чата:",
                title="F.E.D.O — Новый чат"
            ).get_input()
        except Exception:
            return

        if title is None or not str(title).strip():
            return

        folder = self.chats_folder_var.get() or DEFAULT_FOLDER
        chat = create_chat(self.chat_registry, str(title).strip(), folder)
        self.active_chat = chat

        try:
            set_chat_history_store(chat.get("id", "main"))
        except Exception:
            pass

        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.configure(state="disabled")

        self.show_page("Чат")
        self._chat_write(f"Создан чат: «{chat.get('title')}» (папка: {folder}).", "SYSTEM")
        self._refresh_chats_page()

    def _new_folder(self):
        """v1.5.8: создать новую папку."""
        try:
            name = ctk.CTkInputDialog(
                text="Название папки:",
                title="F.E.D.O — Новая папка"
            ).get_input()
        except Exception:
            return

        if name is None or not str(name).strip():
            return

        folder = add_folder(self.chat_registry, str(name))
        self.chats_folder_menu.configure(values=list_folders(self.chat_registry))
        self.chats_folder_var.set(folder)
        self._refresh_chats_page()

    def _confirm_delete_chat(self, chat):
        """v1.5.8: удаление чата (файл + LLM-память)."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("F.E.D.O — Удаление чата")
        dialog.geometry("400x200")
        dialog.configure(fg_color=BG)
        dialog.attributes("-topmost", True)

        title = chat.get("title", "чат")

        try:
            ctk.CTkLabel(
                dialog,
                text=f"Удалить чат «{title}»?",
                font=ctk.CTkFont(size=17, weight="bold"),
                text_color=TEXT
            ).pack(pady=(22, 4))

            ctk.CTkLabel(
                dialog,
                text="Файл чата и его LLM-память будут\nудалены без возможности восстановления.",
                text_color=MUTED,
                font=ctk.CTkFont(size=12),
                justify="center"
            ).pack(pady=(0, 10))

            btns = ctk.CTkFrame(dialog, fg_color=BG)
            btns.pack(pady=18)

            def do_delete():
                delete_chat(self.chat_registry, chat["id"])

                # если удалили активный — переключиться на другой
                if self.active_chat and self.active_chat.get("id") == chat.get("id"):
                    reg = ensure_registry()
                    self.active_chat = active_chat(reg)
                    try:
                        set_chat_history_store(
                            self.active_chat.get("id") if self.active_chat else "main"
                        )
                    except Exception:
                        pass

                dialog.destroy()
                self._refresh_chats_page()

            ctk.CTkButton(
                btns,
                text="Отмена",
                height=34,
                width=100,
                corner_radius=10,
                fg_color=PANEL_2,
                hover_color="#2A2A2D",
                text_color=TEXT,
                command=dialog.destroy
            ).pack(side="left", padx=8)

            ctk.CTkButton(
                btns,
                text="Удалить",
                height=34,
                width=100,
                corner_radius=10,
                fg_color=RED,
                hover_color="#D93F3F",
                text_color="white",
                command=do_delete
            ).pack(side="left", padx=8)
        except Exception as e:
            log(f"[CHAT DELETE DIALOG ERROR] {e}")
            dialog.destroy()
            return

        dialog.after(100, dialog.grab_set)

    # =========================
    # PC
    # =========================

    def _build_pc_page(self):
        page = self._make_page("ПК")

        title = ctk.CTkLabel(page, text="Состояние системы", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT)
        title.pack(anchor="w", pady=(0, 16))

        grid = ctk.CTkFrame(page, fg_color=BG)
        grid.pack(fill="both", expand=True)

        grid.columnconfigure((0, 1), weight=1)
        grid.rowconfigure((0, 1, 2), weight=1)

        disk_path = get_primary_disk_path()

        self.cpu_value = self._metric_card(grid, "CPU", 0, 0)
        self.ram_value = self._metric_card(grid, "RAM", 0, 1)
        self.gpu_value = self._metric_card(grid, "GPU / VRAM", 1, 0)
        self.disk_value = self._metric_card(grid, f"DISK {disk_path}", 1, 1)
        self.ai_value = self._metric_card(grid, "AI CORE", 2, 0)
        self.ai_value.master.grid(columnspan=2)

    def _metric_card(self, parent, title, row, col):
        card = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=16, border_width=1, border_color=BORDER)
        card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)

        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color=MUTED).pack(
            anchor="w", padx=20, pady=(18, 8)
        )

        value = ctk.CTkLabel(card, text="--", font=ctk.CTkFont(size=28, weight="bold"), text_color=ORANGE)
        value.pack(anchor="w", padx=20, pady=(0, 20))
        value.configure(justify="left", anchor="w")

        return value

    def _start_monitor(self):
        disk_path = get_primary_disk_path()

        def loop():
            while True:
                try:
                    cpu = psutil.cpu_percent(interval=1)
                    ram = psutil.virtual_memory()
                    disk = psutil.disk_usage(disk_path)
                    self.after(0, lambda c=cpu, r=ram, d=disk: self._update_metrics(c, r, d))
                except Exception as e:
                    log(f"[MONITOR ERROR] {e}")

        threading.Thread(target=loop, daemon=True).start()

    def _update_metrics(self, cpu, ram, disk):
        if hasattr(self, "cpu_value") and self.cpu_value.winfo_exists():
            self.cpu_value.configure(text=f"{cpu:.0f}%")

        if hasattr(self, "ram_value") and self.ram_value.winfo_exists():
            self.ram_value.configure(
                text=f"{ram.used / (1024 ** 3):.1f} / {ram.total / (1024 ** 3):.1f} GB"
            )

        if hasattr(self, "disk_value") and self.disk_value.winfo_exists():
            self.disk_value.configure(
                text=f"{disk.used / (1024 ** 3):.0f} / {disk.total / (1024 ** 3):.0f} GB"
            )

        if hasattr(self, "gpu_value") and self.gpu_value.winfo_exists():
            if GPUtil is None:
                self.gpu_value.configure(text="GPUtil not installed")
                return

            try:
                gpus = GPUtil.getGPUs()
                if not gpus:
                    self.gpu_value.configure(text="GPU not found")
                    return

                gpu = gpus[0]
                used = gpu.memoryUsed / 1024
                total = gpu.memoryTotal / 1024
                free = gpu.memoryFree / 1024

                self.gpu_value.configure(
                    text=(
                        f"{gpu.name}\n"
                        f"Load: {gpu.load * 100:.0f}% | Temp: {gpu.temperature:.0f}°C\n"
                        f"VRAM: {used:.1f} / {total:.1f} GB | Free: {free:.1f} GB"
                    ),
                    font=ctk.CTkFont(size=16, weight="bold"),
                    justify="left",
                    anchor="w"
                )

            except Exception as e:
                self.gpu_value.configure(text=f"GPU error: {e}")

    # =========================
    # MEMORY
    # =========================

    def _build_memory_page(self):
        page = self._make_page("Память")

        title = ctk.CTkLabel(page, text="Память F.E.D.O", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT)
        title.pack(anchor="w", pady=(0, 16))

        self.memory_frame = ctk.CTkScrollableFrame(page, fg_color=BG)
        self.memory_frame.pack(fill="both", expand=True)

    def _refresh_memory(self):
        for widget in self.memory_frame.winfo_children():
            widget.destroy()

        memory = load_memory()

        if not memory:
            ctk.CTkLabel(
                self.memory_frame,
                text="Память пуста.",
                text_color=MUTED,
                font=ctk.CTkFont(size=14)
            ).pack(pady=30)
            return

        for key, value in memory.items():
            card = ctk.CTkFrame(self.memory_frame, fg_color=PANEL, corner_radius=14, border_width=1, border_color=BORDER)
            card.pack(fill="x", pady=6)

            text = ctk.CTkLabel(
                card,
                text=f"{key}\n{value}",
                justify="left",
                text_color=TEXT,
                font=ctk.CTkFont(size=14)
            )
            text.pack(side="left", padx=16, pady=12)

            btn = ctk.CTkButton(
                card,
                text="Удалить",
                width=80,
                fg_color="#2A1414",
                hover_color="#3A1919",
                text_color=RED,
                command=lambda k=key: self._delete_memory(k)
            )
            btn.pack(side="right", padx=12)

    def _delete_memory(self, key):
        memory = load_memory()
        if key in memory:
            del memory[key]
            save_memory(memory)
            log(f"[MEMORY] Удалено: {key}")
        self._refresh_memory()

    # =========================
    # SETTINGS
    # =========================

    def _build_settings_page(self):
        page = self._make_page("Настройки")

        title = ctk.CTkLabel(page, text="Настройки", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT)
        title.pack(anchor="w", pady=(0, 16))

        box = ctk.CTkScrollableFrame(page, fg_color=BG)
        box.pack(fill="both", expand=True)

        self._section(box, "ИИ")

        self.ai_provider = ctk.StringVar(value=self.settings.get("ai_provider", "Hybrid (Auto)"))
        self._option(box, "Поставщик ИИ", self.ai_provider, ["Hybrid (Auto)", "Gemini (Online Only)", "LM Studio (Offline)"])

        self.gemini_key = ctk.StringVar(value=self.settings.get("gemini_api_key", ""))
        self._entry(box, "Gemini API Key", self.gemini_key, show="*")

        self.lm_url = ctk.StringVar(
            value=self.settings.get("lm_studio_url", "http://127.0.0.1:1234/v1/chat/completions")
        )
        self._entry(box, "LM Studio URL", self.lm_url)

        self._section(box, "Голос")
        self.voice_enabled = ctk.BooleanVar(value=self.settings.get("voice_enabled", True))
        ctk.CTkSwitch(
            box,
            text="Включить голос Silero TTS",
            variable=self.voice_enabled,
            progress_color=ORANGE,
            text_color=TEXT
        ).pack(anchor="w", padx=10, pady=10)

        # v1.4.5: мастерская голосов — строки + кнопка «Прослушать»
        ctk.CTkLabel(
            box,
            text="Выберите голос и нажмите ▶ — F.E.D.O. прочитает фразу этим голосом.",
            text_color=MUTED,
            font=ctk.CTkFont(size=11)
        ).pack(anchor="w", padx=24, pady=(2, 6))

        saved_ru = str(self.settings.get("tts_speaker", "aidar")).strip()
        if saved_ru not in [v[0] for v in self.RU_VOICES]:
            saved_ru = "aidar"
        self.tts_speaker = ctk.StringVar(value=saved_ru)
        self._voice_group(box, "Русский голос (v4_ru)", self.tts_speaker, self.RU_VOICES, "ru")

        saved_en = str(self.settings.get("tts_speaker_en", "en_10")).strip()
        if saved_en not in [v[0] for v in self.EN_VOICES]:
            saved_en = "en_10"
        self.tts_speaker_en = ctk.StringVar(value=saved_en)
        self._voice_group(box, "Английский голос (v3_en)", self.tts_speaker_en, self.EN_VOICES, "en")

        self._tts_status = ctk.CTkLabel(box, text="", text_color=MUTED, font=ctk.CTkFont(size=11))
        self._tts_status.pack(anchor="w", padx=24, pady=(0, 6))

        self._section(box, "Интерфейс")
        self.dev_var = ctk.BooleanVar(value=self.dev_mode)
        ctk.CTkSwitch(
            box,
            text="Режим разработчика",
            variable=self.dev_var,
            progress_color=ORANGE,
            text_color=TEXT,
            command=self._toggle_dev_mode
        ).pack(anchor="w", padx=10, pady=10)

        self._section(box, "Язык ответов")

        self._lang_display = {
            "auto": "Авто (язык пользователя)",
            "ru": "Русский",
            "en": "English",
            "zh": "中文 (Китайский)",
        }
        self._lang_reverse = {v: k for k, v in self._lang_display.items()}
        current_lang = self._lang_reverse.get(
            str(self.settings.get("response_language", "auto")).strip().lower(),
            "auto"
        )
        self.response_language = ctk.StringVar(
            value=self._lang_display[current_lang]
        )
        self._option(
            box,
            "Язык F.E.D.O",
            self.response_language,
            list(self._lang_display.values())
        )

        self._section(box, "Режим личности")

        self.personality_mode = ctk.StringVar(
            value=self.settings.get("personality_mode", "СССР")
        )

        modes = [
            "СССР",
            "Джарвис",
            "Современный"
        ]

        # v1.5.10: в ГОВ-сборке «Агрессивного» нет — ни при каких настройках
        if self.secret_aggressive_unlocked and not is_gov_build():
            modes.append("Агрессивный")

        self._option(
            box,
            "Режим F.E.D.O",
            self.personality_mode,
            modes
        )

        save = ctk.CTkButton(
            box,
            text="Сохранить настройки",
            height=42,
            corner_radius=12,
            fg_color=ORANGE,
            hover_color="#E86D14",
            command=self._save_settings
        )
        save.pack(fill="x", padx=10, pady=24)

    def _section(self, parent, text):
        ctk.CTkLabel(
            parent,
            text=text.upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=ORANGE
        ).pack(anchor="w", padx=10, pady=(18, 8))

    def _entry(self, parent, label, variable, show=None):
        frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
        frame.pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(frame, text=label, text_color=TEXT, width=160, anchor="w").pack(side="left", padx=14, pady=10)

        entry = ctk.CTkEntry(
            frame,
            textvariable=variable,
            show=show,
            fg_color="#0F0F10",
            border_width=1,
            border_color=BORDER,
            text_color=TEXT
        )
        entry.pack(side="right", fill="x", expand=True, padx=14, pady=10)

    def _option(self, parent, label, variable, values):
        frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
        frame.pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(frame, text=label, text_color=TEXT, width=160, anchor="w").pack(side="left", padx=14, pady=10)

        menu = ctk.CTkOptionMenu(
            frame,
            values=values,
            variable=variable,
            fg_color="#0F0F10",
            button_color=PANEL_2,
            button_hover_color="#2A2A2D"
        )
        menu.pack(side="right", padx=14, pady=10)

    def _voice_group(self, parent, title, variable, voices, lang):
        """v1.4.5: группа голосов — радио-строки + кнопка «Прослушать»."""
        frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
        frame.pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(
            frame,
            text=title,
            text_color=TEXT,
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=14, pady=(12, 2))

        for value, label in voices:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=1)

            ctk.CTkRadioButton(
                row,
                text=label,
                variable=variable,
                value=value,
                fg_color=ORANGE,
                hover_color=ORANGE,
                text_color=TEXT,
                font=ctk.CTkFont(size=13)
            ).pack(side="left")

            ctk.CTkButton(
                row,
                text="▶",
                width=52,
                height=28,
                corner_radius=8,
                fg_color=PANEL_2,
                hover_color="#2A2A2D",
                text_color=TEXT,
                command=lambda l=lang, v=value: self._audition(l, v)
            ).pack(side="right", padx=(8, 4))

    def _set_tts_status(self, text):
        """Обновить строку статуса прослушивания (Настройки + мастер установки)."""
        try:
            self._tts_status.configure(text=text)
        except Exception:
            pass
        wizard_status = getattr(self, "_wizard_tts_status", None)
        if wizard_status is not None:
            try:
                wizard_status.configure(text=text)
            except Exception:
                pass

    def _audition(self, lang, speaker):
        """v1.4.5: проиграть фразу-пример выбранным голосом (фоновый поток)."""
        if getattr(self, "_audition_busy", False):
            return

        if not self.voice_enabled.get():
            self._set_tts_status("Голос отключён — включите переключатель выше.")
            return

        self._audition_busy = True
        self._audition_done = False
        self._set_tts_status("Прослушивание (первый раз — загрузка модели)...")

        def work():
            try:
                from voice.tts import audition
                audition(lang, speaker)
            except Exception as e:
                log(f"[TTS AUDITION ERROR] {e}")
            finally:
                self._audition_done = True

        threading.Thread(target=work, daemon=True).start()
        self.after(250, self._poll_audition)

    def _poll_audition(self):
        if not getattr(self, "_audition_done", False):
            self.after(250, self._poll_audition)
            return

        self._audition_done = False
        self._audition_busy = False
        self._set_tts_status("Готово.")

    def _rebuild_settings_page(self):
        if "Настройки" in self.pages:
            self.pages["Настройки"].pack_forget()
            self.pages["Настройки"].destroy()
            del self.pages["Настройки"]

        self._build_settings_page()

    def _toggle_dev_mode(self):
        if self.dev_var.get():
            self._show_dev_warning()
        else:
            self.dev_mode = False
            self.settings["developer_mode"] = False

            if self.settings.get("personality_mode") == "Агрессивный":
                self.settings["personality_mode"] = "СССР"

            save_settings(self.settings)

            self._remove_dev_pages()
            self._rebuild_settings_page()
            self._rebuild_tabs()
            self.show_page("Настройки")

    def _secret_dev_click(self, event=None):
        self.dev_clicks += 1

        if self.dev_clicks >= 5:
            self.dev_clicks = 0

            if not self.secret_aggressive_unlocked:
                # v1.5.1: сначала подтверждение 18+ и ответственности
                self._show_adult_confirm()
            else:
                # уже подтверждено — просто включаем режим
                self.settings["personality_mode"] = "Агрессивный"
                save_settings(self.settings)

                self._rebuild_settings_page()

                if hasattr(self, "personality_mode"):
                    self.personality_mode.set("Агрессивный")

                self.show_page("Настройки")

    def _show_adult_confirm(self):
        """v1.5.1: взрослая функция — 18+ и принятие ответственности."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("F.E.D.O — ВЗРОСЛАЯ ФУНКЦИЯ")
        dialog.geometry("560x400")
        dialog.configure(fg_color=BG)
        dialog.attributes("-topmost", True)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        age_var = ctk.BooleanVar(value=False)
        resp_var = ctk.BooleanVar(value=False)

        try:
            ctk.CTkLabel(
                dialog,
                text="ВЗРОСЛАЯ ФУНКЦИЯ",
                font=ctk.CTkFont(size=22, weight="bold"),
                text_color=RED
            ).pack(pady=(26, 8))

            ctk.CTkLabel(
                dialog,
                text="Агрессивный режим включает грубую подачу и\nнецензурную лексику в ответах F.E.D.O.",
                text_color=TEXT,
                justify="center",
                font=ctk.CTkFont(size=14)
            ).pack(pady=8)

            ctk.CTkCheckBox(
                dialog,
                text="Мне есть 18 лет",
                variable=age_var,
                fg_color=ORANGE,
                text_color=TEXT,
                font=ctk.CTkFont(size=15, weight="bold")
            ).pack(anchor="w", padx=70, pady=8)

            ctk.CTkCheckBox(
                dialog,
                text="Я принимаю полную ответственность за нецензурную\nлексику в ответах F.E.D.O.",
                variable=resp_var,
                fg_color=ORANGE,
                text_color=TEXT,
                font=ctk.CTkFont(size=13)
            ).pack(anchor="w", padx=70, pady=8)

            btns = ctk.CTkFrame(dialog, fg_color=BG)
            btns.pack(pady=22)

            def cancel():
                try:
                    self._chat_write(
                        "Скрытый протокол обнаружен. Подтверждение 18+ не получено — режим заблокирован.",
                        "SYSTEM"
                    )
                except Exception:
                    pass
                dialog.destroy()

            def confirm():
                if not (age_var.get() and resp_var.get()):
                    return
                self.secret_aggressive_unlocked = True
                self.settings["aggressive_unlocked"] = True
                self.settings["personality_mode"] = "Агрессивный"
                save_settings(self.settings)

                self._rebuild_settings_page()

                if hasattr(self, "personality_mode"):
                    self.personality_mode.set("Агрессивный")

                try:
                    self._chat_write(
                        "Скрытый протокол личности активирован. Подтверждение 18+ получено. Агрессивный режим включён.",
                        "SYSTEM"
                    )
                except Exception:
                    pass

                self.show_page("Настройки")
                dialog.destroy()

            ctk.CTkButton(btns, text="Отмена", fg_color=PANEL_2, command=cancel).pack(side="left", padx=8)
            ctk.CTkButton(
                btns,
                text="Подтвердить",
                fg_color=RED,
                hover_color="#D93F3F",
                text_color="white",
                command=confirm
            ).pack(side="left", padx=8)
        except Exception as e:
            log(f"[ADULT CONFIRM ERROR] {e}")
            dialog.destroy()
            return

        dialog.after(100, dialog.grab_set)

    def _show_dev_warning(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Режим разработчика")
        dialog.geometry("460x300")
        dialog.configure(fg_color=BG)
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(
            dialog,
            text="ВНИМАНИЕ",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=RED
        ).pack(pady=(28, 12))

        ctk.CTkLabel(
            dialog,
            text="Режим разработчика откроет терминал, логи и отладку проекта.\nИспользуйте осторожно.",
            text_color=TEXT,
            justify="center",
            wraplength=380
        ).pack(pady=10)

        btns = ctk.CTkFrame(dialog, fg_color=BG)
        btns.pack(pady=25)

        def cancel():
            self.dev_var.set(False)
            dialog.destroy()

        def confirm():
            self.dev_mode = True
            self.settings["developer_mode"] = True
            save_settings(self.settings)

            self._build_dev_pages()
            self._rebuild_settings_page()
            self._rebuild_tabs()

            dialog.destroy()
            self.show_page("Настройки")

        ctk.CTkButton(btns, text="Отмена", fg_color=PANEL_2, command=cancel).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Подтвердить", fg_color=ORANGE, command=confirm).pack(side="left", padx=8)

        # v1.5.9: grab — только после отрисовки окна (на Linux окно
        # ещё не viewable в момент создания → TclError: grab failed)
        def _safe_grab():
            try:
                if dialog.winfo_exists():
                    dialog.grab_set()
            except Exception:
                pass

        dialog.after(100, _safe_grab)

    def _save_settings(self):
        # v1.4: сохраняем поверх существующих настроек,
        # чтобы не терять новые ключи (сложность, мониторинг и т.д.)
        base = load_settings()
        base.update({
            "ai_provider": self.ai_provider.get(),
            "gemini_api_key": self.gemini_key.get().strip(),
            "lm_studio_url": self.lm_url.get().strip(),
            # v1.5.1: сохраняем выбранный режим как есть
            # (раньше "Агрессивный" молча превращался в "СССР")
            "personality_mode": self.personality_mode.get(),
            "response_language": self._lang_reverse.get(self.response_language.get(), "auto"),
            "voice_enabled": self.voice_enabled.get(),
            "tts_speaker": self.tts_speaker.get().strip(),
            "tts_speaker_en": self.tts_speaker_en.get().strip(),
            "developer_mode": self.dev_mode
        })

        self.settings = base
        save_settings(self.settings)
        clear_chat_history()
        self._chat_write("Настройки сохранены. История чата очищена.", "SYSTEM")
        self._update_ai_status()

    # =========================
    # DEV MODE
    # =========================

    def _build_dev_pages(self):
        if "Терминал" not in self.pages:
            self._build_terminal_page()
        if "Логи" not in self.pages:
            self._build_logs_page()
        if "Отладка" not in self.pages:
            self._build_debug_page()

    def _remove_dev_pages(self):
        for name in ["Терминал", "Логи", "Отладка"]:
            if name in self.pages:
                self.pages[name].destroy()
                del self.pages[name]

    def _build_terminal_page(self):
        page = self._make_page("Терминал")

        self.terminal_box = ctk.CTkTextbox(
            page,
            fg_color="#050506",
            text_color=GREEN,
            border_width=1,
            border_color=BORDER,
            corner_radius=14,
            font=ctk.CTkFont(family="Consolas", size=13)
        )
        self.terminal_box.pack(fill="both", expand=True, pady=(0, 12))
        self.terminal_box.insert("end", "F.E.D.O Developer Terminal\n")
        if os.name == "nt":
            self.terminal_box.insert("end", "Введите команду PowerShell/CMD ниже.\n\n")
            placeholder = "C:\\Users\\...>"
        else:
            self.terminal_box.insert("end", "Введите команду ниже (bash / Linux).\n\n")
            placeholder = "$ "

        input_frame = ctk.CTkFrame(page, fg_color=PANEL, corner_radius=14, border_width=1, border_color=BORDER)
        input_frame.pack(fill="x")

        self.term_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text=placeholder,
            fg_color="transparent",
            border_width=0,
            text_color=GREEN,
            height=44,
            font=ctk.CTkFont(family="Consolas", size=13)
        )
        self.term_entry.pack(side="left", fill="x", expand=True, padx=14)
        self.term_entry.bind("<Return>", lambda e: self._run_terminal_command())

        ctk.CTkButton(
            input_frame,
            text="RUN",
            width=90,
            fg_color=ORANGE,
            command=self._run_terminal_command
        ).pack(side="right", padx=10)

    def _run_terminal_command(self):
        cmd = self.term_entry.get().strip()
        if not cmd:
            return

        self.term_entry.delete(0, "end")
        self.terminal_box.insert("end", f"\n> {cmd}\n")
        self.terminal_box.see("end")

        # v1.4: блокировщик расширен для Linux-команд (bash)
        blocked = [
            "format", "shutdown", "reboot", "del /f", "rmdir /s", "rd /s",
            "rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:",
        ]
        if any(x in cmd.lower() for x in blocked):
            self.terminal_box.insert("end", "[BLOCKED] Опасная команда заблокирована.\n")
            return

        def task():
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15
                )
                output = result.stdout or ""
                if result.stderr:
                    output += "\n[ERR]\n" + result.stderr
                if not output.strip():
                    output = "Done."
            except Exception as e:
                output = f"Execution error: {e}"

            self.after(0, lambda: self._terminal_output(output))

        threading.Thread(target=task, daemon=True).start()

    def _terminal_output(self, output):
        self.terminal_box.insert("end", output.strip() + "\n")
        self.terminal_box.see("end")

    def _build_logs_page(self):
        page = self._make_page("Логи")

        self.logs_box = ctk.CTkTextbox(
            page,
            fg_color="#050506",
            text_color=ORANGE,
            border_width=1,
            border_color=BORDER,
            corner_radius=14,
            font=ctk.CTkFont(family="Consolas", size=13)
        )
        self.logs_box.pack(fill="both", expand=True, pady=(0, 12))

        ctk.CTkButton(
            page,
            text="Обновить логи",
            height=40,
            fg_color=ORANGE,
            command=self._refresh_logs
        ).pack(fill="x")

    def _refresh_logs(self):
        if not hasattr(self, "logs_box"):
            return

        path = os.path.join("logs", "session.log")
        self.logs_box.configure(state="normal")
        self.logs_box.delete("1.0", "end")

        if not os.path.exists(path):
            self.logs_box.insert("end", "logs/session.log не найден.\n")
        else:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    self.logs_box.insert("end", "".join(f.readlines()[-150:]))
            except Exception as e:
                self.logs_box.insert("end", f"Ошибка чтения логов: {e}")

        self.logs_box.see("end")
        self.logs_box.configure(state="disabled")

    def _build_debug_page(self):
        page = self._make_page("Отладка")

        self.debug_box = ctk.CTkTextbox(
            page,
            fg_color="#050506",
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
            corner_radius=14,
            font=ctk.CTkFont(family="Consolas", size=13)
        )
        self.debug_box.pack(fill="both", expand=True, pady=(0, 12))

        row = ctk.CTkFrame(page, fg_color=BG)
        row.pack(fill="x")

        ctk.CTkButton(row, text="Обновить", fg_color=ORANGE, command=self._refresh_debug).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="Очистить историю", fg_color=PANEL_2, command=clear_chat_history).pack(side="left", padx=8)
        ctk.CTkButton(row, text="Проверить AI", fg_color=PANEL_2, command=self._update_ai_status).pack(side="left", padx=8)

    def _refresh_debug(self):
        if not hasattr(self, "debug_box"):
            return

        try:
            local_online = is_lm_studio_online()
            model = get_model_name() if local_online else "OFFLINE"
        except Exception as e:
            model = f"ERROR: {e}"

        info = f"""
F.E.D.O DEBUG PANEL
------------------
APP_NAME: {APP_NAME}
APP_VERSION: {APP_VERSION}

Developer Mode: {self.dev_mode}
Voice Enabled: {self.settings.get("voice_enabled", True)}

AI Provider: {self.settings.get("ai_provider", "Hybrid (Auto)")}
LM Studio URL: {self.settings.get("lm_studio_url", "not set")}
Gemini Key: {"SET" if self.settings.get("gemini_api_key") else "EMPTY"}

Local Model: {model}

CPU: {psutil.cpu_percent()}%
RAM: {psutil.virtual_memory().percent}%
"""

        self.debug_box.configure(state="normal")
        self.debug_box.delete("1.0", "end")
        self.debug_box.insert("end", info.strip())
        self.debug_box.configure(state="disabled")


def run_gui():
    app = FedoApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()