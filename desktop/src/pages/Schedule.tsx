import { useCallback, useEffect, useState } from "react";
import { get, todayIso, uploadSchedule, type Lesson } from "../api";
import { Badge, Empty, Field, Spinner, useAsyncAction, useToast } from "../ui";

export function Schedule() {
  const [day, setDay] = useState<"today" | "tomorrow">("today");
  const [entries, setEntries] = useState<Lesson[]>([]);
  const [dateLabel, setDateLabel] = useState("");
  const [group, setGroup] = useState("ИС-21");
  const [dateOverride, setDateOverride] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<{ imported: number; warnings: string[] } | null>(null);
  const { busy, run } = useAsyncAction();
  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    const data = await get<{ date: string; entries: Lesson[] }>(
      `/api/schedule/${day}?group=${encodeURIComponent(group)}`,
    );
    setEntries(data.entries);
    setDateLabel(data.date);
    setLoading(false);
  }, [day, group]);

  useEffect(() => {
    load().catch(() => setLoading(false));
  }, [load]);

  const doImport = () =>
    run(async () => {
      if (!file) throw new Error("Выберите файл .xlsx или .xls");
      const result = await uploadSchedule(file, group, dateOverride);
      setReport({ imported: result.imported, warnings: result.warnings || [] });
      if (result.imported) toast.success(`Импортировано занятий: ${result.imported}`);
      else toast.error("Занятия не найдены — проверь файл");
      setFile(null);
      await load();
    }, "Ошибка импорта расписания");

  return (
    <>
      <div className="grid cols-2">
        <div className="card">
          <div className="card-title"><h3>Расписание группы {group}</h3></div>
          <div className="row" style={{ marginBottom: 12 }}>
            <button className={`chip ${day === "today" ? "active" : ""}`} onClick={() => setDay("today")}>Сегодня</button>
            <button className={`chip ${day === "tomorrow" ? "active" : ""}`} onClick={() => setDay("tomorrow")}>Завтра</button>
            <span className="spacer" />
            <span className="small faint">{dateLabel}</span>
          </div>
          {loading ? (
            <div className="row"><Spinner /> <span className="muted">Загрузка…</span></div>
          ) : entries.length === 0 ? (
            <Empty text="Занятий нет. Импортируй расписание справа." />
          ) : (
            <div className="list">
              {entries.map((lesson) => (
                <div className="list-item" key={lesson.id}>
                  <span className="mono faint" style={{ minWidth: 86 }}>
                    {lesson.start_time || "—"}<br />{lesson.end_time || ""}
                  </span>
                  <div className="grow">
                    <div className="truncate">{lesson.subject}</div>
                    <div className="small faint">
                      {[lesson.teacher, lesson.room, lesson.lesson_type].filter(Boolean).join(" · ") || "—"}
                    </div>
                  </div>
                  <Badge>пара {lesson.slot}</Badge>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title"><h3>Импорт XLS / XLSX</h3></div>
          <div className="stack">
            <Field label="Группа" hint="Парсер ищет столбец этой группы и не читает соседние">
              <input className="input" value={group} onChange={(event) => setGroup(event.target.value)} />
            </Field>
            <Field label="Дата (необязательно)" hint="Если в файле нет даты — укажи её здесь">
              <input className="input" type="date" value={dateOverride}
                     onChange={(event) => setDateOverride(event.target.value)} />
            </Field>
            <Field label="Файл расписания">
              <input className="input" type="file" accept=".xlsx,.xls"
                     onChange={(event) => setFile(event.target.files?.[0] || null)} />
            </Field>
            <button className="btn primary" onClick={doImport} disabled={busy || !file}>
              {busy ? <Spinner /> : null} Импортировать
            </button>
            <p className="hint">
              Файл не покидает устройство. Если данные не распознаны, занятия не выдумываются —
              появятся предупреждения.
            </p>
            {report ? (
              <div className="stack small">
                <div className="row between">
                  <span className="muted">Импортировано</span>
                  <Badge tone={report.imported ? "success" : "warning"}>{report.imported}</Badge>
                </div>
                {report.warnings.map((warning, index) => (
                  <div className="badge warning" key={index} style={{ whiteSpace: "normal" }}>{warning}</div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title"><h3>Всё расписание</h3></div>
        <AllEntries group={group} />
      </div>
    </>
  );
}

function AllEntries({ group }: { group: string }) {
  const [entries, setEntries] = useState<Lesson[]>([]);
  useEffect(() => {
    get<{ entries: Lesson[] }>(`/api/schedule?group=${encodeURIComponent(group)}`)
      .then((data) => setEntries(data.entries))
      .catch(() => setEntries([]));
  }, [group]);

  if (entries.length === 0) return <Empty text="Расписание не импортировано" />;

  const byDate = new Map<string, Lesson[]>();
  for (const entry of entries) byDate.set(entry.date, [...(byDate.get(entry.date) || []), entry]);

  return (
    <div className="stack">
      {[...byDate.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, lessons]) => (
        <div key={date}>
          <div className="row small faint" style={{ marginBottom: 6 }}>
            <strong>{date}</strong> · {date === todayIso() ? "сегодня" : ""}
          </div>
          <div className="list">
            {lessons.map((lesson) => (
              <div className="list-item" key={lesson.id}>
                <span className="mono faint">{lesson.start_time}–{lesson.end_time}</span>
                <div className="grow truncate">{lesson.subject}</div>
                <span className="small faint">{[lesson.room, lesson.teacher].filter(Boolean).join(" · ")}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
