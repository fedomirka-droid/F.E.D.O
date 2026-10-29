import { useCallback, useEffect, useMemo, useState } from "react";
import { del, formatDateTime, get, patch, post, type Event } from "../api";
import { Badge, Empty, Field, Modal, Spinner, useAsyncAction, useToast } from "../ui";

function monthMatrix(year: number, month: number) {
  const first = new Date(year, month, 1);
  const startOffset = (first.getDay() + 6) % 7;
  const days: { date: Date; inMonth: boolean }[] = [];
  for (let i = 0; i < 42; i += 1) {
    const date = new Date(year, month, 1 - startOffset + i);
    days.push({ date, inMonth: date.getMonth() === month });
  }
  return days;
}

const iso = (date: Date) =>
  new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 19);

export function Calendar() {
  const [cursor, setCursor] = useState(() => new Date());
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string>("");
  const [editing, setEditing] = useState<Event | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: "", starts_at: "", ends_at: "", location: "", description: "" });
  const { busy, run } = useAsyncAction();
  const toast = useToast();

  const days = useMemo(() => monthMatrix(cursor.getFullYear(), cursor.getMonth()), [cursor]);
  const rangeStart = new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1);
  const rangeEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 2, 0);

  const load = useCallback(async () => {
    const data = await get<{ events: Event[] }>(
      `/api/events?start=${encodeURIComponent(iso(rangeStart))}&end=${encodeURIComponent(iso(rangeEnd))}`,
    );
    setEvents(data.events);
    setLoading(false);
  }, [cursor]);

  useEffect(() => {
    load();
  }, [load]);

  const byDay = useMemo(() => {
    const map = new Map<string, Event[]>();
    for (const event of events) {
      const key = event.starts_at.slice(0, 10);
      map.set(key, [...(map.get(key) || []), event]);
    }
    return map;
  }, [events]);

  const openCreate = (dayIso?: string) => {
    setEditing(null);
    setForm({
      title: "",
      starts_at: `${dayIso || new Date().toISOString().slice(0, 10)}T10:00`,
      ends_at: "",
      location: "",
      description: "",
    });
    setOpen(true);
  };

  const submit = () =>
    run(async () => {
      if (!form.title.trim()) throw new Error("Введите название");
      const payload = {
        title: form.title.trim(),
        description: form.description,
        starts_at: new Date(form.starts_at).toISOString(),
        ends_at: form.ends_at ? new Date(form.ends_at).toISOString() : null,
        location: form.location,
      };
      if (editing) await patch(`/api/events/${editing.id}`, payload);
      else await post("/api/events", payload);
      setOpen(false);
      await load();
      toast.success(editing ? "Событие обновлено" : "Событие создано");
    }, "Не удалось сохранить событие");

  const remove = (event: Event) =>
    run(async () => {
      await del(`/api/events/${event.id}`);
      await load();
      toast.success("Событие удалено");
    }, "Не удалось удалить событие");

  const selectedEvents = selected ? byDay.get(selected) || [] : [];

  return (
    <>
      <div className="row between">
        <div className="row">
          <button className="btn small" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>←</button>
          <h2 style={{ minWidth: 190, textAlign: "center" }}>
            {cursor.toLocaleDateString("ru-RU", { month: "long", year: "numeric" })}
          </h2>
          <button className="btn small" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>→</button>
          <button className="btn small ghost" onClick={() => setCursor(new Date())}>Сегодня</button>
        </div>
        <button className="btn primary" onClick={() => openCreate()}>＋ Событие</button>
      </div>

      {loading ? (
        <div className="row"><Spinner /> <span className="muted">Загрузка календаря…</span></div>
      ) : (
        <div className="card">
          <div className="calendar-head">
            {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((day) => <div key={day}>{day}</div>)}
          </div>
          <div className="calendar-grid">
            {days.map(({ date, inMonth }) => {
              const key = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
              const isToday = key === new Date().toISOString().slice(0, 10);
              return (
                <div key={key}
                     className={`calendar-cell ${inMonth ? "" : "dim"} ${isToday ? "today" : ""} ${selected === key ? "today" : ""}`}
                     onClick={() => { setSelected(key); if (!byDay.get(key)?.length) openCreate(key); }}>
                  <span className="day">{date.getDate()}</span>
                  {(byDay.get(key) || []).slice(0, 2).map((event) => (
                    <span className="calendar-event" key={event.id}>{event.title}</span>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-title">
          <h3>{selected ? `События ${selected}` : "Выберите день или создайте событие"}</h3>
          {selected ? <button className="btn small" onClick={() => openCreate(selected)}>＋ В этот день</button> : null}
        </div>
        {selectedEvents.length === 0 ? (
          <Empty text={selected ? "На этот день событий нет" : "Клик по дню покажет события"} />
        ) : (
          <div className="list">
            {selectedEvents.map((event) => (
              <div className="list-item" key={event.id}>
                <div className="grow">
                  <div className="truncate">{event.title}</div>
                  <div className="small faint">
                    {formatDateTime(event.starts_at)} {event.ends_at ? `— ${formatDateTime(event.ends_at)}` : ""}
                    {event.location ? ` · ${event.location}` : ""}
                  </div>
                </div>
                <button className="btn small" onClick={() => {
                  setEditing(event);
                  setForm({
                    title: event.title,
                    starts_at: event.starts_at.slice(0, 16),
                    ends_at: event.ends_at ? event.ends_at.slice(0, 16) : "",
                    location: event.location,
                    description: event.description,
                  });
                  setOpen(true);
                }}>✎</button>
                <button className="btn small danger" disabled={busy} onClick={() => remove(event)}>✕</button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title"><h3>Все события месяца</h3><Badge>{events.length}</Badge></div>
        {events.length === 0 ? (
          <Empty text="Событий пока нет" />
        ) : (
          <div className="list scroll-y">
            {events.map((event) => (
              <div className="list-item" key={event.id}>
                <span className="mono faint">{new Date(event.starts_at).toLocaleDateString("ru-RU")}</span>
                <div className="grow truncate">{event.title}</div>
                <span className="small faint">{event.location}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {open ? (
        <Modal title={editing ? "Редактировать событие" : "Новое событие"} onClose={() => setOpen(false)}
               footer={<>
                 <button className="btn ghost" onClick={() => setOpen(false)}>Отмена</button>
                 <button className="btn primary" onClick={submit} disabled={busy}>Сохранить</button>
               </>}>
          <Field label="Название">
            <input className="input" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
          </Field>
          <div className="grid cols-2">
            <Field label="Начало">
              <input className="input" type="datetime-local" value={form.starts_at}
                     onChange={(event) => setForm({ ...form, starts_at: event.target.value })} />
            </Field>
            <Field label="Конец">
              <input className="input" type="datetime-local" value={form.ends_at}
                     onChange={(event) => setForm({ ...form, ends_at: event.target.value })} />
            </Field>
          </div>
          <Field label="Место">
            <input className="input" value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} />
          </Field>
          <Field label="Описание">
            <textarea className="textarea" value={form.description}
                      onChange={(event) => setForm({ ...form, description: event.target.value })} />
          </Field>
        </Modal>
      ) : null}
    </>
  );
}
