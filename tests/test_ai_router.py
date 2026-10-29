"""Проверки 9–13: AI Router 2.0 — локально, отказ, fallback, приватность, лимиты, отмена."""
from __future__ import annotations

import httpx
import pytest

from ecosystem.backend.models import AiUsage, ProviderKey
from ecosystem.backend.security import SecretBox
from ecosystem.backend.services.ai_router import AiRouter
from tests.conftest import gemini_chat, local_models, make_mock_client, openai_chat

GEMINI_PATH = "/v1beta/models/gemini-2.0-flash:generateContent"


def _router(harness, routes, calls, fail_on=(), session=None):
    factory = make_mock_client(routes, calls, fail_on)
    return AiRouter(session or harness.db.session_factory(), harness.settings,
                    SecretBox(harness.settings.secret_key), client_factory=factory)


@pytest.fixture
def ai(harness):
    """Владелец + настройки AI + подключённый (фиктивный) Gemini-ключ."""
    box = SecretBox(harness.settings.secret_key)
    with harness.db.session() as db:
        db.add(ProviderKey(owner_id=harness.owner_id, provider="gemini",
                           encrypted_key=box.encrypt("AIzaFAKE-KEY-FOR-TESTS-123456")))
    return harness


def _settings(router: AiRouter, owner_id: str, **kwargs):
    ai = router.ai_settings(owner_id)
    for key, value in kwargs.items():
        setattr(ai, key, value)
    router.db.flush()
    return ai


async def test_local_answer_without_cloud(ai):
    calls: list = []
    routes = {("GET", "/v1/models"): {"json": local_models()},
              ("POST", "/v1/chat/completions"): {"json": openai_chat("Привет, товарищ")}}
    router = _router(ai, routes, calls)
    result = await router.chat(ai.owner_id, "привет", mode="local_only", use_core_commands=False)
    assert result.text == "Привет, товарищ"
    assert result.provider == "local" and result.cloud is False
    assert all("generativelanguage" not in str(c[1]) for c in calls)
    usage = router.usage_summary(ai.owner_id)
    assert usage["month_requests"] == 1 and usage["month_cost"] == 0.0


async def test_local_failure_never_falls_back_to_cloud_when_forbidden(ai):
    calls: list = []
    routes = {GEMINI_PATH: {"json": gemini_chat()}}
    router = _router(ai, routes, calls, fail_on=("/v1/chat/completions", "/v1/models"))
    _settings(router, ai.owner_id, mode="cloud_preferred", allow_cloud=False)
    result = await router.chat(ai.owner_id, "привет", use_core_commands=False)
    assert result.cloud is False
    assert result.text.startswith("AI недоступен")
    assert not any("generativelanguage" in str(c[1]) for c in calls)
    assert any(step["outcome"] == "failed" for step in result.trace)


async def test_hybrid_falls_back_to_cloud_when_allowed(ai):
    calls: list = []
    routes = {GEMINI_PATH: {"json": gemini_chat("Облако на связи")}}
    router = _router(ai, routes, calls, fail_on=("/v1/chat/completions", "/v1/models"))
    _settings(router, ai.owner_id, mode="hybrid", allow_cloud=True, cloud_provider="gemini")
    result = await router.chat(ai.owner_id, "сложный вопрос", use_core_commands=False)
    assert result.text == "Облако на связи"
    assert result.cloud is True and result.provider == "gemini"
    cloud_calls = [c for c in calls if "generativelanguage" in str(c[1])]
    assert len(cloud_calls) == 1
    # ключ ушёл только в заголовке
    headers = {k.lower(): v for k, v in cloud_calls[0][2].items()}
    assert headers.get("x-goog-api-key") == "AIzaFAKE-KEY-FOR-TESTS-123456"
    assert "AIzaFAKE" not in str(cloud_calls[0][1])
    usage = router.usage_summary(ai.owner_id)
    assert usage["today_cloud_requests"] == 1 and usage["month_cost"] > 0


