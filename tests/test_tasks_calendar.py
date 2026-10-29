"""Проверки 3: создание/редактирование задач, действия, календарь."""
from __future__ import annotations


def _create(harness, **kwargs):
    payload = {"title": "Лабораторная", "description": "Отчёт", "priority": "high",
               "planned_minutes": 45, "category": "учёба"}
    payload.update(kwargs)
    resp = harness.client.post("/api/tasks", headers=harness.headers, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_task_crud(harness):
    task = _create(harness)
    assert task["version"] == 1 and task["status"] == "todo"

    patched = harness.client.patch(f"/api/tasks/{task['id']}", headers=harness.headers,
                                   json={"title": "Лабораторная №2", "due_at": "2026-11-01T09:00:00Z"})
    assert patched.status_code == 200
    assert patched.json()["title"] == "Лабораторная №2"
    assert patched.json()["version"] == 2
    assert patched.json()["due_at"].startswith("2026-11-01T09:00")

    listing = harness.client.get("/api/tasks", headers=harness.headers).json()["tasks"]
    assert len(listing) == 1

    assert harness.client.delete(f"/api/tasks/{task['id']}", headers=harness.headers).status_code == 200
    assert harness.client.get("/api/tasks", headers=harness.headers).json()["tasks"] == []
    assert harness.client.get(f"/api/tasks/{task['id']}", headers=harness.headers).status_code == 404


def test_task_time_actions(harness):
    task = _create(harness)
    tid = task["id"]
    started = harness.client.post(f"/api/tasks/{tid}/action/start", headers=harness.headers).json()
    assert started["status"] == "in_progress"
    assert started["started_at"]

    extended = harness.client.post(f"/api/tasks/{tid}/action/extend?minutes=15", headers=harness.headers).json()
    assert extended["planned_minutes"] == 60

    logged = harness.client.post(f"/api/tasks/{tid}/time", headers=harness.headers,
                                 json={"minutes": 20}).json()
    assert logged["actual_minutes"] == 20

    done = harness.client.post(f"/api/tasks/{tid}/action/complete", headers=harness.headers).json()
    assert done["status"] == "done" and done["completed_at"]

    skipped = harness.client.post(f"/api/tasks/{tid}/action/skip", headers=harness.headers).json()
    assert skipped["status"] == "skipped"

    assert harness.client.post(f"/api/tasks/{tid}/action/explode", headers=harness.headers).status_code == 400


def test_tasks_isolated_between_owners(harness):
    from ecosystem.backend.models import Owner
    from ecosystem.backend.security import hash_password

    with harness.db.session() as db:
        other = Owner(username="neighbour", password_hash=hash_password("Neighbour1!"))
        db.add(other)
        db.flush()
        other_id = other.id

    with harness.db.session() as db:
        from ecosystem.backend.models import Task

        task = Task(owner_id=other_id, title="чужая задача")
        db.add(task)
        db.flush()
        foreign_id = task.id

    assert harness.client.get(f"/api/tasks/{foreign_id}", headers=harness.headers).status_code == 404
    assert harness.client.delete(f"/api/tasks/{foreign_id}", headers=harness.headers).status_code == 404


def test_calendar_crud(harness):
    resp = harness.client.post("/api/events", headers=harness.headers,
                               json={"title": "Консультация", "starts_at": "2026-11-02T14:00:00Z",
                                     "ends_at": "2026-11-02T15:00:00Z", "location": "каб. 210"})
    assert resp.status_code == 200
    event = resp.json()
    assert event["location"] == "каб. 210"

    listing = harness.client.get("/api/events", headers=harness.headers, params={
        "start": "2026-11-01T00:00:00Z", "end": "2026-11-03T00:00:00Z"}).json()["events"]
    assert len(listing) == 1
    assert harness.client.get("/api/events", headers=harness.headers, params={
        "start": "2026-12-01T00:00:00Z"}).json()["events"] == []

    assert harness.client.patch(f"/api/events/{event['id']}", headers=harness.headers,
                                json={"title": "Консультация (перенос)"}).json()["title"] == "Консультация (перенос)"
    assert harness.client.delete(f"/api/events/{event['id']}", headers=harness.headers).status_code == 200
    assert harness.client.get("/api/events", headers=harness.headers).json()["events"] == []


def test_invalid_event_date_rejected(harness):
    resp = harness.client.post("/api/events", headers=harness.headers,
                               json={"title": "Кривая дата", "starts_at": "не дата"})
    assert resp.status_code == 422
