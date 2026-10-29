import { useCallback, useEffect, useRef, useState } from "react";
import {
  createLesson,
  deleteLesson,
  get,
  todayIso,
  uploadSchedule,
  type Lesson,
} from "../api";
import { Badge, Empty, Field, Spinner, useAsyncAction, useToast } from "../ui";

const NOTIFY_KEY = "fedo_notify_classes";
const NOTIFY_LEAD_MINUTES = 10;
const SENT_KEY = "fedo_notified_classes";

export function Schedule() {
  const [day, setDay] = useState<"today" | "tomorrow">("today");
  const [entries, setEntries] = useState<Lesson[]>([]);
  const [dateLabel, setDateLabel] = useState("");
  const [group, setGroup] = useState("ИС-21");
  const [dateOverride, setDateOverride] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<{ imported: number; warnings: string[] } | null>(null);
  const [notify, setNotify] = useState(() => localStorage.getItem(NOTIFY_KEY) === "1");
  const [permission, setPermission] = useState<NotificationPermission>(
    typeof Notification !== "undefined" ? Notification.permission : "denied",
  );
  const sentRef = useRef<Set<string>>(new Set(JSON.parse(localStorage.getItem(SENT_KEY) || "[]")));
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

  const enableNotifications = async () => {
    if (typeof Notification === "undefined") {
      toast.error("Системные уведомления недоступны в этом окружении");
      return;
    }
    let result = Notification.permission;
    if (result === "default") result = await Notification.requestPermission();
    setPermission(result);
    if (result === "granted") {
      localStorage.setItem(NOTIFY_KEY, "1");
      setNotify(true);
      new Notification("F.E.D.O.", { body: `Напоминания о парах включены (за ${NOTIFY_LEAD_MINUTES} мин).` });
    } else {
      toast.error("Браузер/система запретила уведомления — включи их в настройках Windows");
    }
  };

  const disableNotifications = () => {
    localStorage.setItem(NOTIFY_KEY, "0");
    setNotify(false);
  };

  // Напоминания о занятиях: проверяем расписание на сегодня раз в минуту.
  useEffect(() => {
    if (!notify || permission !== "granted") return;
    const check = async () => {
      try {
        const data = await get<{ date: string; entries: Lesson[] }>(
          `/api/schedule/today?group=${encodeURIComponent(group)}`,
        );
        const now = new Date();
        const nowMinutes = now.getHours() * 60 + now.getMinutes();
        for (const lesson of data.entries) {
          if (!lesson.start_time) continue;
          const [hours, minutes] = lesson.start_time.split(":").map(Number);
          const startMinutes = hours * 60 + (minutes || 0);
          const delta = startMinutes - nowMinutes;
          const key = `${lesson.date}:${lesson.start_time}:${lesson.subject}`;
          if (delta > 0 && delta <= NOTIFY_LEAD_MINUTES && !sentRef.current.has(key)) {
            sentRef.current.add(key);
            localStorage.setItem(SENT_KEY, JSON.stringify([...sentRef.current].slice(-200)));
            new Notification(`Через ${delta} мин — ${lesson.subject}`, {
              body: [lesson.start_time, lesson.room, lesson.teacher].filter(Boolean).join(" · "),
              tag: key,
            });
          }
        }
      } catch {
        // расписание недоступно — просто подождём следующего тика
      }
    };
    check();
    const timer = window.setInterval(check, 60000);
    return () => window.clearInterval(timer);
  }, [notify, permission, group]);

  const remove = (lesson: Lesson) =>
    run(async () => {
      await deleteLesson(lesson.id);
      toast.success("Занятие удалено");
      await load();
    }, "Не удалось удалить занятие");

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
          <div className="row between small" style={{ marginBottom: 10 }}>
            <span className="muted">
              Уведомления о парах{notify && permission === "granted"
                ? ` · за ${NOTIFY_LEAD_MINUTES} мин` : " выключены"}
            </span>
            {notify && permission === "granted" ? (
              <button className="btn small ghost" onClick={disableNotifications}>Выключить</button>
            ) : (
              <button className="btn small" onClick={enableNotifications}>
                Включить напоминания
              </button>
            )}
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
                  <button className="btn small ghost" title="Удалить занятие"
                          onClick={() => remove(lesson)} disabled={busy}>✕</button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title"><h3>Добавить занятие вручную</h3></div>
          <ManualLesson group={group} onCreated={load} />
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

function ManualLesson({ group, onCreated }: { group: string; onCreated: () => Promise<void> }) {
  const [date, setDate] = useState(todayIso());
  const [subject, setSubject] = useState("");
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("10:30");
  const [teacher, setTeacher] = useState("");
  const [room, setRoom] = useState("");
  const { busy, run } = useAsyncAction();
  const toast = useToast();

  const save = () =>
    run(async () => {
      await createLesson({
        date,
        subject: subject.trim(),
        start_time: start,
        end_time: end,
        teacher: teacher.trim(),
        room: room.trim(),
        group_name: group,
      });
      toast.success("Занятие добавлено");
      setSubject("");
      setTeacher("");
      setRoom("");
      await onCreated();
    }, "Не удалось добавить занятие");

  return (
    <div className="stack">
      <Field label="Дата">
        <input className="input" type="date" value={date}
               onChange={(event) => setDate(event.target.value)} />
      </Field>
      <Field label="Предмет">
        <input className="input" value={subject} placeholder="Например, Базы данных"
               onChange={(event) => setSubject(event.target.value)} />
      </Field>
      <div className="row">
        <Field label="Начало">
          <input className="input" type="time" value={start}
                 onChange={(event) => setStart(event.target.value)} />
        </Field>
        <Field label="Конец">
          <input className="input" type="time" value={end}
                 onChange={(event) => setEnd(event.target.value)} />
        </Field>
      </div>
      <div className="row">
        <Field label="Преподаватель">
          <input className="input" value={teacher}
                 onChange={(event) => setTeacher(event.target.value)} />
        </Field>
        <Field label="Кабинет">
          <input className="input" value={room}
                 onChange={(event) => setRoom(event.target.value)} />
        </Field>
      </div>
      <button className="btn primary" onClick={save} disabled={busy || !subject.trim() || !date}>
        {busy ? <Spinner /> : null} Добавить
      </button>
      <p className="hint">Номер пары определяется по времени начала автоматически.</p>
    </div>
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