async def test_history_not_sent_to_cloud_without_permission(ai):
    calls: list = []
    routes = {GEMINI_PATH: {"json": gemini_chat()}}
    router = _router(ai, routes, calls, fail_on=("/v1/chat/completions", "/v1/models"))
    _settings(router, ai.owner_id, mode="cloud_preferred", allow_cloud=True,
              allow_history_to_cloud=False, cloud_provider="gemini")
    history = [{"role": "user", "content": "МОЙ СЕКРЕТ ИЗ ЛОКАЛЬНОГО ЧАТА"},
               {"role": "assistant", "content": "записал"}]
    await router.chat(ai.owner_id, "новый вопрос", history=history, use_core_commands=False)
    body = calls[-1][3].decode()
    assert "МОЙ СЕКРЕТ" not in body
    assert "новый вопрос" in body


async def test_history_sent_when_explicitly_allowed(ai):
    calls: list = []
    routes = {GEMINI_PATH: {"json": gemini_chat()}}
    router = _router(ai, routes, calls, fail_on=("/v1/chat/completions", "/v1/models"))
    _settings(router, ai.owner_id, mode="cloud_preferred", allow_cloud=True,
              allow_history_to_cloud=True, cloud_provider="gemini")
    history = [{"role": "user", "content": "контекст разрешён"}]
    await router.chat(ai.owner_id, "новый вопрос", history=history, use_core_commands=False)
    assert "контекст разрешён" in calls[-1][3].decode()


async def test_daily_limit_blocks_cloud_and_falls_back_locally(ai):
    calls: list = []
    with ai.db.session() as db:
        db.add(AiUsage(owner_id=ai.owner_id, provider="gemini", model="gemini-2.0-flash",
                       prompt_tokens=10, completion_tokens=5, cost=0.01, cloud=True))
    routes = {GEMINI_PATH: {"json": gemini_chat()}}
    router = _router(ai, routes, calls, fail_on=("/v1/chat/completions", "/v1/models"))
    _settings(router, ai.owner_id, mode="hybrid", allow_cloud=True, daily_request_limit=1)
    result = await router.chat(ai.owner_id, "вопрос", use_core_commands=False)
    assert result.text.startswith("AI недоступен")
    assert any(step["outcome"] == "blocked" and "лимит" in step["reason"] for step in result.trace)
    assert not any("generativelanguage" in str(c[1]) for c in calls)


async def test_healthy_local_never_touches_cloud(ai):
    """Hybrid: если локальная модель жива — облако не вызывается вовсе."""
    calls: list = []
    routes = {("GET", "/v1/models"): {"json": local_models()},
              ("POST", "/v1/chat/completions"): {"json": openai_chat("локально")},
              GEMINI_PATH: {"json": gemini_chat()}}
    router = _router(ai, routes, calls)
    _settings(router, ai.owner_id, mode="hybrid", allow_cloud=True)
    result = await router.chat(ai.owner_id, "вопрос", use_core_commands=False)
    assert result.provider == "local"
    assert not any("generativelanguage" in str(c[1]) for c in calls)


async def test_monthly_budget_blocks_cloud(ai):
    calls: list = []
    with ai.db.session() as db:
        db.add(AiUsage(owner_id=ai.owner_id, provider="gemini", model="gemini-2.0-flash",
                       prompt_tokens=10, completion_tokens=5, cost=5.0, cloud=True))
    routes = {GEMINI_PATH: {"json": gemini_chat()}}
    router = _router(ai, routes, calls, fail_on=("/v1/chat/completions", "/v1/models"))
    _settings(router, ai.owner_id, mode="cloud_preferred", allow_cloud=True, monthly_budget=2.0)
    result = await router.chat(ai.owner_id, "вопрос", use_core_commands=False)
    assert result.cloud is False
    assert any("бюджет" in step["reason"] for step in result.trace)
    assert not any("generativelanguage" in str(c[1]) for c in calls)


