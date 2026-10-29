"""AI Router 2.0: чат, стриминг, модели, приватность, расходы, личные диалоги."""
from __future__ import annotations

import json
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import utcnow
from ..deps import DbDep, OwnerDep, SettingsDep, audit
from ..models import ChatConversation, ChatMessage, ProviderKey
from ..security import SecretBox, redact
from ..services.ai_router import MODE_LABELS, AiRouter

router = APIRouter(prefix="/api/ai", tags=["ai"])

ALLOWED_PROVIDERS = ("gemini", "openai", "openai_base_url")


class AiSettingsUpdate(BaseModel):
    mode: Literal["local_only", "hybrid", "cloud_preferred", "manual"] | None = None
    allow_cloud: bool | None = None
    allow_history_to_cloud: bool | None = None
    allow_remote_node: bool | None = None
    cloud_provider: Literal["gemini", "openai"] | None = None
    manual_model: str | None = Field(default=None, max_length=120)
    local_model: str | None = Field(default=None, max_length=120)
    daily_request_limit: int | None = Field(default=None, ge=0, le=100000)
    monthly_budget: float | None = Field(default=None, ge=0, le=100000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=16000)
    conversation_id: str | None = None
    mode: Literal["local_only", "hybrid", "cloud_preferred", "manual"] | None = None
    model: str | None = Field(default=None, max_length=120)
    request_id: str | None = Field(default=None, max_length=64)


class KeyIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=400)
    base_url: str | None = Field(default=None, max_length=200)


class ConversationIn(BaseModel):
    title: str = Field(default="Новый диалог", max_length=200)


def _router(db, settings, request: Request) -> AiRouter:
    return AiRouter(db, settings, SecretBox(settings.secret_key),
                    cancel_registry=request.app.state.ai_cancels)


def _settings_public(ai) -> dict:
    return {
        "mode": ai.mode,
        "modes": MODE_LABELS,
        "allow_cloud": ai.allow_cloud,
        "allow_history_to_cloud": ai.allow_history_to_cloud,
        "allow_remote_node": ai.allow_remote_node,
        "cloud_provider": ai.cloud_provider,
        "manual_model": ai.manual_model,
        "local_model": ai.local_model,
        "daily_request_limit": ai.daily_request_limit,
        "monthly_budget": ai.monthly_budget,
        "temperature": ai.temperature,
    }


@router.get("/settings")
def get_settings(auth: OwnerDep, db: DbDep, settings: SettingsDep,
                 request: Request) -> dict:
    ai = _router(db, settings, request).ai_settings(auth.owner.id)
    return _settings_public(ai)


@router.put("/settings")
def put_settings(payload: AiSettingsUpdate, auth: OwnerDep, db: DbDep, settings: SettingsDep,
                 request: Request) -> dict:
    ai = _router(db, settings, request).ai_settings(auth.owner.id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(ai, key, value)
    # fail-safe: manual-режим без модели не должен «молча» уходить в облако
    if ai.mode == "local_only":
        ai.allow_cloud = False
    db.flush()
    audit(db, auth.owner.id, "ai.settings", target=ai.mode,
          allow_cloud=ai.allow_cloud, history=ai.allow_history_to_cloud)
    return _settings_public(ai)


@router.get("/models")
async def models(auth: OwnerDep, db: DbDep, settings: SettingsDep, request: Request) -> dict:
    return await _router(db, settings, request).models(auth.owner.id)


@router.get("/usage")
def usage(auth: OwnerDep, db: DbDep, settings: SettingsDep, request: Request) -> dict:
    return _router(db, settings, request).usage_summary(auth.owner.id)


@router.get("/keys")
def list_keys(auth: OwnerDep, db: DbDep) -> dict:
    rows = db.execute(select(ProviderKey).where(ProviderKey.owner_id == auth.owner.id)).scalars().all()
    return {"configured": [row.provider for row in rows]}  # значения НИКОГДА не отдаём


@router.post("/keys/{provider}")
def set_key(provider: str, payload: KeyIn, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Неизвестный провайдер")
    box = SecretBox(settings.secret_key)
    value = payload.base_url if provider == "openai_base_url" else payload.api_key
    row = db.execute(select(ProviderKey).where(ProviderKey.owner_id == auth.owner.id,
                                               ProviderKey.provider == provider)).scalar_one_or_none()
    if row is None:
        db.add(ProviderKey(owner_id=auth.owner.id, provider=provider,
                           encrypted_key=box.encrypt(value)))
    else:
        row.encrypted_key = box.encrypt(value)
        row.updated_at = utcnow()
    db.flush()
    audit(db, auth.owner.id, "ai.key.set", target=provider)
    return {"ok": True, "provider": provider}


@router.delete("/keys/{provider}")
def delete_key(provider: str, auth: OwnerDep, db: DbDep) -> dict:
    row = db.execute(select(ProviderKey).where(ProviderKey.owner_id == auth.owner.id,
                                               ProviderKey.provider == provider)).scalar_one_or_none()
    if row is not None:
        db.delete(row)
        db.flush()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Диалоги (личные, НЕ синхронизируются)
# --------------------------------------------------------------------------- #
@router.get("/conversations")
def list_conversations(auth: OwnerDep, db: DbDep) -> dict:
    rows = db.execute(select(ChatConversation).where(ChatConversation.owner_id == auth.owner.id)
                      .order_by(ChatConversation.updated_at.desc()).limit(100)).scalars().all()
    return {"conversations": [{"id": c.id, "title": c.title,
                               "updated_at": c.updated_at.isoformat() + "Z"} for c in rows]}


@router.post("/conversations")
def create_conversation(payload: ConversationIn, auth: OwnerDep, db: DbDep) -> dict:
    conv = ChatConversation(owner_id=auth.owner.id, title=payload.title)
    db.add(conv)
    db.flush()
    return {"id": conv.id, "title": conv.title}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, auth: OwnerDep, db: DbDep) -> dict:
    conv = db.get(ChatConversation, conversation_id)
    if conv is None or conv.owner_id != auth.owner.id:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    db.delete(conv)
    db.flush()
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: str, auth: OwnerDep, db: DbDep) -> dict:
    conv = db.get(ChatConversation, conversation_id)
    if conv is None or conv.owner_id != auth.owner.id:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    rows = db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                      .order_by(ChatMessage.id)).scalars().all()
    return {"messages": [{"id": m.id, "role": m.role, "content": m.content,
                          "provider": m.provider, "model": m.model,
                          "created_at": m.created_at.isoformat() + "Z"} for m in rows]}


