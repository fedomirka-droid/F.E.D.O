"""Student Edition: профиль студента и совместимый слой импорта."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import Settings
from ..deps import DbDep, OwnerDep, SettingsDep, audit
from ..services import student

router = APIRouter(prefix="/api/student", tags=["student"])


class ProfileUpdate(BaseModel):
    group_name: str | None = Field(default=None, max_length=24)
    college: str | None = Field(default=None, max_length=160)
    specialty: str | None = Field(default=None, max_length=160)
    course: int | None = Field(default=None, ge=0, le=8)
    semester: int | None = Field(default=None, ge=0, le=16)
    study_form: str | None = Field(default=None, max_length=32)
    student_card: str | None = Field(default=None, max_length=48)
    notes: str | None = Field(default=None, max_length=4000)


class ImportRequest(BaseModel):
    path: str | None = Field(default=None, max_length=512,
                            description="Путь к SQLite Student Edition; по умолчанию — автопоиск")
    dry_run: bool = False


@router.get("/profile")
def get_profile(auth: OwnerDep, db: DbDep) -> dict:
    profile = student.get_or_create_profile(db, auth.owner.id)
    return student.profile_public(profile)


@router.put("/profile")
def put_profile(payload: ProfileUpdate, auth: OwnerDep, db: DbDep, settings: SettingsDep) -> dict:
    profile = student.update_profile(db, auth.owner.id,
                                     payload.model_dump(exclude_none=True),
                                     settings=settings,
                                     device_id=auth.device.id if auth.device else "")
    audit(db, auth.owner.id, "student.profile.update", target=profile.id)
    return student.profile_public(profile)


@router.get("/status")
def status(auth: OwnerDep, db: DbDep) -> dict:
    return student.integration_status(db, auth.owner.id)


@router.post("/import")
def import_legacy(payload: ImportRequest, auth: OwnerDep, db: DbDep) -> dict:
    """Импорт данных Student Edition. Без исходников вернёт понятную ошибку."""
    detection = student.detect_legacy()
    source = payload.path
    if not source:
        if not detection["databases"]:
            raise HTTPException(
                status_code=409,
                detail=("Исходники Student Edition MVP отсутствуют: нет ни каталога, "
                        "ни архива, ни SQLite-базы. Импорт невозможен."),
            )
        source = detection["databases"][0]["path"]
    report = student.import_legacy(db, auth.owner.id, source, dry_run=payload.dry_run)
    if not report.get("ok"):
        raise HTTPException(status_code=400, detail=report.get("reason") or "Импорт не удался")
    return report


@router.get("/detect")
def detect() -> dict:
    """Что найдено в файловой системе (без авторизации не отдаём пути)."""
    detection = student.detect_legacy()
    return detection
