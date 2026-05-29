import os
import threading
import subprocess
import psutil
try:
    import GPUtil
except ImportError:
    GPUtil = None
import customtkinter as ctk

from config import APP_NAME, APP_VERSION
from ai.llm_client import ask_llm, get_model_name, is_lm_studio_online, clear_chat_history
from core.commands import handle_command
from core.logger import log
from core.settings import load_settings, save_settings
from core.memory import load_memory, save_memory
from voice.tts import speak
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
    def __init__(self):
        super().__init__()

        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1050x720")
        self.minsize(900, 600)
        self.configure(fg_color=BG)

        self.settings = load_settings()
        self.dev_mode = self.settings.get("developer_mode", False)
        self.is_processing = False
        self.dev_clicks = 0
        self.secret_aggressive_unlocked = False

        if self.settings.get("personality_mode") == "Агрессивный":
            self.settings["personality_mode"] = "СССР"
            save_settings(self.settings)

        self.pages = {}
        self.tab_buttons = {}

        self._set_icon()
        self._build_layout()
        self._setup_hotkeys()
        self._setup_context_menu()
        self._build_tabs()
        self._build_chat_page()
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
            text=f"{APP_NAME} {APP_VERSION}",
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

        self.tabs_frame = ctk.CTkFrame(self, fg_color=BG)
        self.tabs_frame.pack(fill="x", padx=18, pady=(10, 8))

        self.content = ctk.CTkFrame(self, fg_color=BG)
        self.content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

    def _build_tabs(self):
        for name in ["Чат", "ПК", "Память", "Настройки"]:
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
        try:
            answer = handle_command(text)
            if not answer:
                answer = ask_llm(text)
        except Exception as e:
            answer = f"Ошибка обработки запроса: {e}"
            log(f"[GUI ERROR] {e}")

        self.after(0, lambda: self._response_ready(answer))

    def _response_ready(self, answer):
        self._chat_write(answer, "F.E.D.O")
        self._set_status("READY")
        self._update_ai_status()

        if self.settings.get("voice_enabled", True):
            threading.Thread(target=lambda: speak(str(answer)[:600]), daemon=True).start()

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
        self._chat_write("Платформа оператора F.E.D.O активна.", "SYSTEM")
        self._chat_write("Интерфейс v1.3 Stable GUI загружен.", "SYSTEM")
        self._update_ai_status()

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

        self.cpu_value = self._metric_card(grid, "CPU", 0, 0)
        self.ram_value = self._metric_card(grid, "RAM", 0, 1)
        self.gpu_value = self._metric_card(grid, "GPU / VRAM", 1, 0)
        self.disk_value = self._metric_card(grid, "DISK C:", 1, 1)
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
        def loop():
            while True:
                try:
                    cpu = psutil.cpu_percent(interval=1)
                    ram = psutil.virtual_memory()
                    disk = psutil.disk_usage("C:\\")
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

        self._section(box, "Режим личности")

        self.personality_mode = ctk.StringVar(
            value=self.settings.get("personality_mode", "СССР")
        )

        modes = [
            "СССР",
            "Джарвис",
            "Современный"
        ]

        if self.secret_aggressive_unlocked:
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
                try:
                    self._chat_write(
                        "Скрытый протокол личности обнаружен. Агрессивный режим разблокирован.",
                        "SYSTEM"
                    )
                except Exception:
                    pass

                self.secret_aggressive_unlocked = True

            self.settings["personality_mode"] = "Агрессивный"

            self._rebuild_settings_page()

            if hasattr(self, "personality_mode"):
                self.personality_mode.set("Агрессивный")

            self.show_page("Настройки")

    def _show_dev_warning(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Режим разработчика")
        dialog.geometry("460x300")
        dialog.configure(fg_color=BG)
        dialog.grab_set()
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

    def _save_settings(self):
        self.settings = {
            "ai_provider": self.ai_provider.get(),
            "gemini_api_key": self.gemini_key.get().strip(),
            "lm_studio_url": self.lm_url.get().strip(),
            "personality_mode": "СССР" if self.personality_mode.get() == "Агрессивный" else self.personality_mode.get(),
            "voice_enabled": self.voice_enabled.get(),
            "developer_mode": self.dev_mode
        }

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
        self.terminal_box.insert("end", "Введите команду Windows PowerShell/CMD ниже.\n\n")

        input_frame = ctk.CTkFrame(page, fg_color=PANEL, corner_radius=14, border_width=1, border_color=BORDER)
        input_frame.pack(fill="x")

        self.term_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="D:\\Projects\\Python\\F.E.D.O>",
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

        blocked = ["format", "shutdown", "del /f", "rmdir /s", "rd /s"]
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