# --------------------------------------------------------------------------- #
# Чат
# --------------------------------------------------------------------------- #
def _history(db, conversation_id: str | None) -> list[dict]:
    if not conversation_id:
        return []
    rows = db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                      .order_by(ChatMessage.id.desc()).limit(12)).scalars().all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


@router.post("/chat")
async def chat(payload: ChatIn, auth: OwnerDep, db: DbDep, settings: SettingsDep,
               request: Request) -> dict:
    conversation_id = payload.conversation_id
    if conversation_id:
        conv = db.get(ChatConversation, conversation_id)
        if conv is None or conv.owner_id != auth.owner.id:
            raise HTTPException(status_code=404, detail="Диалог не найден")
    else:
        conv = ChatConversation(owner_id=auth.owner.id,
                                title=payload.message.strip()[:60] or "Новый диалог")
        db.add(conv)
        db.flush()
        conversation_id = conv.id

    history = _history(db, conversation_id)
    db.add(ChatMessage(owner_id=auth.owner.id, conversation_id=conversation_id,
                       role="user", content=payload.message))
    db.flush()

    request_id = payload.request_id or str(uuid.uuid4())
    router_ = _router(db, settings, request)
    result = await router_.chat(auth.owner.id, payload.message, history=history,
                                mode=payload.mode, model=payload.model, request_id=request_id)
    db.add(ChatMessage(owner_id=auth.owner.id, conversation_id=conversation_id,
                       role="assistant", content=result.text,
                       provider=result.provider, model=result.model))
    conv.updated_at = utcnow()
    db.flush()
    return {"conversation_id": conversation_id, **result.as_dict(),
            "log": redact(result.text[:0])}


@router.post("/chat/stream")
async def chat_stream(payload: ChatIn, auth: OwnerDep, settings: SettingsDep,
                      request: Request) -> StreamingResponse:
    """SSE-стрим. Сессия БД открывается внутри генератора (живёт весь стрим)."""
    db_session_factory = request.app.state.db
    request_id = payload.request_id or str(uuid.uuid4())

    async def event_stream():
        with db_session_factory.session() as db:
            conversation_id = payload.conversation_id
            conv = db.get(ChatConversation, conversation_id) if conversation_id else None
            if conv is None or conv.owner_id != auth.owner.id:
                conv = ChatConversation(owner_id=auth.owner.id,
                                        title=payload.message.strip()[:60] or "Новый диалог")
                db.add(conv)
                db.flush()
                conversation_id = conv.id
            history = _history(db, conversation_id)
            db.add(ChatMessage(owner_id=auth.owner.id, conversation_id=conversation_id,
                               role="user", content=payload.message))
            db.flush()
            yield _sse({"type": "meta", "conversation_id": conversation_id,
                        "request_id": request_id})
            router_ = _router(db, settings, request)
            full_text = ""
            final: dict = {}
            async for event in router_.stream(auth.owner.id, payload.message, history=history,
                                              mode=payload.mode, model=payload.model,
                                              request_id=request_id):
                if event.get("type") == "chunk":
                    full_text += event.get("text", "")
                if event.get("type") == "done":
                    final = event
                if await request.is_disconnected():
                    router_.cancel(request_id)
                    break
                yield _sse(event)
            if not full_text and final.get("text"):
                full_text = final["text"]
            db.add(ChatMessage(owner_id=auth.owner.id, conversation_id=conversation_id,
                               role="assistant", content=full_text,
                               provider=final.get("provider", ""), model=final.get("model", "")))
            conv.updated_at = utcnow()
            db.flush()
            router_.finish(request_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/cancel/{request_id}")
def cancel(request_id: str, auth: OwnerDep, request: Request) -> dict:
    router_ = AiRouter(None, request.app.state.settings, SecretBox("x"),
                       cancel_registry=request.app.state.ai_cancels)
    return {"ok": router_.cancel(request_id)}
