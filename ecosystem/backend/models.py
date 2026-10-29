"""Модели Ecosystem: owner, устройства, задачи, календарь, расписание, синхронизация, AI, аудит.

Правила:
  * у каждой пользовательской таблицы есть owner_id (переход к мультиарендности);
  * синхронизируемые сущности: uuid-первичный ключ, version, updated_at (UTC),
    deleted_at (tombstone), origin_device;
  * личные чаты, API-ключи и файлы НЕ синхронизируются.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow


def new_uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SyncMixin:
    """Поля, обязательные для синхронизируемых сущностей."""

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    origin_device: Mapped[str | None] = mapped_column(String(64), nullable=True)


# --------------------------------------------------------------------------- #
# Владелец / безопасность
# --------------------------------------------------------------------------- #
class Owner(Base, TimestampMixin):
    __tablename__ = "owners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserSession(Base):
    """Сессия пользователя (opaque-токен, в БД только хэш)."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Device(Base, TimestampMixin):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_device_owner_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="desktop")  # desktop|gpu|hub|controller
    platform: Mapped[str] = mapped_column(String(120), default="")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Секрет для подписи канала устройство↔HUB (HMAC), хранится зашифрованным
    channel_secret_enc: Mapped[str] = mapped_column(Text, default="")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="offline")  # online|offline|sleeping
    ai_available: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(String(255), default="")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Белый список приложений, которые агенту разрешено запускать/останавливать
    command_allowlist: Mapped[list] = mapped_column(JSON, default=list)
    pairing_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeviceCommand(Base):
    """Типизированная команда устройству. Свободный shell запрещён."""

    __tablename__ = "device_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_by: Mapped[str] = mapped_column(String(24), default="desktop")  # desktop|telegram|agent
    requested_by_id: Mapped[str] = mapped_column(String(64), default="")
    signature: Mapped[str] = mapped_column(String(128), default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Защита от повторного выполнения: команда живёт до expires_at и
    # исполняется один раз (executed_at выставляется агентом/HUB).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PairingCode(Base):
    """Одноразовый код привязки нового устройства (TTL, одно использование)."""

    __tablename__ = "pairing_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_name: Mapped[str] = mapped_column(String(80), default="")
    device_kind: Mapped[str] = mapped_column(String(24), default="desktop")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_by_device: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    actor: Mapped[str] = mapped_column(String(48), default="owner")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


# --------------------------------------------------------------------------- #
# Синхронизируемые сущности
# --------------------------------------------------------------------------- #
class Task(Base, TimestampMixin, SyncMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(12), default="normal")  # low|normal|high
    status: Mapped[str] = mapped_column(String(16), default="todo")  # todo|in_progress|done|skipped
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned_minutes: Mapped[int] = mapped_column(Integer, default=0)
    actual_minutes: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(48), default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CalendarEvent(Base, TimestampMixin, SyncMixin):
    __tablename__ = "calendar_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    location: Mapped[str] = mapped_column(String(120), default="")
    category: Mapped[str] = mapped_column(String(48), default="")
    remind_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ScheduleEntry(Base, TimestampMixin, SyncMixin):
    """Занятие колледжа (группа ИС-21)."""

    __tablename__ = "schedule_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    group_name: Mapped[str] = mapped_column(String(24), default="ИС-21", index=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    slot: Mapped[int] = mapped_column(Integer, default=0)
    start_time: Mapped[str] = mapped_column(String(5), default="")
    end_time: Mapped[str] = mapped_column(String(5), default="")
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    teacher: Mapped[str] = mapped_column(String(120), default="")
    room: Mapped[str] = mapped_column(String(48), default="")
    lesson_type: Mapped[str] = mapped_column(String(48), default="")
    source_file: Mapped[str] = mapped_column(String(160), default="")
    source_sheet: Mapped[str] = mapped_column(String(80), default="")


class UserPreference(Base, TimestampMixin, SyncMixin):
    """Разрешённые пользовательские настройки (тема, масштаб…)."""

    __tablename__ = "user_preferences"
    __table_args__ = (UniqueConstraint("owner_id", "key", name="uq_pref_owner_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class StudentProfile(Base, TimestampMixin, SyncMixin):
    """Студенческий профиль (Student Edition).

    id детерминирован от owner_id: два устройства, создавшие профиль
    независимо, получают одну и ту же запись и не плодят дубликаты.
    """

    __tablename__ = "student_profiles"
    __table_args__ = (UniqueConstraint("owner_id", name="uq_student_profile_owner"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    group_name: Mapped[str] = mapped_column(String(24), default="ИС-21")
    college: Mapped[str] = mapped_column(String(160), default="")
    specialty: Mapped[str] = mapped_column(String(160), default="")
    course: Mapped[int] = mapped_column(Integer, default=0)
    semester: Mapped[int] = mapped_column(Integer, default=0)
    study_form: Mapped[str] = mapped_column(String(32), default="")
    student_card: Mapped[str] = mapped_column(String(48), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(24), default="manual")  # manual|legacy_import


class ChangeLog(Base):
    """Журнал изменений HUB: курсор для pull-синхронизации."""

    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    entity: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    operation: Mapped[str] = mapped_column(String(16), default="upsert")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    device_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class SyncOperation(Base):
    """Идемпотентность push: op_id уникален в рамках владельца."""

    __tablename__ = "sync_operations"
    __table_args__ = (UniqueConstraint("owner_id", "op_id", name="uq_sync_op"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    op_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), default="")
    entity: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SyncConflict(Base):
    """Конфликт версий: обе версии сохраняются до решения владельца."""

    __tablename__ = "sync_conflicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    entity: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    base_version: Mapped[int] = mapped_column(Integer, default=0)
    server_version: Mapped[int] = mapped_column(Integer, default=0)
    incoming: Mapped[dict] = mapped_column(JSON, default=dict)
    server: Mapped[dict] = mapped_column(JSON, default=dict)
    device_id: Mapped[str] = mapped_column(String(36), default="")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|resolved|discarded
    resolution: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OutboxEntry(Base):
    """Локальная очередь изменений Desktop (не отправлена в HUB)."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    op_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    entity: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), default="upsert")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    base_version: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SyncState(Base):
    """Состояние синхронизации устройства (курсор pull, время, ошибка)."""

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), default="")
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_pull_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(255), default="")
    online: Mapped[bool] = mapped_column(Boolean, default=False)


# --------------------------------------------------------------------------- #
# AI: настройки, ключи, использование, личные чаты (НЕ синхронизируются)
# --------------------------------------------------------------------------- #
class AiSettings(Base, TimestampMixin):
    __tablename__ = "ai_settings"

    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), default="hybrid")  # local_only|hybrid|cloud_preferred|manual
    allow_cloud: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_history_to_cloud: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_remote_node: Mapped[bool] = mapped_column(Boolean, default=True)
    cloud_provider: Mapped[str] = mapped_column(String(32), default="gemini")
    manual_model: Mapped[str] = mapped_column(String(120), default="")
    local_model: Mapped[str] = mapped_column(String(120), default="")
    daily_request_limit: Mapped[int] = mapped_column(Integer, default=200)
    monthly_budget: Mapped[float] = mapped_column(Float, default=0.0)  # 0 = без лимита
    temperature: Mapped[float] = mapped_column(Float, default=0.6)


class ProviderKey(Base):
    """API-ключи провайдеров: только в зашифрованном виде, никогда в логах."""

    __tablename__ = "provider_keys"
    __table_args__ = (UniqueConstraint("owner_id", "provider", name="uq_key_owner_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AiUsage(Base):
    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    cloud: Mapped[bool] = mapped_column(Boolean, default=False)
    device_id: Mapped[str] = mapped_column(String(36), default="")
    request_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class ChatConversation(Base, TimestampMixin):
    """Личная история диалогов — НЕ синхронизируется (по требованию приватности)."""

    __tablename__ = "ai_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Новый диалог")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class LegacyImportRecord(Base):
    """Журнал импорта из Student Edition: что и когда перенесено (идемпотентность)."""

    __tablename__ = "legacy_import_records"
    __table_args__ = (UniqueConstraint("owner_id", "source_path", "kind", "source_key",
                                       name="uq_legacy_import_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    source_path: Mapped[str] = mapped_column(String(400), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)      # task | lesson | profile
    source_key: Mapped[str] = mapped_column(String(120), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), default="")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #
class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), default="")
    linked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TelegramLinkCode(Base):
    __tablename__ = "telegram_link_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claimed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="info")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    delivered_telegram_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
