"""Базовые типы AI-провайдеров."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol


class ProviderError(Exception):
    """Провайдер недоступен/вернул ошибку. Текст безопасен для логов."""

    def __init__(self, message: str, *, retryable: bool = True, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class Cancelled(Exception):
    """Запрос отменён пользователем."""


@dataclass
class ChatMessage:
    role: str
    content: str

    def as_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatRequest:
    messages: list[ChatMessage]
    system: str = ""
    temperature: float = 0.6
    max_tokens: int = 800
    stream: bool = False


@dataclass
class ChatResponse:
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    extra: dict = field(default_factory=dict)


class Provider(Protocol):
    name: str
    is_cloud: bool

    async def available(self) -> bool: ...

    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    def stream(self, request: ChatRequest) -> AsyncIterator[str]: ...
