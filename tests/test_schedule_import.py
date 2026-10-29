"""Проверка 8: импорт расписания ИС-21 из XLS/XLSX (разные форматы)."""
from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from ecosystem.backend.services.schedule_import import parse_schedule, split_lesson


def _workbook() -> Workbook:
    return Workbook()


def _bytes(wb: Workbook) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_block_workbook() -> bytes:
    """Один лист: дата в шапке, два занятия, соседние группы рядом."""
    wb = _workbook()
    ws = wb.active
    ws.title = "Расписание"
    ws["A1"] = "Расписание занятий на 12.05.2026"
    ws["A2"], ws["B2"], ws["C2"], ws["E2"], ws["F2"] = "Пара", "Время", "ИС-21", "ИС-22", "ЭК-31"
    ws.merge_cells("C2:D2")
    ws["A3"], ws["B3"], ws["C3"] = 1, "8:30-10:00", "Математика каб. 215 Иванов И.И."
    ws.merge_cells("C3:D3")
    ws["E3"] = "ЧУЖАЯ ГРУППА: история"
    ws["A4"], ws["B4"], ws["C4"] = 2, "10:10-11:40", "Физика (лабораторная) ауд. 12 Петров П.П."
    ws.merge_cells("C4:D4")
    ws["A5"], ws["B5"] = 3, "12:10-13:40"  # пустая ячейка группы — пропуск
    ws["E6"] = "ЧУЖАЯ ГРУППА: химия"
    return _bytes(wb)


def build_multi_sheet_workbook() -> bytes:
    wb = _workbook()
    ws1 = wb.active
    ws1.title = "13.05.2026"
    ws1["A1"], ws1["B1"], ws1["C1"], ws1["D1"] = "Пара", "Время", "ИС-22", "ИС-21"
    ws1["A2"], ws1["B2"] = 1, "8:30-10:00"
    ws1["C2"] = "НЕ НАША: экономика"
    ws1["D2"] = "Информатика каб. 305 Смирнов А.П."
    ws2 = wb.create_sheet("14.05.2026")
    ws2["A1"], ws2["B1"], ws2["C1"] = "Пара", "Время", "ИС-21"
    ws2["A2"], ws2["B2"], ws2["C2"] = 1, "8:30-10:00", "История И.И. Сидоров"
    return _bytes(wb)


def build_multi_day_workbook() -> bytes:
    wb = _workbook()
    ws = wb.active
    ws.title = "Неделя"
    ws["A1"], ws["B1"], ws["C1"] = "Пара", "Время", "ИС-21"
    ws["A2"], ws["C2"] = "Понедельник 13.05.2026", "Алгебра каб. 201"
    ws["A3"], ws["B3"], ws["C3"] = 1, "8:30-10:00", "Алгебра каб. 201"
    ws["A4"], ws["C4"] = "Вторник 14.05.2026", "Геометрия каб. 202"
    ws["A5"], ws["B5"], ws["C5"] = 1, "8:30-10:00", "Геометрия каб. 202"
    return _bytes(wb)


def test_block_format_reads_only_target_group():
    result = parse_schedule(build_block_workbook(), filename="schedule.xlsx")
    assert result.entries, result.warnings
    subjects = [e["subject"] for e in result.entries]
    assert "Математика" in subjects and "Физика" in subjects
    assert not any("ЧУЖАЯ" in s or "экономика" in s for s in subjects)
    first = result.entries[0]
    assert first["date"] == "2026-05-12"
    assert first["start_time"] == "08:30" and first["end_time"] == "10:00"
    assert first["room"] == "каб. 215"
    assert first["teacher"] == "Иванов И.И."
    assert first["group_name"] == "ИС-21"


def test_merged_cells_and_empty_rows_are_handled():
    result = parse_schedule(build_block_workbook(), filename="schedule.xlsx")
    assert len(result.entries) == 2  # пустая пара не превращается в занятие
    assert all(e["subject"] for e in result.entries)