async def test_cloud_unavailable_returns_error_and_keeps_counters(ai):
    calls: list = []
    router = _router(ai, {}, calls, fail_on=("/v1/chat/completions", "/v1/models", GEMINI_PATH))
    _settings(router, ai.owner_id, mode="hybrid", allow_cloud=True)
    result = await router.chat(ai.owner_id, "вопрос", use_core_commands=False)
    assert result.text.startswith("AI недоступен")
    assert len(result.trace) >= 2
    assert router.usage_summary(ai.owner_id)["month_requests"] == 0


async def test_cancel_stops_request(ai):
    calls: list = []
    routes = {("GET", "/v1/models"): {"json": local_models()},
              ("POST", "/v1/chat/completions"): {"json": openai_chat()}}
    router = _router(ai, routes, calls)
    router.cancel("req-1")  # регистрации ещё нет — False
    event = router._cancel.setdefault("req-1", __import__("asyncio").Event())
    event.set()
    result = await router.chat(ai.owner_id, "стоп", mode="local_only",
                               request_id="req-1", use_core_commands=False)
    assert result.text == "Запрос отменён."
    assert calls == []


async def test_streaming_local_chunks(ai):
    sse = ('data: {"choices":[{"delta":{"content":"При"}}]}\n\n'
           'data: {"choices":[{"delta":{"content":"вет"}}]}\n\n'
           'data: [DONE]\n\n')
    calls: list = []
    routes = {("GET", "/v1/models"): {"json": local_models()},
              ("POST", "/v1/chat/completions"): {"text": sse}}
    router = _router(ai, routes, calls)
    _settings(router, ai.owner_id, mode="local_only", allow_cloud=False)
    chunks, done = [], False
    async for event in router.stream(ai.owner_id, "привет", request_id="s1"):
        if event["type"] == "chunk":
            chunks.append(event["text"])
        if event["type"] == "done":
            done = True
    assert "".join(chunks) == "Привет"
    assert done is True


async def test_models_endpoint_reports_privacy(ai):
    calls: list = []
    routes = {("GET", "/v1/models"): {"json": local_models("qwen2.5-7b")}}
    router = _router(ai, routes, calls)
    _settings(router, ai.owner_id, allow_cloud=False)
    data = await router.models(ai.owner_id)
    assert data["local"]["available"] is True
    assert data["local"]["models"] == ["qwen2.5-7b"]
    assert data["cloud"]["allowed"] is False
    assert data["privacy"] == "local_only_enforced"


def test_api_key_stored_encrypted_and_not_returned(harness):
    resp = harness.client.post("/api/ai/keys/gemini", headers=harness.headers,
                                json={"api_key": "AIzaSUPERSECRETKEY123456"})
    assert resp.status_code == 200
    with harness.db.session() as db:
        row = db.query(ProviderKey).first()
        assert "SUPERSECRET" not in row.encrypted_key
    listed = harness.client.get("/api/ai/keys", headers=harness.headers).json()
    assert listed == {"configured": ["gemini"]}


def test_redact_hides_secrets():
    from ecosystem.backend.security import redact

    text = 'api_key="AIzaABCDEFGHIJKLMNOPQRSTUV" Authorization: Bearer sk-1234567890abcdefgh'
    masked = redact(text)
    assert "AIzaABCDEFGHIJKLMNOPQRSTUV" not in masked
    assert "sk-1234567890abcdefgh" not in masked


async def test_core_commands_answered_without_network(ai):
    calls: list = []
    router = _router(ai, {}, calls)
    result = await router.chat(ai.owner_id, "состояние системы")
    assert result.provider == "core"
    assert "Состояние системы" in result.text or "CPU" in result.text or "Память" in result.text
    assert calls == []


async def test_side_effects_not_executed_from_router_text(ai):
    """Текст из AI/Telegram не должен запускать действия с ПК через Core."""
    calls: list = []
    router = _router(ai, {}, calls, fail_on=("/v1/models", "/v1/chat/completions"))
    _settings(router, ai.owner_id, mode="local_only", allow_cloud=False)
    result = await router.chat(ai.owner_id, "открой браузер")
    assert result.provider != "core"
