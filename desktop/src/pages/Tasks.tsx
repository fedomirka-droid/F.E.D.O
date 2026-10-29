import { useCallback, useEffect, useState } from "react";
import { del, formatDateTime, get, patch, post, type Task } from "../api";
import { Badge, Empty, Field, Modal, Spinner, statusTone, useAsyncAction, useToast } from "../ui";

const FILTERS = [
  { key: "active", label: "Активные" },
  { key: "todo", label: "К выполнению" },
  { key: "in_progress", label: "В работе" },
  { key: "done", label: "Готовые" },
  { key: "all", label: "Все" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

export function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [filter, setFilter] = useState<FilterKey>("active");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Task | null>(null);
  const [form, setForm] = useState({ title: "", description: "", priority: "normal", due_at: "", planned_minutes: 30, category: "" });
  const { busy, run } = useAsyncAction();
  const toast = useToast();

  const load = useCallback(async () => {
    const data = await get<{ tasks: Task[] }>("/api/tasks");
    setTasks(data.tasks);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const visible = tasks.filter((task) => {
    if (filter === "all") return true;
    if (filter === "active") return task.status !== "done" && task.status !== "skipped";
    return task.status === filter;
  });

  const submit = () =>
    run(async () => {
      if (!form.title.trim()) throw new Error("Введите название");
      const payload = {
        title: form.title.trim(),
        description: form.description,
        priority: form.priority,
        planned_minutes: Number(form.planned_minutes) || 0,
        category: form.category,
        due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
      };
      if (editing) {
        await patch(`/api/tasks/${editing.id}`, payload);
      } else {
        await post("/api/tasks", payload);
      }
      setCreating(false);
      setEditing(null);
      setForm({ title: "", description: "", priority: "normal", due_at: "", planned_minutes: 30, category: "" });
      await load();
      toast.success(editing ? "Задача обновлена" : "Задача создана");
    }, "Не удалось сохранить задачу");

  const act = (task: Task, action: string, minutes = 0) =>
    run(async () => {
      await post(`/api/tasks/${task.id}/action/${action}${minutes ? `?minutes=${minutes}` : ""}`);
      await load();
    }, "Не удалось выполнить действие");

  const remove = (task: Task) =>
    run(async () => {
      await del(`/api/tasks/${task.id}`);
      await load();
      toast.success("Задача удалена");
    }, "Не удалось удалить задачу");

  const startEdit = (task: Task) => {
    setEditing(task);
    setCreating(true);
    setForm({
      title: task.title,
      description: task.description,
      priority: task.priority,
      due_at: task.due_at ? task.due_at.slice(0, 16) : "",
      planned_minutes: task.planned_minutes,
      category: task.category,
    });
  };

  return (
    <>
      <div className="row between">
        <div className="row">
          {FILTERS.map((item) => (
            <button key={item.key}
                    className={`chip ${filter === item.key ? "active" : ""}`}
                    onClick={() => setFilter(item.key)}>
              {item.label}
            </button>
          ))}
        </div>
        <button className="btn primary" onClick={() => { setEditing(null); setCreating(true); }}>
          ＋ Новая задача
        </button>
      </div>

      <div className="card">
        {loading ? (
          <div className="row"><Spinner /> <span className="muted">Загрузка задач…</span></div>
        ) : visible.length === 0 ? (
          <Empty text="Задач нет. Нажми «Новая задача»." />
        ) : (
          <div className="list">
            {visible.map((task) => (
              <div className="list-item" key={task.id}>
                <span className={`dot ${task.priority === "high" ? "danger" : task.priority === "normal" ? "warn" : "offline"}`} />
                <div className="grow">
                  <div className={task.status === "done" ? "done truncate" : "truncate"}>{task.title}</div>
                  <div className="small faint">
                    {task.description ? `${task.description.slice(0, 70)} · ` : ""}
                    {task.due_at ? `срок ${formatDateTime(task.due_at)}` : "без срока"}
                    {" · "}план {task.planned_minutes || 0} мин
                    {task.actual_minutes ? ` · факт ${task.actual_minutes} мин` : ""}
                    {task.category ? ` · ${task.category}` : ""}
                  </div>
                </div>
                <Badge tone={statusTone(task.status) || ""}>{task.status.replace("_", " ")}</Badge>
                <div className="row" style={{ gap: 6 }}>
                  {task.status !== "in_progress" && task.status !== "done" ? (
                    <button className="btn small" disabled={busy} onClick={() => act(task, "start")}>▶</button>
                  ) : null}
                  {task.status !== "done" ? (
                    <button className="btn small primary" disabled={busy} onClick={() => act(task, "complete")}>✓</button>
                  ) : null}
                  <button className="btn small" disabled={busy} title="Продлить план на 15 минут"
                          onClick={() => act(task, "extend", 15)}>+15 план</button>
                  <button className="btn small" disabled={busy} title="Отложить срок и напоминание на 15 минут"
                          onClick={() => act(task, "snooze", 15)}>⏰ +15 мин</button>
                  <button className="btn small" disabled={busy} title="Записать 15 минут факта"
                          onClick={() => act(task, "time", 15)}>⏱ факт</button>
                  <button className="btn small" disabled={busy} onClick={() => act(task, "skip")}>⏭</button>
                  <button className="btn small ghost" onClick={() => startEdit(task)}>✎</button>
                  <button className="btn small danger" disabled={busy} onClick={() => remove(task)}>✕</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {creating ? (
        <Modal title={editing ? "Редактировать задачу" : "Новая задача"}
               onClose={() => { setCreating(false); setEditing(null); }}
               footer={
                 <>
                   <button className="btn ghost" onClick={() => { setCreating(false); setEditing(null); }}>Отмена</button>
                   <button className="btn primary" onClick={submit} disabled={busy}>Сохранить</button>
                 </>
               }>
          <Field label="Название">
            <input className="input" value={form.title}
                   onChange={(event) => setForm({ ...form, title: event.target.value })} />
          </Field>
          <Field label="Описание">
            <textarea className="textarea" value={form.description}
                      onChange={(event) => setForm({ ...form, description: event.target.value })} />
          </Field>
          <div className="grid cols-2">
            <Field label="Приоритет">
              <select className="select" value={form.priority}
                      onChange={(event) => setForm({ ...form, priority: event.target.value })}>
                <option value="low">Низкий</option>
                <option value="normal">Обычный</option>
                <option value="high">Высокий</option>
              </select>
            </Field>
            <Field label="Плановое время (мин)">
              <input className="input" type="number" min={0} value={form.planned_minutes}
                     onChange={(event) => setForm({ ...form, planned_minutes: Number(event.target.value) })} />
            </Field>
            <Field label="Дедлайн">
              <input className="input" type="datetime-local" value={form.due_at}
                     onChange={(event) => setForm({ ...form, due_at: event.target.value })} />
            </Field>
            <Field label="Категория">
              <input className="input" value={form.category}
                     onChange={(event) => setForm({ ...form, category: event.target.value })} />
            </Field>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
