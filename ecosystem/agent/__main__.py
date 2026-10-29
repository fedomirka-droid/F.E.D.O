"""F.E.D.O. Agent — CLI.

Пример (домашний ПК с RTX 3080):
    python -m ecosystem.agent \
        --hub https://hub.example \
        --token dev_xxx --secret yyy \
        --name HomePC --kind gpu \
        --allow-ai-control --ai-start "lms server start" \
        --ai-url http://127.0.0.1:1234/v1 \
        --gateway-port 8790

Режим симуляции (без реальных действий):
    python -m ecosystem.agent --simulate --hub http://127.0.0.1:8765 --token dev_x --secret y
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from ..backend.config import default_data_dir
from .gateway import GatewayConfig, create_gateway
from .runtime import AgentExecutor, AgentPolicy

logger = logging.getLogger("fedo.agent")


def _credentials_path() -> Path:
    return default_data_dir() / "agent.json"


def load_saved() -> dict:
    path = _credentials_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_credentials(data: dict) -> None:
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class AgentRunner:
    def __init__(self, hub_url: str, token: str, name: str, kind: str,
                 executor: AgentExecutor, interval: int = 15, ai_endpoint: str = ""):
        self.hub_url = hub_url.rstrip("/")
        self.token = token
        self.name = name
        self.kind = kind
        self.executor = executor
        self.interval = interval
        self.ai_endpoint = ai_endpoint
        self.client = httpx.Client(timeout=15.0, headers={"X-Device-Token": token})

    def _metrics(self) -> dict:
        from ..backend.services import core_bridge

        snapshot = core_bridge.system_snapshot()
        return {
            "cpu_percent": snapshot.get("cpu_percent"),
            "ram_percent": snapshot.get("ram_percent"),
            "disk_percent": snapshot.get("disk_percent"),
            "gpu": snapshot.get("gpu"),
            "hostname": snapshot.get("hostname"),
            "ai_endpoint": self.ai_endpoint,  # адрес AI-шлюза для HUB (не локальный LM Studio)
        }

    def heartbeat(self) -> bool:
        payload = {
            "status": "online",
            "metrics": self._metrics(),
            "ai_available": self.executor._ai_reachable(),
            "platform": f"{platform.system()} {platform.release()}",
        }
        try:
            resp = self.client.post(f"{self.hub_url}/api/agent/heartbeat", json=payload)
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("heartbeat failed: %s", exc)
            return False

    def poll_once(self) -> int:
        try:
            resp = self.client.get(f"{self.hub_url}/api/agent/poll")
        except httpx.HTTPError as exc:
            logger.warning("poll failed: %s", exc)
            return 0
        if resp.status_code != 200:
            logger.warning("poll HTTP %s", resp.status_code)
            return 0
        executed = 0
        for command in resp.json().get("commands", []):
            result = self.executor.execute(command.get("action", ""), command.get("params") or {})
            executed += 1
            try:
                self.client.post(f"{self.hub_url}/api/agent/result",
                                 json={"command_id": command.get("command_id"),
                                       "ok": bool(result.get("ok")), "result": result})
            except httpx.HTTPError as exc:
                logger.warning("result report failed: %s", exc)
        return executed

    def run_forever(self) -> None:
        logger.info("agent %s connected to %s", self.name, self.hub_url)
        while True:
            self.heartbeat()
            self.poll_once()
            time.sleep(self.interval)


def pair_with_hub(hub_url: str, code: str, name: str, kind: str) -> dict:
    """Обменять одноразовый код на токен устройства (публичный эндпоинт HUB)."""
    import httpx

    url = hub_url.rstrip("/") + "/api/devices/pair"
    resp = httpx.post(url, json={"code": code.strip().upper(), "name": name,
                                 "kind": kind, "platform": platform.platform()[:120]},
                      timeout=20)
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text[:200]
        raise SystemExit(f"Привязка не удалась ({resp.status_code}): {detail}")
    return resp.json()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="F.E.D.O. Agent")
    saved = load_saved()
    parser.add_argument("--hub", default=os.environ.get("FEDO_HUB_URL", saved.get("hub_url", "")))
    parser.add_argument("--token", default=os.environ.get("FEDO_DEVICE_TOKEN", saved.get("token", "")))
    parser.add_argument("--secret", default=os.environ.get("FEDO_CHANNEL_SECRET", saved.get("channel_secret", "")))
    parser.add_argument("--name", default=saved.get("name", platform.node() or "Device"))
    parser.add_argument("--device-id", default=os.environ.get("FEDO_DEVICE_ID", saved.get("device_id", "")),
                        help="ID устройства на HUB (из ответа при регистрации)")
    parser.add_argument("--kind", default=saved.get("kind", "desktop"),
                        choices=["desktop", "gpu", "hub", "controller"])
    parser.add_argument("--simulate", action="store_true", help="ничего реально не выполнять")
    parser.add_argument("--allow-power", action="store_true", help="разрешить сон и выключение")
    parser.add_argument("--allow-lock", action="store_true", help="разрешить блокировку экрана")
    parser.add_argument("--allow-ai-control", action="store_true", help="разрешить запуск/останов AI")
    parser.add_argument("--allow-wol", action="store_true", help="разрешить отправку WoL")
    parser.add_argument("--allow-app", action="append", default=[], metavar="МЕТКА=ПУТЬ",
                        help="разрешить приложение (можно несколько раз), напр. "
                             '"Браузер=C:\\Program Files\\Chrome\\chrome.exe"')
    parser.add_argument("--pair-code", default=os.environ.get("FEDO_PAIR_CODE", ""),
                        help="одноразовый код привязки из Desktop → Устройства")
    parser.add_argument("--ai-url", default=os.environ.get("FEDO_AI_URL", "http://127.0.0.1:1234/v1"))
    parser.add_argument("--ai-start", default="", help='команда запуска AI, например "lms server start"')
    parser.add_argument("--ai-stop", default="", help="команда остановки AI")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--gateway-port", type=int, default=0,
                        help="порт AI-шлюза (0 — не запускать)")
    parser.add_argument("--gateway-host", default="0.0.0.0")
    parser.add_argument("--ai-endpoint", default=os.environ.get("FEDO_AI_ENDPOINT", ""),
                        help="внешний адрес AI-шлюза, который увидит HUB")
    parser.add_argument("--save", action="store_true", help="сохранить hub/token/secret в файл 0600")
    parser.add_argument("--once", action="store_true", help="один цикл и выход (диагностика)")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args()
    if args.pair_code:
        # Привязка по одноразовому коду: устройство само получает токен и секрет.
        if not args.hub:
            raise SystemExit("Для --pair-code нужен --hub")
        paired = pair_with_hub(args.hub, args.pair_code, args.name, args.kind)
        args.token = paired["token"]
        args.secret = paired["channel_secret"]
        args.device_id = paired["device"]["id"]
        logger.info("device paired: %s (%s)", paired["device"]["name"], args.device_id)
    if not args.hub or not args.token:
        raise SystemExit("Нужны --hub и --token (Desktop → Устройства) "
                         "либо --pair-code для привязки по коду")

    apps: dict[str, list[str]] = {}
    for entry in args.allow_app:
        label, _, command = entry.partition("=")
        label, command = label.strip(), command.strip()
        if not label or not command:
            raise SystemExit(f"Некорректный --allow-app: {entry!r} (нужно МЕТКА=ПУТЬ)")
        apps[label] = [command]

    policy = AgentPolicy(
        simulate=args.simulate,
        allow_power=args.allow_power,
        allow_lock=args.allow_lock,
        allow_ai_control=args.allow_ai_control,
        allow_wol=args.allow_wol,
        allow_apps=bool(apps),
        apps=apps,
        ai_url=args.ai_url,
        ai_start_command=args.ai_start.split() if args.ai_start else [],
        ai_stop_command=args.ai_stop.split() if args.ai_stop else [],
    )
    executor = AgentExecutor(policy)
    if args.save:
        save_credentials({"hub_url": args.hub, "token": args.token,
                          "channel_secret": args.secret, "name": args.name,
                          "kind": args.kind, "device_id": args.device_id})
        logger.info("credentials saved to %s", _credentials_path())

    if args.gateway_port and args.secret:
        if not args.device_id:
            raise SystemExit("Для AI-шлюза нужен --device-id (ID устройства на HUB)")
        config = GatewayConfig(device_id=args.device_id, channel_secret=args.secret,
                               ai_url=args.ai_url)
        gateway = create_gateway(config)
        threading.Thread(
            target=lambda: uvicorn.run(gateway, host=args.gateway_host, port=args.gateway_port,
                                       log_level="info"),
            name="fedo-ai-gateway", daemon=True,
        ).start()
        logger.info("AI gateway on %s:%s", args.gateway_host, args.gateway_port)

    endpoint = args.ai_endpoint
    if not endpoint and args.gateway_port:
        endpoint = f"http://{platform.node()}:{args.gateway_port}"
    runner = AgentRunner(args.hub, args.token, args.name, args.kind, executor,
                         args.interval, ai_endpoint=endpoint)
    if args.once:
        logger.info("heartbeat: %s", runner.heartbeat())
        logger.info("commands executed: %s", runner.poll_once())
        return
    runner.run_forever()


if __name__ == "__main__":
    main()
