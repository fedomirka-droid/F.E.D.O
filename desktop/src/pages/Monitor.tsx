import { useEffect, useState } from "react";
import { formatDateTime, get, type SystemSnapshot } from "../api";
import { Badge, Bar, Empty, Spinner } from "../ui";

export function Monitor() {
  const [data, setData] = useState<SystemSnapshot | null>(null);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState("");

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const snapshot = await get<SystemSnapshot>("/api/monitor/system");
        if (!alive) return;
        setData(snapshot);
        setUpdated(new Date().toLocaleTimeString("ru-RU"));
        setError("");
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "Ошибка монитора");
      }
    };
    load();
    const timer = window.setInterval(load, 4000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!data) {
    return error
      ? <div className="card"><Empty text={`Монитор недоступен: ${error}`} /></div>
      : <div className="row"><Spinner /> <span className="muted">Сбор данных монитора…</span></div>;
  }

  const snapshot = data.snapshot as Record<string, any>;
  const gpu = snapshot.gpu || {};
  const processes: { pid: number; name: string; cpu: number; mem: number }[] = snapshot.top_processes || [];
  const tone = (value: number) => (value > 88 ? "danger" : value > 68 ? "warning" : "success");

  return (
    <>
      <div className="row between">
        <p className="muted small">
          Источник: собственный монитор F.E.D.O. Core {data.core.version} ({data.core.build})
          {data.core.available ? "" : " — Core недоступен"}
        </p>
        <span className="small faint">обновлено {updated}</span>
      </div>

      <div className="grid cols-4">
        <div className="card">
          <div className="metric">
            <span className="label">CPU</span>
            <span className="value">{Math.round(snapshot.cpu_percent ?? 0)}%</span>
            <span className="small muted">{snapshot.cpu_count ?? 0} ядер
              {snapshot.cpu_temperature ? ` · ${Math.round(snapshot.cpu_temperature)}°C` : ""}</span>
          </div>
          <Bar value={snapshot.cpu_percent ?? 0} tone={tone(snapshot.cpu_percent ?? 0) as any} />
        </div>
        <div className="card">
          <div className="metric">
            <span className="label">Память</span>
            <span className="value">{Math.round(snapshot.ram_percent ?? 0)}%</span>
            <span className="small muted">{snapshot.ram_used_gb} / {snapshot.ram_total_gb} ГБ</span>
          </div>
          <Bar value={snapshot.ram_percent ?? 0} tone={tone(snapshot.ram_percent ?? 0) as any} />
        </div>
        <div className="card">
          <div className="metric">
            <span className="label">Диск</span>
            <span className="value">{Math.round(snapshot.disk_percent ?? 0)}%</span>
            <span className="small muted">{snapshot.disk_used_gb} / {snapshot.disk_total_gb} ГБ</span>
          </div>
          <Bar value={snapshot.disk_percent ?? 0} tone={tone(snapshot.disk_percent ?? 0) as any} />
        </div>
        <div className="card">
          <div className="metric">
            <span className="label">GPU</span>
            <span className="value" style={{ fontSize: 18 }}>{gpu.available ? gpu.name : "нет"}</span>
            <span className="small muted">
              {gpu.available
                ? `${Math.round((gpu.load ?? 0) * 100)}% · VRAM ${gpu.vram_used}/${gpu.vram_total} ГБ`
                : gpu.note || "не обнаружен"}
            </span>
          </div>
          {gpu.available ? <Bar value={(gpu.load ?? 0) * 100} tone="warning" /> : null}
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-title"><h3>Сводка F.E.D.O.</h3><Badge tone="accent">{data.role}</Badge></div>
          <pre className="mono small" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{data.summary}</pre>
        </div>
        <div className="card">
          <div className="card-title"><h3>Топ процессов</h3><span className="small faint">{formatDateTime(data.collected_at)}</span></div>
          {processes.length === 0 ? <Empty text="Нет данных" /> : (
            <div className="list">
              {processes.map((process) => (
                <div className="list-item" key={process.pid}>
                  <div className="grow truncate">{process.name}</div>
                  <span className="small faint">PID {process.pid}</span>
                  <Badge tone={process.cpu > 50 ? "danger" : ""}>{process.cpu.toFixed(0)}% CPU</Badge>
                  <Badge>{process.mem.toFixed(0)}% RAM</Badge>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title"><h3>Платформа</h3></div>
        <dl className="kv">
          <dt>Система</dt><dd>{snapshot.platform}</dd>
          <dt>Хост</dt><dd>{snapshot.hostname}</dd>
          <dt>Время монитора</dt><dd>{snapshot.time}</dd>
          <dt>Диск</dt><dd>{snapshot.disk_path}</dd>
        </dl>
      </div>
    </>
  );
}
