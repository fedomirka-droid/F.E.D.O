"""legacy import journal for Student Edition

Revision ID: c3f81a5d7e42
Revises: a7c41d90e2b5
Create Date: 2026-10-29 06:50:00.000000

Аддитивная миграция: добавляется журнал импорта из Student Edition.
Он нужен для идемпотентности — повторный импорт той же базы не создаёт
дубликатов задач и занятий. Существующие таблицы и данные не трогаются.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c3f81a5d7e42"
down_revision = "a7c41d90e2b5"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("legacy_import_records"):
        return
    op.create_table(
        "legacy_import_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("source_path", sa.String(length=400), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("checksum", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "source_path", "kind", "source_key",
                            name="uq_legacy_import_source"),
    )
    op.create_index("ix_legacy_import_owner", "legacy_import_records", ["owner_id"])


def downgrade() -> None:
    if _has_table("legacy_import_records"):
        op.drop_index("ix_legacy_import_owner", table_name="legacy_import_records")
        op.drop_table("legacy_import_records")
