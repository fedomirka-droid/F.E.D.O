import { useCallback, useEffect, useState } from "react";
import {
  formatDateTime,
  get,
  post,
  type CommandAction,
  type Device,
  type DeviceCommand,
} from "../api";
import { Badge, Empty, Field, Modal, Spinner, statusTone, useAsyncAction, useToast } from "../ui";

export function Devices() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [actions, setActions] = useState<CommandAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [registering, setRegistering] = useState(false);
  const [credentials, setCredentials] = useState<{ device: Device; token: string; channel_secret: string } | null>(null);
  const [history, setHistory] = useState<{ device: Device; commands: DeviceCommand[] } | null>(null);
  const [form, setForm] = useState({ name: "", kind: "desktop", capabilities: "" });
  const [wolTarget, setWolTarget] = useState<Device | null>(null);
  const [wolMac, setWolMac] = useState("");
  const { busy, run } = useAsyncAction();
  const toast = useToast();

  const load = useCallback(async () => {
    const data = await get<{ devices: Device[]; actions: CommandAction[] }>("/api/devices");
    setDevices(data.devices);
    setActions(data.actions);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 20000);
    return () => window.clearInterval(timer);
  }, [load]);

  const register = () =>
    run(async () => {
      if (!form.name.trim()) throw new Error("Введите имя устройства");
      const result = await post<{ device: Device; token: string; channel_secret: string }>("/api/devices", {
        name: form.name.trim(),
        kind: form.kind,
        capabilities: form.capabilities.split(",").map((item) => item.trim()).filter(Boolean),
      });
      setCredentials({ device: result.device, token: result.token, channel_secret: result.channel_secret });
      setRegistering(false);
      setForm({ name: "", kind: "desktop", capabilities: "" });
      await load();
    }, "Не удалось зарегистрировать устройство");

  const send = (device: Device, action: string, params: Record<string, unknown> = {}) =>
    run(async () => {
      const command = await post<DeviceCommand>(`/api/devices/${device.id}/commands`, { action, params });
      if (command.requires_confirmation) {
        toast.notify(`${action}: требуется подтверждение`, "info");
        if (window.confirm(`Подтвердить опасное действие «${action}» на «${device.name}»?`)) {
          await post(`/api/devices/commands/${command.id}/confirm`);
          toast.success("Команда подтверждена и отправлена");
        } else {
          await post(`/api/devices/commands/${command.id}/reject`);
          toast.notify("Команда отклонена");
        }
      } else {
        toast.success(`Команда «${action}» отправлена`);
      }
      await load();
    }, "Не удалось отправить команду");

  const rotate = (device: Device) =>
    run(async () => {
      const result = await post<{ token: string; channel_secret: string }>(`/api/devices/${device.id}/rotate-token`);
      setCredentials({ device, token: result.token, channel_secret: result.channel_secret });
      toast.success("Токен обновлён, старый больше не действует");
    }, "Не удалось обновить токен");

  const revoke = (device: Device) =>
    run(async () => {
      if (!window.confirm(`Отозвать устройство «${device.name}»?`)) return;
      await post(`/api/devices/${device.id}/revoke`);
      await load();
    }, "Не удалось отозвать устройство");

  const openHistory = (device: Device) =>
    run(async () => {
      const data = await get<{ commands: DeviceCommand[] }>(`/api/devices/${device.id}/commands`);
      setHistory({ device, commands: data.commands });
    }, "Не удалось загрузить историю команд");

  return (
    <>
      <div className="row between">
        <p className="muted small">
          ThinkPad · домашний ПК с RTX 3080 · VPS (HUB) · контроллер Wake-on-LAN. Команды — только из белого списка.
        </p>
        <button className="btn primary" onClick={() => setRegistering(true)}>＋ Устройство</button>
      </div>

      {loading ? (
        <div className="row"><Spinner /> <span className="muted">Загрузка устройств…</span></div>
      ) : devices.length === 0 ? (
        <div className="card"><Empty text="Устройств нет. Добавь ThinkPad или домашний ПК." /></div>
      ) : (
        <div className="grid cols-2">
          {devices.map((device) => {
            const metrics = device.metrics as Record<string, any>;
            return (
              <div className="card" key={device.id}>
                <div className="card-title">
                  <div className="row">
                    <h3>{device.name}</h3>
                    <Badge tone={statusTone(device.status)}>{device.status}</Badge>
                    {device.ai_available ? <Badge tone="accent">AI</Badge> : null}
                  </div>
                  <button className="btn ghost small" onClick={() => openHistory(device)}>История</button>
                </div>
                <div className="stack small">
                  <div className="row between"><span className="muted">Тип</span><span>{device.kind}</span></div>
                  <div className="row between"><span className="muted">Платформа</span><span className="truncate">{device.platform || "—"}</span></div>
                  <div className="row between"><span className="muted">Активность</span><span>{formatDateTime(device.last_seen_at)}</span></div>
                  <div className="row between"><span className="muted">CPU / RAM</span>
                    <span>{metrics?.cpu_percent ?? "—"}% / {metrics?.ram_percent ?? "—"}%</span></div>
                  {metrics?.gpu?.available ? (
                    <div className="row between"><span className="muted">GPU</span>
                      <span className="truncate">{metrics.gpu.name}</span></div>
                  ) : null}
                  <div className="row between"><span className="muted">Команд в очереди</span><span>{device.pending_commands}</span></div>
                  {device.capabilities.length ? (
                    <div className="row" style={{ gap: 6 }}>
                      {device.capabilities.map((cap) => <Badge key={cap}>{cap}</Badge>)}
                    </div>
                  ) : null}
                </div>
                <div className="divider" style={{ margin: "12px 0" }} />
                <div className="row" style={{ gap: 6 }}>
                  {actions.filter((action) => !["wol"].includes(action.action)).map((action) => (
                    <button key={action.action}
                            className={`btn small ${action.dangerous ? "danger" : ""}`}
                            title={action.description}
                            disabled={busy || device.status === "revoked"}
                            onClick={() => send(device, action.action)}>
                      {action.action}
                    </button>
                  ))}
                  <button className="btn small" disabled={busy} onClick={() => setWolTarget(device)}>wol</button>
                  <span className="spacer" />
                  <button className="btn small ghost" onClick={() => rotate(device)}>↻ токен</button>
                  <button className="btn small danger" onClick={() => revoke(device)}>отозвать</button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {registering ? (
        <Modal title="Новое устройство" onClose={() => setRegistering(false)}
               footer={<>
                 <button className="btn ghost" onClick={() => setRegistering(false)}>Отмена</button>
                 <button className="btn primary" onClick={register} disabled={busy}>Создать</button>
               </>}>
          <Field label="Имя устройства">
            <input className="input" placeholder="ThinkPad / HomePC / VPS" value={form.name}
                   onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </Field>
          <Field label="Тип">
            <select className="select" value={form.kind}
                    onChange={(event) => setForm({ ...form, kind: event.target.value })}>
              <option value="desktop">Desktop</option>
              <option value="gpu">GPU-узел</option>
              <option value="controller">Контроллер WoL</option>
              <option value="hub">HUB</option>
            </select>
          </Field>
          <Field label="Возможности (через запятую)" hint="Например: ai, monitor, wol">
            <input className="input" value={form.capabilities}
                   onChange={(event) => setForm({ ...form, capabilities: event.target.value })} />
          </Field>
          <p className="hint">Токен и секрет канала показываются один раз — их вводят в F.E.D.O. Agent.</p>
        </Modal>
      ) : null}

      {credentials ? (
        <Modal title="Данные устройства (показываются один раз)" onClose={() => setCredentials(null)}
               footer={<button className="btn primary" onClick={() => setCredentials(null)}>Сохранил</button>}>
          <p className="muted small">
            Скопируй в защищённое место и передай агенту устройства. В Git и логи эти значения не попадают.
          </p>
          <Field label="Device ID">
            <input className="input mono" readOnly value={credentials.device.id} onFocus={(event) => event.target.select()} />
          </Field>
          <Field label="Токен">
            <input className="input mono" readOnly value={credentials.token} onFocus={(event) => event.target.select()} />
          </Field>
          <Field label="Секрет канала (HMAC)">
            <input className="input mono" readOnly value={credentials.channel_secret} onFocus={(event) => event.target.select()} />
          </Field>
          <pre className="mono small" style={{ whiteSpace: "pre-wrap", background: "var(--surface-2)", padding: 10, borderRadius: 8 }}>
{`python -m ecosystem.agent --hub <HUB_URL> \\
  --device-id ${credentials.device.id} \\
  --token ${credentials.token.slice(0, 12)}… \\
  --secret <секрет> \\
  --name "${credentials.device.name}" --kind ${credentials.device.kind}`}
          </pre>
        </Modal>
      ) : null}

      {history ? (
        <Modal title={`Команды: ${history.device.name}`} onClose={() => setHistory(null)}>
          {history.commands.length === 0 ? <Empty text="Команд ещё не было" /> : (
            <div className="list">
              {history.commands.map((command) => (
                <div className="list-item" key={command.id}>
                  <div className="grow">
                    <div>{command.action} <span className="faint small">{command.status}</span></div>
                    <div className="small faint">{formatDateTime(command.created_at)}
                      {command.requires_confirmation ? " · требовала подтверждения" : ""}</div>
                  </div>
                  {command.requires_confirmation && command.status === "awaiting_confirmation" ? (
                    <button className="btn small primary" onClick={() =>
                      run(async () => {
                        await post(`/api/devices/commands/${command.id}/confirm`);
                        toast.success("Подтверждено");
                        setHistory(null);
                      }, "Не удалось подтвердить")}>Подтвердить</button>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </Modal>
      ) : null}

      {wolTarget ? (
        <Modal title={`Wake-on-LAN: ${wolTarget.name}`} onClose={() => setWolTarget(null)}
               footer={<>
                 <button className="btn ghost" onClick={() => setWolTarget(null)}>Отмена</button>
                 <button className="btn primary" disabled={busy}
                         onClick={() => {
                           send(wolTarget, "wol", { mac: wolMac });
                           setWolTarget(null);
                         }}>Разбудить</button>
               </>}>
          <Field label="MAC-адрес" hint="Отправляется через устройство-контроллер (например, старый ноутбук)">
            <input className="input mono" placeholder="AA:BB:CC:DD:EE:FF" value={wolMac}
                   onChange={(event) => setWolMac(event.target.value)} />
          </Field>
        </Modal>
      ) : null}
    </>
  );
}
