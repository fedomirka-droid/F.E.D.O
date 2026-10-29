"""AI Router 2.0 — маршрутизация, приватность, лимиты, отмена.

Режимы:
  local_only      — только своё железо (локальная модель / домашний узел);
  hybrid          — локальная по умолчанию, облако только как fallback и только
                    при явно разрешённом облаке;
  cloud_preferred — облако первым, локальная как резерв;
  manual          — строго выбранная модель, без автоподбора.

Жёсткие правила:
  * allow_cloud = False → облако запрещено полностью (никакой fallback его не обходит);
  * allow_history_to_cloud = False → в облако уходит только текущий запрос;
  * лимиты (запросы/день, бюджет/месяц) проверяются ПЕРЕД каждым облачным запросом;
  * ключи никогда не пишутся в лог (redact на каждом логируемом тексте).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, AsyncIterator

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import iso, utcnow
from ..models import AiSettings, AiUsage, Device, ProviderKey
from ..providers.base import Cancelled, ChatMessage, ChatRequest, ChatResponse, ProviderError
from ..providers.gemini import GeminiProvider
from ..providers.local_lmstudio import LocalLMStudioProvider
from ..providers.openai_compat import OpenAICompatibleProvider
from ..providers.remote_node import RemoteNodeProvider
from ..security import SecretBox, redact
from . import core_bridge

CLOUD_MODELS = {
    "gemini": ["gemini-2.0-flash", "gemini-1.5-pro"],
    "openai": ["gpt-4o-mini", "gpt-4o"],
}

MODE_LABELS = {
    "local_only": "Local Only",
    "hybrid": "Hybrid",
    "cloud_preferred": "Cloud Preferred",
    "manual": "Manual",
}


@dataclass
class RouteStep:
    provider: str
    model: str
    outcome: str  # ok | failed | blocked | skipped
    reason: str = ""
    cloud: bool = False

    def as_dict(self) -> dict:
        return {"provider": self.provider, "model": self.model, "outcome": self.outcome,
                "reason": self.reason, "cloud": self.cloud}


@dataclass
class RouteResult:
    text: str
    provider: str = ""
    model: str = ""
    cloud: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    trace: list[dict] = field(default_factory=list)
    request_id: str = ""
    cached: bool = False

    def as_dict(self) -> dict:
        return {
            "text": self.text, "provider": self.provider, "model": self.model,
            "cloud": self.cloud, "usage": {"prompt_tokens": self.prompt_tokens,
                                           "completion_tokens": self.completion_tokens,
                                           "cost": round(self.cost, 6)},
            "trace": self.trace, "request_id": self.request_id,
        }


class AiRouter:
    def __init__(self, db: Session, settings: Settings, box: SecretBox,
                 client_factory=None, guard: Any = None,
                 cancel_registry: dict | None = None):
        self.db = db
        self.settings = settings
        self.box = box
        self._client_factory = client_factory
        # реестр отмен общий на процесс (живёт в app.state)
        self._cancel: dict[str, asyncio.Event] = cancel_registry if cancel_registry is not None else {}
        self.guard = guard  # необязательный колбэк для внешнего аудита

    # ------------------------------------------------------------------ #
    # Настройки владельца
    # ------------------------------------------------------------------ #
    def ai_settings(self, owner_id: str) -> AiSettings:
        row = self.db.get(AiSettings, owner_id)
        if row is None:
            row = AiSettings(owner_id=owner_id)
            self.db.add(row)
            self.db.flush()
        return row

    def _key(self, owner_id: str, provider: str) -> str:
        row = self.db.execute(
            select(ProviderKey).where(ProviderKey.owner_id == owner_id,
                                      ProviderKey.provider == provider)
        ).scalar_one_or_none()
        if row is None:
            return ""
        return self.box.decrypt(row.encrypted_key)

    def _client(self, timeout: float) -> httpx.AsyncClient:
        if self._client_factory:
            return self._client_factory(timeout)
        return httpx.AsyncClient(timeout=timeout)

    # ------------------------------------------------------------------ #
    # Провайдеры
    # ------------------------------------------------------------------ #
    def local_provider(self, ai: AiSettings, timeout: float | None = None,
                       client: httpx.AsyncClient | None = None) -> LocalLMStudioProvider:
        return LocalLMStudioProvider(
            base_url=self.settings.local_ai_url,
            model=ai.local_model,
            client=client,
            timeout=timeout or self.settings.ai_request_timeout,
        )

    def cloud_provider(self, owner_id: str, ai: AiSettings, client: httpx.AsyncClient | None = None):
        provider = ai.cloud_provider or "gemini"
        key = self._key(owner_id, provider)
        model = ai.manual_model if ai.mode == "manual" and ai.manual_model else ""
        if provider == "gemini":
            return GeminiProvider(api_key=key, model=model or "gemini-2.0-flash", client=client)
        base = self._key(owner_id, "openai_base_url") or "https://api.openai.com/v1"
        return OpenAICompatibleProvider(name=provider, base_url=base, api_key=key,
                                        model=model or "gpt-4o-mini", client=client)

    def remote_node(self, owner_id: str, client: httpx.AsyncClient | None = None) -> RemoteNodeProvider | None:
        """AI-узел домашнего ПК: устройство с capability 'ai' и адресом в metrics."""
        devices = self.db.execute(
            select(Device).where(Device.owner_id == owner_id, Device.revoked_at.is_(None))
        ).scalars().all()
        for device in devices:
            caps = device.capabilities or []
            endpoint = (device.metrics or {}).get("ai_endpoint")
            if "ai" in caps and endpoint:
                secret = self.box.decrypt(device.channel_secret_enc or "")
                if secret:
                    return RemoteNodeProvider(node_url=endpoint, device_id=device.id,
                                              channel_secret=secret, client=client,
                                              timeout=self.settings.ai_request_timeout)
        return None

    async def models(self, owner_id: str) -> dict:
        ai = self.ai_settings(owner_id)
        client = self._client(5.0)
        try:
            local = self.local_provider(ai, client=client)
            local_models = await local.list_models()
        finally:
            await client.aclose()
        node = self.remote_node(owner_id)
        node_ok = await node.available() if node else False
        cloud_key = self._key(owner_id, ai.cloud_provider or "gemini")
        return {
            "mode": ai.mode,
            "modes": list(MODE_LABELS.keys()),
            "allow_cloud": ai.allow_cloud,
            "allow_history_to_cloud": ai.allow_history_to_cloud,
            "allow_remote_node": ai.allow_remote_node,
            "local": {"available": bool(local_models), "models": local_models,
                      "selected": ai.local_model or (local_models[0] if local_models else "")},
            "cloud": {"provider": ai.cloud_provider, "configured": bool(cloud_key),
                      "models": CLOUD_MODELS.get(ai.cloud_provider, []),
                      "allowed": bool(ai.allow_cloud)},
            "remote_node": {"available": node_ok,
                            "models": [node.model or "home-node"] if node else []},
            "privacy": "cloud_allowed" if ai.allow_cloud else "local_only_enforced",
        }

    async def health(self, owner_id: str) -> dict:
        """Быстрый health-check провайдеров: без утечки ключей и без запросов к облаку."""
        ai = self.ai_settings(owner_id)
        client = self._client(3.0)
        local_ok, local_models, local_error = False, [], ""
        try:
            local = self.local_provider(ai, client=client)
            local_models = await local.list_models()
            local_ok = bool(local_models)
        except Exception as exc:  # провайдер недоступен — это штатная ситуация
            local_error = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            await client.aclose()

        node = self.remote_node(owner_id)
        node_ok = False
        if node is not None:
            try:
                node_ok = await node.available()
            except Exception:
                node_ok = False

        cloud_key = bool(self._key(owner_id, ai.cloud_provider or "gemini"))
        allowed, reason = self.cloud_limits(owner_id, ai)
        plan = self._plan(owner_id, ai, ai.mode or "hybrid")
        return {
            "mode": ai.mode,
            "local": {"available": local_ok, "models": local_models[:10],
                      "selected": ai.local_model, "error": local_error},
            "remote_node": {"configured": node is not None, "available": node_ok},
            "cloud": {"provider": ai.cloud_provider, "key_configured": cloud_key,
                      "allowed": bool(ai.allow_cloud), "usable": allowed,
                      "reason": reason},
            "fallback_plan": [{"kind": kind, "label": label, "cloud": cloud}
                              for kind, label, cloud in plan],
            "can_answer": bool(plan),
            "privacy": "cloud_allowed" if ai.allow_cloud else "local_only_enforced",
        }

    # ------------------------------------------------------------------ #
    # Лимиты
    # ------------------------------------------------------------------ #
    def cloud_limits(self, owner_id: str, ai: AiSettings) -> tuple[bool, str]:
        if not ai.allow_cloud:
            return False, "облако запрещено настройками приватности"
        day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        daily = self.db.execute(
            select(func.count(AiUsage.id)).where(
                AiUsage.owner_id == owner_id, AiUsage.cloud.is_(True), AiUsage.created_at >= day_start
            )
        ).scalar() or 0
        if ai.daily_request_limit and daily >= ai.daily_request_limit:
            return False, f"дневной лимит облачных запросов исчерпан ({daily}/{ai.daily_request_limit})"
        spent = self.db.execute(
            select(func.coalesce(func.sum(AiUsage.cost), 0.0)).where(
                AiUsage.owner_id == owner_id, AiUsage.cloud.is_(True), AiUsage.created_at >= month_start
            )
        ).scalar() or 0.0
        if ai.monthly_budget and float(spent) >= float(ai.monthly_budget):
            return False, (f"месячный бюджет исчерпан ({float(spent):.4f}/"
                           f"{float(ai.monthly_budget):.2f})")
        return True, ""

    def usage_summary(self, owner_id: str) -> dict:
        day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        rows = self.db.execute(
            select(AiUsage).where(AiUsage.owner_id == owner_id, AiUsage.created_at >= month_start)
        ).scalars().all()
        today = [r for r in rows if r.created_at >= day_start]
        ai = self.ai_settings(owner_id)
        allowed, reason = self.cloud_limits(owner_id, ai)
        return {
            "today_requests": len(today),
            "today_cloud_requests": sum(1 for r in today if r.cloud),
            "month_requests": len(rows),
            "month_tokens": sum(r.prompt_tokens + r.completion_tokens for r in rows),
            "month_cost": round(sum(r.cost for r in rows), 6),
            "daily_request_limit": ai.daily_request_limit,
            "monthly_budget": ai.monthly_budget,
            "cloud_allowed_now": allowed,
            "cloud_block_reason": reason,
        }

    def _record_usage(self, owner_id: str, response: ChatResponse, cloud: bool,
                      request_id: str, device_id: str = "") -> None:
        self.db.add(AiUsage(
            owner_id=owner_id, provider=response.provider, model=response.model,
            prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
            cost=response.cost, cloud=cloud, request_id=request_id, device_id=device_id,
        ))
        self.db.flush()

    # ------------------------------------------------------------------ #
    # Планирование маршрута
    # ------------------------------------------------------------------ #
    def _plan(self, owner_id: str, ai: AiSettings, mode: str, model_hint: str = ""):
        """Список кандидатов: [(kind, label, cloud)] в порядке приоритета."""
        allow_node = ai.allow_remote_node
        cloud_ok, cloud_reason = self.cloud_limits(owner_id, ai)
        plan: list[tuple[str, str, bool]] = []

        def add_cloud():
            # кандидат добавляется всегда; фактическая проверка приватности и
            # лимитов — перед каждым облачным запросом (см. chat/stream)
            plan.append(("cloud", ai.cloud_provider or "gemini", True))

        if mode == "local_only":
            plan.append(("local", "local", False))
            if allow_node:
                plan.append(("remote_node", "home-node", False))
        elif mode == "cloud_preferred":
            add_cloud()
            plan.append(("local", "local", False))
            if allow_node:
                plan.append(("remote_node", "home-node", False))
        elif mode == "manual":
            target = model_hint or ai.manual_model or ai.local_model
            if target and (target in sum(CLOUD_MODELS.values(), []) or "/" in target and "gemini" in target):
                add_cloud()
            elif target == "home-node" and allow_node:
                plan.append(("remote_node", target, False))
            else:
                plan.append(("local", target or "local", False))
        else:  # hybrid
            plan.append(("local", "local", False))
            if allow_node:
                plan.append(("remote_node", "home-node", False))
            add_cloud()
        # при запрещённом облаке облачных кандидатов в плане нет вовсе
        self._plan_note = "" if cloud_ok else cloud_reason
        return plan

    def _provider_for(self, kind: str, owner_id: str, ai: AiSettings, client, model_hint: str = ""):
        if kind == "local":
            provider = self.local_provider(ai, client=client)
            if model_hint and model_hint not in ("local", "auto"):
                provider.model = model_hint
            return provider, False
        if kind == "remote_node":
            node = self.remote_node(owner_id, client=client)
            return node, False
        return self.cloud_provider(owner_id, ai, client=client), True

    def _messages(self, ai: AiSettings, message: str, history: list[dict] | None,
                  cloud: bool) -> list[ChatMessage]:
        msgs: list[ChatMessage] = []
        if history and (not cloud or ai.allow_history_to_cloud):
            for item in history[-12:]:
                role = item.get("role", "user")
                if role not in ("user", "assistant"):
                    continue
                content = str(item.get("content", ""))[:4000]
                if content:
                    msgs.append(ChatMessage(role=role, content=content))
        msgs.append(ChatMessage(role="user", content=message))
        return msgs

    # ------------------------------------------------------------------ #
    # Основной вызов
    # ------------------------------------------------------------------ #
    async def chat(self, owner_id: str, message: str, history: list[dict] | None = None,
                   mode: str | None = None, model: str | None = None,
                   request_id: str = "", use_core_commands: bool = True,
                   device_id: str = "") -> RouteResult:
        ai = self.ai_settings(owner_id)
        effective_mode = mode or ai.mode or "hybrid"
        if effective_mode not in MODE_LABELS:
            effective_mode = "hybrid"
        trace: list[dict] = []

        # 0) Локальные команды Core (без сети, без токенов)
        if use_core_commands:
            answer = core_bridge.core_local_route(message)
            if answer:
                trace.append({"provider": "core", "model": "local-commands",
                              "outcome": "ok", "reason": "локальная команда Core", "cloud": False})
                return RouteResult(text=answer, provider="core", model="local-commands",
                                   trace=trace, request_id=request_id)

        plan = self._plan(owner_id, ai, effective_mode, model or "")
        if not plan:
            return RouteResult(text="Нет доступных AI-провайдеров: проверь настройки.",
                               trace=[{"provider": "-", "model": "-", "outcome": "blocked",
                                       "reason": "пустой план", "cloud": False}],
                               request_id=request_id)
        cancel_event = self._cancel.setdefault(request_id, asyncio.Event()) if request_id else None

        for kind, label, cloud in plan:
            if cancel_event and cancel_event.is_set():
                trace.append({"provider": kind, "model": label, "outcome": "blocked",
                              "reason": "запрос отменён", "cloud": cloud})
                return RouteResult(text="Запрос отменён.", trace=trace,
                                   request_id=request_id)
            if cloud:
                ok, reason = self.cloud_limits(owner_id, ai)
                if not ok:
                    trace.append({"provider": label, "model": label, "outcome": "blocked",
                                  "reason": reason, "cloud": True})
                    continue
            timeout = self.settings.ai_request_timeout
            client = self._client(timeout)
            provider, is_cloud = self._provider_for(kind, owner_id, ai, client, model or "")
            if provider is None:
                trace.append({"provider": kind, "model": label, "outcome": "skipped",
                              "reason": "домашний узел не подключён", "cloud": False})
                await client.aclose()
                continue
            request = ChatRequest(
                messages=self._messages(ai, message, history, is_cloud),
                system=core_bridge.build_system_prompt(response_language="auto"),
                temperature=ai.temperature or 0.6,
                max_tokens=800,
            )
            try:
                if cancel_event and cancel_event.is_set():
                    raise Cancelled()
                response = await provider.chat(request)
                if cancel_event and cancel_event.is_set():
                    raise Cancelled()
                if is_cloud:
                    self._record_usage(owner_id, response, True, request_id, device_id)
                else:
                    self._record_usage(owner_id, response, False, request_id, device_id)
                trace.append({"provider": response.provider, "model": response.model,
                              "outcome": "ok", "reason": "", "cloud": is_cloud})
                return RouteResult(
                    text=response.text, provider=response.provider, model=response.model,
                    cloud=is_cloud, prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens, cost=response.cost,
                    trace=trace, request_id=request_id,
                )
            except Cancelled:
                trace.append({"provider": kind, "model": label, "outcome": "blocked",
                              "reason": "запрос отменён", "cloud": is_cloud})
                return RouteResult(text="Запрос отменён.", trace=trace, request_id=request_id)
            except ProviderError as exc:
                trace.append({"provider": kind, "model": label, "outcome": "failed",
                              "reason": redact(str(exc))[:200], "cloud": is_cloud})
            except Exception as exc:  # непредвиденная ошибка провайдера
                trace.append({"provider": kind, "model": label, "outcome": "failed",
                              "reason": redact(f"{type(exc).__name__}: {exc}")[:200],
                              "cloud": is_cloud})
            finally:
                await client.aclose()

        hint = "Облако запрещено настройками." if not ai.allow_cloud else "Проверь доступность моделей."
        return RouteResult(
            text=f"AI недоступен: все провайдеры не ответили. {hint}",
            trace=trace, request_id=request_id,
        )

    # ------------------------------------------------------------------ #
    # Стриминг
    # ------------------------------------------------------------------ #
    async def stream(self, owner_id: str, message: str, history: list[dict] | None = None,
                     mode: str | None = None, model: str | None = None,
                     request_id: str = "") -> AsyncIterator[dict]:
        ai = self.ai_settings(owner_id)
        effective_mode = mode or ai.mode or "hybrid"
        cancel_event = self._cancel.setdefault(request_id, asyncio.Event()) if request_id else None
        plan = self._plan(owner_id, ai, effective_mode, model or "")
        trace: list[dict] = []
        yield {"type": "start", "mode": effective_mode, "plan": [c[0] for c in plan],
               "plan_note": getattr(self, "_plan_note", "")}

        for kind, label, cloud in plan:
            if cancel_event and cancel_event.is_set():
                yield {"type": "cancelled", "trace": trace}
                return
            if cloud:
                ok, reason = self.cloud_limits(owner_id, ai)
                if not ok:
                    trace.append({"provider": label, "model": label, "outcome": "blocked",
                                  "reason": reason, "cloud": True})
                    continue
            client = self._client(self.settings.ai_request_timeout)
            provider, is_cloud = self._provider_for(kind, owner_id, ai, client, model or "")
            if provider is None:
                await client.aclose()
                trace.append({"provider": kind, "model": label, "outcome": "skipped",
                              "reason": "домашний узел не подключён", "cloud": False})
                continue
            request = ChatRequest(
                messages=self._messages(ai, message, history, is_cloud),
                system=core_bridge.build_system_prompt(response_language="auto"),
                temperature=ai.temperature or 0.6, max_tokens=800, stream=True,
            )
            collected: list[str] = []
            yield {"type": "route", "provider": kind, "model": label, "cloud": is_cloud}
            try:
                async for chunk in provider.stream(request):
                    if cancel_event and cancel_event.is_set():
                        yield {"type": "cancelled", "trace": trace, "text": "".join(collected)}
                        return
                    collected.append(chunk)
                    yield {"type": "chunk", "text": chunk}
                text = "".join(collected)
                if not text:
                    raise ProviderError("пустой ответ модели")
                usage = ChatResponse(text=text, provider=kind, model=label)
                self._record_usage(owner_id, usage, is_cloud, request_id)
                trace.append({"provider": kind, "model": label, "outcome": "ok",
                              "reason": "", "cloud": is_cloud})
                yield {"type": "done", "text": text, "provider": kind, "model": label,
                       "cloud": is_cloud, "trace": trace}
                return
            except ProviderError as exc:
                trace.append({"provider": kind, "model": label, "outcome": "failed",
                              "reason": redact(str(exc))[:200], "cloud": is_cloud})
                continue
            finally:
                await client.aclose()

        yield {"type": "error", "message": "AI недоступен: ни один провайдер не ответил.",
               "trace": trace}

    # ------------------------------------------------------------------ #
    # Отмена
    # ------------------------------------------------------------------ #
    def cancel(self, request_id: str) -> bool:
        event = self._cancel.get(request_id)
        if event is None:
            return False
        event.set()
        return True

    def finish(self, request_id: str) -> None:
        self._cancel.pop(request_id, None)
