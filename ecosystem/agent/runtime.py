"""Исполнение разрешённых команд агентом (с режимом симуляции)."""
from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable

from ..backend.services import core_bridge
from .wake import send_magic_packet


@dataclass
class AgentPolicy:
    """Разрешения, которые владелец выдаёт устройству явно."""

    allow_stats: bool = True
    allow_ai_control: bool = False
    allow_power: bool = False
    allow_wol: bool = False
    ai_start_command: list[str] = field(default_factory=list)
    ai_stop_command: list[str] = field(default_factory=list)
    ai_url: str = "http://127.0.0.1:1234/v1"
    simulate: bool = False


class AgentExecutor:
    def __init__(self, policy: AgentPolicy):
        self.policy = policy

    # ------------------------------------------------------------------ #
    def execute(self, action: str, params: dict | None = None) -> dict:
        from ..backend.services.device_service import validate_action

        try:
            spec, clean = validate_action(action, params)
        except ValueError as exc:
            # неизвестное действие/параметры: агент не падает и ничего не выполняет
            return {"ok": False, "error": str(exc), "denied": True}
        started = time.time()
        try:
            handler = getattr(self, f"_do_{spec.name}", None)
            if handler is None:
                return {"ok": False, "error": f"Действие {spec.name} не реализовано"}
            result = handler(clean)
            result.setdefault("simulated", self.policy.simulate)
            result["duration_ms"] = int((time.time() - started) * 1000)
            return result
        except PermissionError as exc:
            return {"ok": False, "error": str(exc), "denied": True}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------ #
    def _do_status(self, _params: dict) -> dict:
        snapshot = core_bridge.system_snapshot()
        return {
            "ok": True,
            "hostname": snapshot.get("hostname"),
            "platform": snapshot.get("platform"),
            "core_version": core_bridge.core_version(),
            "ai_reachable": self._ai_reachable(),
            "uptime_hint": snapshot.get("time"),
        }

    def _do_stats(self, _params: dict) -> dict:
        snapshot = core_bridge.system_snapshot()
        return {
            "ok": True,
            "cpu_percent": snapshot.get("cpu_percent"),
            "ram_percent": snapshot.get("ram_percent"),
            "disk_percent": snapshot.get("disk_percent"),
            "gpu": snapshot.get("gpu"),
            "cpu_temperature": snapshot.get("cpu_temperature"),
            "top_processes": (snapshot.get("top_processes") or [])[:5],
        }

    def _do_ai_check(self, _params: dict) -> dict:
        reachable = self._ai_reachable()
        return {"ok": True, "ai_available": reachable, "url": self.policy.ai_url}

    def _do_ai_start(self, _params: dict) -> dict:
        if not self.policy.allow_ai_control:
            raise PermissionError("Управление AI-сервисом не разрешено на этом устройстве")
        return self._run_allowed(self.policy.ai_start_command, "AI-сервис запускается")

    def _do_ai_stop(self, _params: dict) -> dict:
        if not self.policy.allow_ai_control:
            raise PermissionError("Управление AI-сервисом не разрешено на этом устройстве")
        return self._run_allowed(self.policy.ai_stop_command, "AI-сервис останавливается")

    def _do_sleep(self, _params: dict) -> dict:
        if not self.policy.allow_power:
            raise PermissionError("Управление питанием не разрешено на этом устройстве")
        if self.policy.simulate:
            return {"ok": True, "action": "sleep", "note": "симуляция"}
        system = platform.system().lower()
        if system == "windows":
            cmd = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
        elif shutil.which("systemctl"):
            cmd = ["systemctl", "suspend"]
        else:
            raise RuntimeError("Сон не поддерживается на этой платформе")
        subprocess.Popen(cmd, shell=False)  # noqa: S603 - команда из белого списка
        return {"ok": True, "action": "sleep", "platform": system}

    def _do_wol(self, params: dict) -> dict:
        if not self.policy.allow_wol:
            raise PermissionError("Wake-on-LAN не разрешён на этом устройстве")
        mac = params.get("mac", "")
        broadcast = params.get("broadcast", "255.255.255.255")
        if self.policy.simulate:
            return {"ok": True, "mac": mac, "broadcast": broadcast, "note": "симуляция"}
        sent = send_magic_packet(mac, broadcast)
        return {"ok": sent > 0, "mac": mac, "broadcast": broadcast, "bytes": sent}

    # ------------------------------------------------------------------ #
    def _ai_reachable(self) -> bool:
        import httpx

        url = self.policy.ai_url.rstrip("/")
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        if not url.endswith("/v1"):
            url += "/v1"
        try:
            resp = httpx.get(f"{url}/models", timeout=2.0)
            return resp.status_code == 200 and "data" in resp.json()
        except Exception:
            return False

    def _run_allowed(self, command: list[str], message: str) -> dict:
        if not command:
            raise PermissionError("Команда запуска сервиса не настроена владельцем")
        if self.policy.simulate:
            return {"ok": True, "message": message, "command": " ".join(command), "note": "симуляция"}
        process = subprocess.run(command, shell=False, capture_output=True, text=True, timeout=90)  # noqa: S603
        return {
            "ok": process.returncode == 0,
            "message": message,
            "returncode": process.returncode,
            "stdout": (process.stdout or "")[-500:],
            "stderr": (process.stderr or "")[-500:],
        }
