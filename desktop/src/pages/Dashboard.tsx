import { useCallback, useEffect, useState } from "react";
import {
  formatDate,
  formatDateTime,
  get,
  post,
  type AiModels,
  type AiUsage,
  type Device,
  type Lesson,
  type SyncStatus,
  type Task,
} from "../api";
import type { PageKey } from "../components/Layout";
import { Badge, Bar, Empty, Spinner, useToast } from "../ui";

export function Dashboard({ onNavigate }: { onNavigate: (page: PageKey) => void }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [models, setModels] = useState<AiModels | null>(null);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const toast = useToast();

  const load = useCallback(async () => {
    const [today, schedule, deviceList, modelList, usageData, syncData] = await Promise.allSettled([
      get<{ tasks: Task[] }>("/api/tasks/today"),
      get<{ entries: Lesson[] }>("/api/schedule/today"),
      get<{ devices: Device[] }>("/api/devices"),
      get<AiModels>("/api/ai/models"),
      get<AiUsage>("/api/ai/usage"),
      get<SyncStatus>("/api/sync/status"),
    ]);
    if (today.status === "fulfilled") setTasks(today.value.tasks);
    if (schedule.status === "fulfilled") setLessons(schedule.value.entries);
    if (deviceList.status === "fulfilled") setDevices(deviceList.value.devices);
    if (modelList.status === "fulfilled") setModels(modelList.value);
    if (usageData.status === "fulfilled") setUsage(usageData.value);
    if (syncData.status === "fulfilled") setSync(syncData.value);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, [load]);

  const act = async (task: Task, action: string) => {
    setBusyId(task.id);
    try {
      await post(`/api/tasks/${task.id}/action/${action}`);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Ошибка");
    } finally {
      setBusyId("");
    }
  };

  const hour = new Date().getHours();
  const greeting = hour < 6 ? "Доброй ночи" : hour < 12 ? "Доброе утро" : hour < 18 ? "Добрый день" : "Добрый вечер";

  if (loading) {
    return <div className="row"><Spinner /> <span className="muted">Загрузка панели…</span></div>;
  }

  return (
    <>
      <div className="card">
        <div className="row between">
          <div>
            <h1>{greeting}, товарищ.</h1>
            <p className="muted small">
              {new Date().toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" })} ·
              {" "}задач сегодня: {tasks.length} · пар: {lessons.length}
            </p>
          </div>
          <div className="row">
            <button className="btn primary small" onClick={() => onNavigate("assistant")}>✦ Спросить AI</button>
            <button className="btn small" onClick={() => onNavigate("tasks")}>＋ Задача</button>
          </div>
        </div>
      </div>

      <div className="grid cols-4">
        <div className="card">
          <div className="metric">
            <span className="label">Задачи</span>
            <span className="value">{tasks.filter((t) => t.status !== "done").length}</span>
            <span className="small muted">{tasks.filter((t) => t.status === "in_progress").length} в работе</span>
          </div>
        </div>
        <div className="card">
          <div className="metric">
            <span className="label">AI сегодня</span>
            <span className="value">{usage?.today_requests ?? 0}</span>
            <span className="small muted">облако: {usage?.today_cloud_requests ?? 0}</span>
          </div>
        </div>
        <div className="card">
          <div className="metric">
            <span className="label">Синхронизация</span>
            <span className="value" style={{ fontSize: 18 }}>
              {sync?.hub_configured ? (sync.online ? "Онлайн" : "Ожидание") : "Локально"}
            </span>
            <span className="small muted">
              {sync?.pending_operations ? `в очереди: ${sync.pending_operations}` : "очередь пуста"}
            </span>
          </div>
        </div>
        <div className="card">
          <div className="metric">
            <span className="label">Устройства</span>
            <span className="value">{devices.filter((d) => d.status === "online").length}/{devices.length}</span>
            <span className="small muted">онлайн</span>
          </div>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-title">
            <h3>Задачи на сегодня</h3>
            <button className="btn ghost small" onClick={() => onNavigate("tasks")}>Все →</button>
          </div>
          {tasks.length === 0 ? (
            <Empty text="На сегодня задач нет" />
          ) : (
            <div className="list">
              {tasks.slice(0, 6).map((task) => (
                <div className="list-item" key={task.id}>
                  <span className={`dot ${task.priority === "high" ? "danger" : task.priority === "normal" ? "warn" : "offline"}`} />
                  <div className="grow">
                    <div className={task.status === "done" ? "done truncate" : "truncate"}>{task.title}</div>
                    <div className="small faint">
                      {task.due_at ? `срок ${formatDateTime(task.due_at)}` : "без срока"}
                      {task.planned_minutes ? ` · план ${task.planned_minutes} мин` : ""}
                    </div>
                  </div>
                  {task.status === "in_progress" ? (
                    <button className="btn small primary" disabled={busyId === task.id}
                            onClick={() => act(task, "complete")}>Завершить</button>
                  ) : task.status === "done" ? (
                    <Badge tone="success">готово</Badge>
                  ) : (
                    <button className="btn small" disabled={busyId === task.id}
                            onClick={() => act(task, "start")}>Начать</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">
            <h3>Ближайшие занятия</h3>
            <button className="btn ghost small" onClick={() => onNavigate("schedule")}>Расписание →</button>
          </div>
          {lessons.length === 0 ? (
            <Empty text="На сегодня занятий нет (или расписание не импортировано)" />
          ) : (
            <div className="list">
              {lessons.slice(0, 6).map((lesson) => (
                <div className="list-item" key={lesson.id}>
                  <span className="mono faint">
                    {lesson.start_time || "—"}
                    <br />
                    {lesson.end_time || ""}
                  </span>
                  <div className="grow">
                    <div className="truncate">{lesson.subject}</div>
                    <div className="small faint">
                      {[lesson.teacher, lesson.room, lesson.lesson_type].filter(Boolean).join(" · ") || "—"}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid cols-3">
        <div className="card">
          <div className="card-title"><h3>Состояние AI</h3></div>
          <div className="stack small">
            <div className="row between">
              <span className="muted">Режим</span>
              <Badge tone="accent">{models?.mode ?? "—"}</Badge>
            </div>
            <div className="row between">
              <span className="muted">Локальная модель</span>
              <span>{models?.local.available ? models.local.selected || "готова" : "недоступна"}</span>
            </div>
            <div className="row between">
              <span className="muted">Облако</span>
              <Badge tone={models?.allow_cloud ? "warning" : "success"}>
                {models?.allow_cloud ? "разрешено" : "запрещено"}
              </Badge>
            </div>
            <div className="row between">
              <span className="muted">Домашний узел</span>
              <span>{models?.remote_node.available ? "онлайн" : "не подключён"}</span>
            </div>
            <div>
              <div className="row between small muted">
                <span>Расход за месяц</span>
                <span>{usage?.month_cost ?? 0}</span>
              </div>
              <Bar value={usage?.monthly_budget ? (usage.month_cost / usage.monthly_budget) * 100 : 0}
                   tone={usage?.monthly_budget && usage.month_cost >= usage.monthly_budget ? "danger" : "success"} />
            </div>
            <button className="btn small" onClick={() => onNavigate("settings")}>Настройки AI →</button>
          </div>
        </div>

        <div className="card">
          <div className="card-title"><h3>Синхронизация</h3></div>
          <div className="stack small">
            <div className="row between">
              <span className="muted">HUB</span>
              <span className="truncate mono">{sync?.hub_url || "не настроен"}</span>
            </div>
            <div className="row between">
              <span className="muted">Последний push</span>
              <span>{formatDateTime(sync?.last_push_at)}</span>
            </div>
            <div className="row between">
              <span className="muted">Последний pull</span>
              <span>{formatDateTime(sync?.last_pull_at)}</span>
            </div>
            <div className="row between">
              <span className="muted">Конфликты</span>
              <Badge tone={sync?.open_conflicts ? "danger" : "success"}>{sync?.open_conflicts ?? 0}</Badge>
            </div>
            {sync?.last_error ? <div className="badge danger small">{sync.last_error}</div> : null}
          </div>
        </div>

        <div className="card">
          <div className="card-title"><h3>Устройства</h3></div>
          {devices.length === 0 ? (
            <Empty text="Устройства не добавлены" />
          ) : (
            <div className="list">
              {devices.slice(0, 4).map((device) => (
                <div className="list-item" key={device.id}>
                  <span className={`dot ${device.status === "online" ? "online" : device.status === "sleeping" ? "warn" : "offline"}`} />
                  <div className="grow">
                    <div className="truncate">{device.name}</div>
                    <div className="small faint">
                      {device.kind} · {formatDate(device.last_seen_at)}
                    </div>
                  </div>
                  {device.ai_available ? <Badge tone="accent">AI</Badge> : null}
                </div>
              ))}
            </div>
          )}
          <button className="btn small" style={{ marginTop: 10 }} onClick={() => onNavigate("devices")}>
            Управление устройствами →
          </button>
        </div>
      </div>
    </>
  );
}