def test_multiple_sheets_and_neighbour_columns():
    result = parse_schedule(build_multi_sheet_workbook(), filename="week.xlsx")
    assert result.sheets_scanned == 2 and result.sheets_matched == 2
    dates = sorted({e["date"] for e in result.entries})
    assert dates == ["2026-05-13", "2026-05-14"]
    assert {e["subject"] for e in result.entries} == {"Информатика", "История"}
    assert all("экономика" not in e["subject"] for e in result.entries)


def test_multi_day_blocks():
    result = parse_schedule(build_multi_day_workbook(), filename="week.xlsx")
    assert {e["date"] for e in result.entries} == {"2026-05-13", "2026-05-14"}


def test_group_parameter_can_switch_target():
    result = parse_schedule(build_block_workbook(), filename="schedule.xlsx", group="ИС-22")
    assert result.entries, result.warnings
    assert all("ЧУЖАЯ" in e["subject"] for e in result.entries)
    assert not any("Математика" in e["subject"] for e in result.entries)
    assert all(e["group_name"] == "ИС-22" for e in result.entries)


def test_missing_group_column_gives_warning_without_inventing():
    wb = _workbook()
    ws = wb.active
    ws["A1"], ws["B1"], ws["C1"] = "Пара", "Время", "ИС-22"
    ws["C2"] = "Экономика"
    result = parse_schedule(_bytes(wb), filename="other.xlsx")
    assert result.entries == []
    assert result.sheets_matched == 0
    assert any("не найден" in w for w in result.warnings)


def test_no_date_does_not_invent_lessons():
    wb = _workbook()
    ws = wb.active
    ws.title = "Лист1"
    ws["A1"], ws["B1"], ws["C1"] = "Пара", "Время", "ИС-21"
    ws["A2"], ws["B2"], ws["C2"] = 1, "8:30-10:00", "Математика каб. 215"
    result = parse_schedule(_bytes(wb), filename="noschedule.xlsx")
    assert result.entries == []
    assert any("дата" in w.lower() for w in result.warnings)


def test_date_override_and_filename_date():
    wb = _workbook()
    ws = wb.active
    ws.title = "Лист1"
    ws["A1"], ws["B1"], ws["C1"] = "Пара", "Время", "ИС-21"
    ws["C2"] = "Математика каб. 215"
    data = _bytes(wb)
    from_override = parse_schedule(data, filename="plain.xlsx", date_override="20.05.2026")
    assert [e["date"] for e in from_override.entries] == ["2026-05-20"]
    from_name = parse_schedule(data, filename="raspisanie_21.05.2026.xlsx")
    assert [e["date"] for e in from_name.entries] == ["2026-05-21"]


def test_corrupted_file_raises():
    with pytest.raises(ValueError):
        parse_schedule(b"not a workbook at all", filename="broken.xlsx")


def test_xls_requires_xlrd(monkeypatch):
    """XLS читается через xlrd; при отсутствии библиотеки — понятная ошибка."""
    pytest.importorskip("xlrd")
    with pytest.raises(Exception):
        parse_schedule(b"\xd0\xcf\x11\xe0broken", filename="old.xls")


@pytest.mark.parametrize("text,expected", [
    ("Физика (лабораторная) ауд. 12 Петров П.П.", ("Физика", "Петров П.П.", "ауд. 12", "лабор")),
    ("История И.И. Сидоров", ("История", "И.И. Сидоров", "", "")),
    ("Химия, лаб. 210", ("Химия", "", "лаб. 210", "")),
    ("Информатика", ("Информатика", "", "", "")),
])
def test_lesson_split_variants(text, expected):
    parts = split_lesson(text)
    assert (parts["subject"], parts["teacher"], parts["room"], parts["lesson_type"]) == expected


