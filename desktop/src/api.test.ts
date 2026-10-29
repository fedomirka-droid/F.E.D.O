import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  createLesson,
  deleteLesson,
  formatDate,
  formatDateTime,
  getToken,
  setToken,
  todayIso,
} from "./api";

const jsonResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("токен", () => {
  it("сохраняется и очищается", () => {
    expect(getToken()).toBe("");
    setToken("abc");
    expect(getToken()).toBe("abc");
    setToken("");
    expect(getToken()).toBe("");
  });

  it("подставляется в заголовок Authorization", async () => {
    setToken("secret-token");
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, { ok: true }));
    await api("/api/health");
    const headers = spy.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer secret-token");
  });
});

describe("api", () => {
  it("на 401 очищает токен и шлёт событие", async () => {
    setToken("old");
    const events: string[] = [];
    window.addEventListener("fedo:unauthorized", () => events.push("fired"));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(401, { detail: "nope" }));
    await expect(api("/api/tasks")).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBe("");
    expect(events).toEqual(["fired"]);
  });

  it("пробрасывает detail ошибки бэкенда", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(422, { detail: "Дата должна быть в формате ГГГГ-ММ-ДД" }),
    );
    await expect(api("/api/schedule")).rejects.toMatchObject({
      status: 422,
      message: "Дата должна быть в формате ГГГГ-ММ-ДД",
    });
  });

  it("204 не пытается парсить JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    await expect(deleteLesson("x")).resolves.toBeUndefined();
  });

  it("createLesson отправляет JSON с Content-Type", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(200, { id: "1", subject: "Сети" }));
    const lesson = await createLesson({ date: "2026-11-02", subject: "Сети", start_time: "12:20" });
    expect(lesson.id).toBe("1");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toMatchObject({ subject: "Сети", start_time: "12:20" });
  });
});

describe("форматирование", () => {
  it("пустые значения заменяются прочерком", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
    expect(formatDate("")).toBe("—");
  });

  it("невалидная дата возвращается как есть", () => {
    expect(formatDate("не дата")).toBe("не дата");
  });

  it("валидная дата форматируется как «день месяц»", () => {
    expect(formatDate("2026-11-02")).toBe("02 ноября");
  });

  it("дата со временем показывает часы и минуты", () => {
    expect(formatDateTime("2026-11-02T14:35:00Z")).toMatch(/\d{2}\.\d{2}, \d{2}:\d{2}/);
  });

  it("todayIso отдаёт ISO-день", () => {
    expect(todayIso()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(todayIso()).toBe(new Date().toISOString().slice(0, 10));
  });
});
