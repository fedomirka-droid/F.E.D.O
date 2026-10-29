import { useCallback, useEffect, useState } from "react";
import {
  SCALE_KEY,
  THEME_KEY,
  del,
  formatDateTime,
  get,
  post,
  put,
  type AiModels,
  type AiSettings,
  type AiUsage,
  type Conflict,
  type SyncStatus,
} from "../api";
import { Badge, Empty, Field, Spinner, useAsyncAction, useToast } from "../ui";

type Session = { id: string; user_agent: string; created_at: string; last_seen_at: string; revoked: boolean; current: boolean };
type TelegramAccount = { id: number; telegram_id: number; username: string; linked_at: string; revoked: boolean };
type AuditEntry = { id: number; actor: string; action: string; target: string; created_at: string };

export function Settings({
  theme,
  onThemeChange,
  scale,
  onScaleChange,
}: {
  theme: string;
  onThemeChange: (theme: string) => void;
  scale: number;
  onScaleChange: (scale: number) => void;
}) {
  const [ai, setAi] = useState<AiSettings | null>(null);
  const [models, setModels] = useState<AiModels | null>(null);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [accounts, setAccounts] = useState<TelegramAccount[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [keys, setKeys] = useState<string[]>([]);
  const [linkCode, setLinkCode] = useState<{ code: string; expires_at: string } | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [hubUrl, setHubUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const { busy, run } = useAsyncAction();
  const toast = useToast();

  const load = useCallback(async () => {
    const results = await Promise.allSettled([
      get<AiSettings>("/api/ai/settings"),
      get<AiModels>("/api/ai/models"),
      get<AiUsage>("/api/ai/usage"),
      get<SyncStatus>("/api/sync/status"),
      get<{ conflicts: Conflict[] }>("/api/sync/conflicts"),
      get<{ sessions: Session[] }>("/api/auth/sessions"),
      get<{ accounts: TelegramAccount[] }>("/api/telegram/accounts"),
      get<{ entries: AuditEntry[] }>("/api/audit?limit=20"),
      get<{ configured: string[] }>("/api/ai/keys"),
    ]);
    if (results[0].status === "fulfilled") setAi(results[0].value);
    if (results[1].status === "fulfilled") setModels(results[1].value);
    if (results[2].status === "fulfilled") setUsage(results[2].value);
    if (results[3].status === "fulfilled") {
      setSync(results[3].value);
      setHubUrl(results[3].value.hub_url || "");
    }
    if (results[4].status === "fulfilled") setConflicts(results[4].value.conflicts);
    if (results[5].status === "fulfilled") setSessions(results[5].value.sessions);
    if (results[6].status === "fulfilled") setAccounts(results[6].value.accounts);
    if (results[7].status === "fulfilled") setAudit(results[7].value.entries);
    if (results[8].status === "fulfilled") setKeys(results[8].value.configured);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const saveAi = (patchBody: Partial<AiSettings>) =>
    run(async () => {
      const updated = await put<AiSettings>("/api/ai/settings", patchBody);
      setAi(updated);
      await load();
      toast.success("Настройки AI сохранены");
    }, "Не удалось сохранить настройки AI");

  const saveKey = () =>
    run(async () => {
      if (ai?.cloud_provider === "gemini") {
        await post("/api/ai/keys/gemini", { api_key: apiKey });
      } else if (baseUrl) {
        await post("/api/ai/keys/openai_base_url", { api_key: "base-url", base_url: baseUrl });
        await post("/api/ai/keys/openai", { api_key: apiKey || "not-set" });
      } else {
        await post("/api/ai/keys/openai", { api_key: apiKey });
      }
      setApiKey("");
      await load();
      toast.success("Ключ сохранён в зашифрованном виде");
    }, "Не удалось сохранить ключ");

  const runSync = () =>
    run(async () => {
      const result = await post<{ ok: boolean; reason?: string; pushed: number; pulled: number; conflicts: number }>("/api/sync/run");
      if (result.ok) toast.success(`Синхронизация: отправлено ${result.pushed}, получено ${result.pulled}`);
      else toast.error(`Синхронизация не выполнена: ${result.reason}`);
      await load();
    }, "Ошибка синхронизации");

  const resolve = (conflict: Conflict, resolution: "local" | "server") =>
    run(async () => {
      await post(`/api/sync/conflicts/${conflict.id}/resolve`, { resolution });
      await load();
      toast.success("Конфликт разрешён");
    }, "Не удалось разрешить конфликт");

  const revokeSession = (session: Session) =>
    run(async () => {
      await del(`/api/auth/sessions/${session.id}`);
      await load();
    }, "Не удалось отозвать сессию");

  const createLink = () =>
    run(async () => {
      const result = await post<{ code: string; expires_at: string }>("/api/telegram/link");
      setLinkCode(result);
    }, "Не удалось создать код");

  const unlink = (account: TelegramAccount) =>
    run(async () => {
      await del(`/api/telegram/accounts/${account.id}`);
      await load();
    }, "Не удалось отвязать аккаунт");

  if (loading) return <div className="row"><Spinner /> <span className="muted">Загрузка настроек…</span></div>;

  return (
    <>
      <div className="grid cols-2">
        <div className="card">
          <div className="card-title"><h3>Внешний вид</h3></div>
          <div className="stack">
            <div className="row between">
              <span className="muted">Тема</span>
              <div className="row" style={{ gap: 6 }}>
                <button className={`chip ${theme === "dark" ? "active" : ""}`}
                        onClick={() => { localStorage.setItem(THEME_KEY, "dark"); onThemeChange("dark"); }}>Тёмная</button>
                <button className={`chip ${theme === "light" ? "active" : ""}`}
                        onClick={() => { localStorage.setItem(THEME_KEY, "light"); onThemeChange("light"); }}>Светлая</button>
              </div>
            </div>
            <div className="row between">
              <span className="muted">Масштаб интерфейса</span>
              <div className="row" style={{ gap: 6 }}>
                {[0.9, 1, 1.1, 1.25].map((value) => (
                  <button key={value} className={`chip ${scale === value ? "active" : ""}`}
                          onClick={() => { localStorage.setItem(SCALE_KEY, String(value)); onScaleChange(value); }}>
                    {Math.round(value * 100)}%
                  </button>
                ))}
              </div>
            </div>
            <p className="hint">Настройки темы и масштаба хранятся локально и синхронизируются как предпочтения.</p>
          </div>
        </div>

        <div className="card">
          <div className="card-title"><h3>Сессии и доступ</h3><Badge>{sessions.filter((s) => !s.revoked).length}</Badge></div>
          <div className="list scroll-y">
            {sessions.map((session) => (
              <div className="list-item" key={session.id}>
                <div className="grow">
                  <div className="truncate small">{session.user_agent || "устройство"}</div>
                  <div className="faint small">вход {formatDateTime(session.created_at)}</div>
                </div>
                {session.current ? <Badge tone="accent">текущая</Badge> : (
                  session.revoked ? <Badge>отозвана</Badge> :
                    <button className="btn small danger" onClick={() => revokeSession(session)}>отозвать</button>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h3>AI Router 2.0</h3>
          <div className="row">
            <Badge tone={ai?.allow_cloud ? "warning" : "success"}>
              {ai?.allow_cloud ? "облако разрешено" : "облако запрещено"}
            </Badge>
            {models?.local.available ? <Badge tone="success">локальная модель онлайн</Badge> : <Badge tone="warning">локальная модель недоступна</Badge>}
          </div>
        </div>
        {!ai ? <Empty text="Настройки AI недоступны" /> : (
          <div className="stack">
            <div className="grid cols-2">
              <Field label="Режим маршрутизации">
                <select className="select" value={ai.mode}
                        onChange={(event) => saveAi({ mode: event.target.value as AiSettings["mode"] })}>
                  <option value="local_only">Local Only — только своё железо</option>
                  <option value="hybrid">Hybrid — локально, облако как резерв</option>
                  <option value="cloud_preferred">Cloud Preferred</option>
                  <option value="manual">Manual — выбранная модель</option>
                </select>
              </Field>
              <Field label="Облачный провайдер">
                <select className="select" value={ai.cloud_provider}
                        onChange={(event) => saveAi({ cloud_provider: event.target.value })}>
                  <option value="gemini">Gemini</option>
                  <option value="openai">OpenAI-compatible</option>
                </select>
              </Field>
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={ai.allow_cloud}
                     onChange={(event) => saveAi({ allow_cloud: event.target.checked })} />
              Разрешить облачные запросы (иначе облако запрещено полностью)
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={ai.allow_history_to_cloud}
                     onChange={(event) => saveAi({ allow_history_to_cloud: event.target.checked })} />
              Отправлять историю диалога в облако (по умолчанию только текущий запрос)
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={ai.allow_remote_node}
                     onChange={(event) => saveAi({ allow_remote_node: event.target.checked })} />
              Разрешить домашний AI-узел (RTX 3080)
            </label>
            <div className="grid cols-3">
              <Field label="Лимит облачных запросов в день">
                <input className="input" type="number" min={0} defaultValue={ai.daily_request_limit}
                       onBlur={(event) => saveAi({ daily_request_limit: Number(event.target.value) })} />
              </Field>
              <Field label="Бюджет в месяц (0 — без лимита)">
                <input className="input" type="number" min={0} step="0.01" defaultValue={ai.monthly_budget}
                       onBlur={(event) => saveAi({ monthly_budget: Number(event.target.value) })} />
              </Field>
              <Field label="Температура">
                <input className="input" type="number" min={0} max={2} step="0.1" defaultValue={ai.temperature}
                       onBlur={(event) => saveAi({ temperature: Number(event.target.value) })} />
              </Field>
            </div>
            <div className="grid cols-2">
              <Field label="Локальная модель (пусто — авто)">
                <input className="input" defaultValue={ai.local_model}
                       placeholder={models?.local.models[0] || "determined by LM Studio"}
                       onBlur={(event) => saveAi({ local_model: event.target.value })} />
              </Field>
              <Field label={`API-ключ ${ai.cloud_provider} (шифруется)`}>
                <div className="row">
                  <input className="input" type="password" value={apiKey} placeholder="не хранится в открытом виде"
                         onChange={(event) => setApiKey(event.target.value)} />
                  <button className="btn small primary" onClick={saveKey} disabled={busy || !apiKey}>Сохранить</button>
                </div>
              </Field>
            </div>
            {ai.cloud_provider === "openai" ? (
              <Field label="Base URL OpenAI-compatible API">
                <input className="input" value={baseUrl} placeholder="https://api.openai.com/v1"
                       onChange={(event) => setBaseUrl(event.target.value)} />
              </Field>
            ) : null}
            <div className="row between small">
              <span className="muted">Ключи настроены: {keys.length ? keys.join(", ") : "нет"}</span>
              <span className="muted">
                Запросов сегодня: {usage?.today_requests ?? 0} · облако: {usage?.today_cloud_requests ?? 0}
                {" · "}расход: {usage?.month_cost ?? 0}
              </span>
            </div>
            {usage && !usage.cloud_allowed_now ? (
              <div className="badge warning">Облако сейчас блокируется: {usage.cloud_block_reason}</div>
            ) : null}
          </div>
        )}
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-title"><h3>Синхронизация с HUB</h3>
            <Badge tone={sync?.online ? "success" : sync?.hub_configured ? "warning" : ""}>
              {sync?.hub_configured ? (sync?.online ? "онлайн" : "ожидание") : "не настроено"}
            </Badge>
          </div>
          <div className="stack">
            <Field label="Адрес HUB" hint="Задаётся на сервере/в .env; здесь только для справки">
              <input className="input" value={hubUrl} readOnly />
            </Field>
            <div className="row between small">
              <span className="muted">В очереди: {sync?.pending_operations ?? 0}</span>
              <span className="muted">Курсор: {sync?.cursor ?? 0}</span>
              <button className="btn small" onClick={runSync} disabled={busy}>Синхронизировать</button>
            </div>
            {sync?.last_error ? <div className="badge danger">{sync.last_error}</div> : null}
            <p className="hint">
              В Personal Edition Desktop работает локально и без HUB. Синхронизация — опция.
              Токен устройства для HUB задаётся переменной FEDO_SYNC_DEVICE_TOKEN.
            </p>
          </div>
        </div>

        <div className="card">
          <div className="card-title"><h3>Конфликты изменений</h3><Badge tone={conflicts.length ? "danger" : "success"}>{conflicts.length}</Badge></div>
          {conflicts.length === 0 ? <Empty text="Конфликтов нет" /> : (
            <div className="list scroll-y">
              {conflicts.map((conflict) => (
                <div key={conflict.id} className="stack" style={{ gap: 6 }}>
                  <div className="small">
                    {conflict.entity} · версия сервера {conflict.server_version} / локальная {conflict.base_version}
                  </div>
                  <div className="row" style={{ gap: 8 }}>
                    <button className="btn small" onClick={() => resolve(conflict, "local")}>Принять мою</button>
                    <button className="btn small" onClick={() => resolve(conflict, "server")}>Оставить серверную</button>
                  </div>
                  <div className="divider" />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-title"><h3>Telegram (F.E.D.O. Mini)</h3></div>
          <div className="stack">
            {accounts.filter((account) => !account.revoked).length === 0 ? (
              <p className="muted small">Аккаунт не привязан. Создай код и отправь боту: /link КОД</p>
            ) : accounts.map((account) => (
              <div className="list-item" key={account.id}>
                <div className="grow small">
                  @{account.username || "telegram"} · id {account.telegram_id}
                  <div className="faint">привязан {formatDateTime(account.linked_at)}</div>
                </div>
                <button className="btn small danger" onClick={() => unlink(account)}>отвязать</button>
              </div>
            ))}
            <div className="row">
              <button className="btn primary small" onClick={createLink} disabled={busy}>Создать код</button>
              {linkCode ? (
                <span className="mono" style={{ fontSize: 20, letterSpacing: 3 }}>{linkCode.code}</span>
              ) : null}
            </div>
            {linkCode ? <span className="hint">Код действует до {formatDateTime(linkCode.expires_at)} и одноразовый.</span> : null}
          </div>
        </div>

        <div className="card">
          <div className="card-title"><h3>Журнал операций</h3></div>
          <div className="list scroll-y" style={{ maxHeight: 260 }}>
            {audit.length === 0 ? <Empty text="Пока пусто" /> : audit.map((entry) => (
              <div className="list-item" key={entry.id}>
                <div className="grow">
                  <div className="small">{entry.action}</div>
                  <div className="faint small">{entry.actor} · {formatDateTime(entry.created_at)}</div>
                </div>
                <span className="small faint truncate" style={{ maxWidth: 140 }}>{entry.target}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
