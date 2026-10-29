"""Общие фикстуры: изолированная БД, приложение, владелец, мок HTTP."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from ecosystem.backend.app import create_app  # noqa: E402
from ecosystem.backend.config import Settings  # noqa: E402
from ecosystem.backend.db import Database  # noqa: E402

PASSWORD = "Sup3rSecret!"


class AppHarness:
    def __init__(self, settings: Settings, db: Database, app, client: TestClient):
        self.settings = settings
        self.db = db
        self.app = app
        self.client = client
        self.token: str = ""
        self.owner_id: str = ""

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def setup_owner(self, username: str = "owner", password: str = PASSWORD) -> dict:
        resp = self.client.post("/api/auth/setup",
                                json={"username": username, "password": password})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        self.token = data["token"]
        self.owner_id = data["owner"]["id"]
        return data

    def login(self, username: str = "owner", password: str = PASSWORD) -> dict:
        resp = self.client.post("/api/auth/login",
                                json={"username": username, "password": password})
        assert resp.status_code == 200, resp.text
        self.token = resp.json()["token"]
        return resp.json()

    def make_app(self, role: str = "desktop") -> None:
        """Пересоздать приложение на той же БД (имитация перезапуска)."""
        self.app = create_app(self.settings, self.db, auto_migrate=False, start_sync=False)
        self.client = TestClient(self.app)


@pytest.fixture
def make_harness(tmp_path):
    counter = {"n": 0}

    def _factory(role: str = "desktop", **overrides) -> AppHarness:
        counter["n"] += 1
        data_dir = tmp_path / f"instance-{counter['n']}"
        data_dir.mkdir(parents=True, exist_ok=True)
        settings = Settings(data_dir=str(data_dir), role=role,
                            database_url=f"sqlite:///{data_dir}/fedo-{role}.db",
                            secret_key="test-secret-key-not-for-production",
                            hub_url=overrides.pop("hub_url", ""),
                            **overrides)
        db = Database(settings)
        db.create_all()
        app = create_app(settings, db, auto_migrate=False, start_sync=False)
        return AppHarness(settings, db, app, TestClient(app))
    return _factory


@pytest.fixture
def harness(make_harness) -> AppHarness:
    h = make_harness("desktop")
    h.setup_owner()
    return h


@pytest.fixture
def hub(make_harness) -> AppHarness:
    h = make_harness("hub")
    h.setup_owner()
    return h


@pytest.fixture
def no_network(monkeypatch):
    """Любой реальный сетевой вызов к внешнему хосту — ошибка."""
    def guard(request: httpx.Request):
        raise AssertionError(f"unexpected network call: {request.url}")
    return guard


def make_mock_client(routes: dict, calls: list | None = None, fail_on: tuple = ()):
    """httpx.MockTransport по правилам «METHOD path → ответ».

    routes: {("GET", "/v1/models"): {"json": {...}} | {"status": 500, ...}}
    """
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append((request.method, str(request.url), request.headers, request.content))
        key = (request.method, request.url.path)
        if key in fail_on or request.url.path in fail_on:
            raise httpx.ConnectError("connection refused", request=request)
        spec = routes.get(key) or routes.get(request.url.path)
        if spec is None:
            raise AssertionError(f"unexpected call {key}")
        if callable(spec):
            return spec(request)
        return httpx.Response(spec.get("status", 200),
                              json=spec.get("json"),
                              text=spec.get("text"))

    transport = httpx.MockTransport(handler)

    def factory(timeout=None):
        return httpx.AsyncClient(transport=transport, timeout=timeout or 30)

    return factory


def local_models(model: str = "local-model") -> dict:
    return {"data": [{"id": model}]}


def openai_chat(text: str = "локальный ответ", prompt_tokens: int = 12,
                completion_tokens: int = 5) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def gemini_chat(text: str = "облачный ответ") -> dict:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 500},
    }
