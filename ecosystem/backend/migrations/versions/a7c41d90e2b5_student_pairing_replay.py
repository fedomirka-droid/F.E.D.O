"""student profile + device pairing codes + command replay protection

Revision ID: a7c41d90e2b5
Revises: ef92a32bf0fe
Create Date: 2026-10-29 06:30:00.000000

Миграция аддитивная: существующие таблицы не пересоздаются, данные
пользователя сохраняются. Добавляются:

  * student_profiles — профиль студента (один на владельца);
  * pairing_codes — одноразовые коды привязки нового устройства;
  * devices.command_allowlist / devices.pairing_confirmed_at — белый список
    разрешённых приложений и отметка привязки;
  * device_commands.expires_at / executed_at — защита от повторного
    выполнения (команда исполняется один раз и до истечения срока).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a7c41d90e2b5"
down_revision = "ef92a32bf0fe"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_table("student_profiles"):
        op.create_table(
            "student_profiles",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("group_name", sa.String(length=24), nullable=False),
            sa.Column("college", sa.String(length=160), nullable=False),
            sa.Column("specialty", sa.String(length=160), nullable=False),
            sa.Column("course", sa.Integer(), nullable=False),
            sa.Column("semester", sa.Integer(), nullable=False),
            sa.Column("study_form", sa.String(length=32), nullable=False),
            sa.Column("student_card", sa.String(length=48), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=24), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("origin_device", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("owner_id", name="uq_student_profile_owner"),
        )
        op.create_index(op.f("ix_student_profiles_owner_id"), "student_profiles",
                        ["owner_id"], unique=False)

    if not _has_table("pairing_codes"):
        op.create_table(
            "pairing_codes",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("device_name", sa.String(length=80), nullable=False),
            sa.Column("device_kind", sa.String(length=24), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("used_by_device", sa.String(length=36), nullable=True),
            sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_pairing_codes_owner_id"), "pairing_codes",
                        ["owner_id"], unique=False)
        op.create_index(op.f("ix_pairing_codes_code_hash"), "pairing_codes",
                        ["code_hash"], unique=False)

    if not _has_column("devices", "command_allowlist"):
        with op.batch_alter_table("devices", schema=None) as batch_op:
            batch_op.add_column(sa.Column("command_allowlist", sa.JSON(), nullable=True))
    if not _has_column("devices", "pairing_confirmed_at"):
        with op.batch_alter_table("devices", schema=None) as batch_op:
            batch_op.add_column(sa.Column("pairing_confirmed_at", sa.DateTime(), nullable=True))

    if not _has_column("device_commands", "expires_at"):
        with op.batch_alter_table("device_commands", schema=None) as batch_op:
            batch_op.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
    if not _has_column("device_commands", "executed_at"):
        with op.batch_alter_table("device_commands", schema=None) as batch_op:
            batch_op.add_column(sa.Column("executed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if _has_column("device_commands", "executed_at"):
        with op.batch_alter_table("device_commands", schema=None) as batch_op:
            batch_op.drop_column("executed_at")
    if _has_column("device_commands", "expires_at"):
        with op.batch_alter_table("device_commands", schema=None) as batch_op:
            batch_op.drop_column("expires_at")
    if _has_column("devices", "pairing_confirmed_at"):
        with op.batch_alter_table("devices", schema=None) as batch_op:
            batch_op.drop_column("pairing_confirmed_at")
    if _has_column("devices", "command_allowlist"):
        with op.batch_alter_table("devices", schema=None) as batch_op:
            batch_op.drop_column("command_allowlist")
    if _has_table("pairing_codes"):
        op.drop_index(op.f("ix_pairing_codes_code_hash"), table_name="pairing_codes")
        op.drop_index(op.f("ix_pairing_codes_owner_id"), table_name="pairing_codes")
        op.drop_table("pairing_codes")
    if _has_table("student_profiles"):
        op.drop_index(op.f("ix_student_profiles_owner_id"), table_name="student_profiles")
        op.drop_table("student_profiles")