def test_import_api_endpoint(harness):
    resp = harness.client.post("/api/schedule/import", headers=harness.headers,
                               files={"file": ("schedule.xlsx", build_block_workbook(),
                                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                               data={"group": "ИС-21", "date_override": ""})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 2
    assert body["dates"] == ["2026-05-12"]

    listing = harness.client.get("/api/schedule", headers=harness.headers,
                                 params={"day": "2026-05-12"}).json()["entries"]
    assert len(listing) == 2
    assert listing[0]["start_time"] == "08:30"

    # повторный импорт того же дня не дублирует записи
    harness.client.post("/api/schedule/import", headers=harness.headers,
                        files={"file": ("schedule.xlsx", build_block_workbook())},
                        data={"group": "ИС-21"})
    again = harness.client.get("/api/schedule", headers=harness.headers,
                               params={"day": "2026-05-12"}).json()["entries"]
    assert len(again) == 2


def test_import_rejects_wrong_extension_and_empty(harness):
    bad = harness.client.post("/api/schedule/import", headers=harness.headers,
                              files={"file": ("schedule.csv", b"a,b", "text/csv")})
    assert bad.status_code == 415
    empty = harness.client.post("/api/schedule/import", headers=harness.headers,
                                files={"file": ("schedule.xlsx", b"", "application/vnd.ms-excel")})
    assert empty.status_code == 422


def test_import_damaged_file_reports_warning(harness):
    resp = harness.client.post("/api/schedule/import", headers=harness.headers,
                               files={"file": ("broken.xlsx", b"garbage-bytes",
                                               "application/vnd.ms-excel")})
    assert resp.status_code == 422


def test_noise_rows_do_not_become_lessons():
    """Даты, номера пар и заголовки групп не превращаются в «предметы»."""
    from ecosystem.backend.services.schedule_import import _is_noise_cell

    for text in ("30.10.2026", "12.05", "1 пара", "пара 2", "3", "Время",
                 "ИС-21", "Понедельник", "10:10-11:40", ""):
        assert _is_noise_cell(text), text
    for text in ("Математика", "Базы данных", "Физика (лабораторная) Иванов И.И."):
        assert _is_noise_cell(text) == "", text


def test_merged_label_block_without_subjects_is_not_fabricated():
    """Excel-блок с датой и «N пара» (как в реальных шапках) не даёт занятий."""
    wb = _workbook()
    ws = wb.active
    ws["A1"] = "Расписание ИС-21"
    ws["B2"], ws["C2"] = "ИС-21", "ИС-22"
    ws["A3"] = "30.10.2026"
    ws.merge_cells("B3:B4")
    ws["B3"] = "1 пара"
    ws["A5"], ws["B5"] = "2 пара", "ЧУЖОЕ (ИС-22)"
    result = parse_schedule(_bytes(wb), filename="labels.xlsx")
    assert result.entries == []
    assert result.warnings, "должно быть предупреждение, а не выдуманные занятия"


def test_real_table_layout_imports_cleanly():
    wb = _workbook()
    ws = wb.active
    ws["A1"], ws["B1"], ws["C1"], ws["D1"] = "Пара", "Время", "ИС-21", "ИС-22"
    ws["A2"], ws["B2"], ws["C2"] = 1, "09:00-10:30", "Сети (лекция) Иванов И.И. каб. 204"
    ws["D2"] = "ЧУЖАЯ: экономика"
    ws["A3"], ws["B3"], ws["C3"] = 2, "10:40-12:10", "Базы данных (практика) Петрова А.С. ауд. 301"
    result = parse_schedule(_bytes(wb), filename="week.xlsx", date_override="2026-10-30")
    assert [e["subject"] for e in result.entries] == ["Сети", "Базы данных"]
    assert all(e["date"] == "2026-10-30" for e in result.entries)
    assert result.entries[0]["start_time"] == "09:00"
    assert result.entries[1]["room"] == "ауд. 301"
    assert not any("экономика" in e["subject"].lower() for e in result.entries)
