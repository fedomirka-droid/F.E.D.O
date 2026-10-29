import { useCallback, useEffect, useRef, useState } from "react";
import {
  del,
  get,
  put,
  streamChat,
  type AiHealth,
  type AiModels,
  type AiSettings,
  type AiUsage,
} from "../api";
import { Badge, Empty, useToast } from "../ui";

type Conversation = { id: string; title: string; updated_at: string };
type Message = { id?: number; role: "user" | "assistant"; content: string; provider?: string; model?: string };
type TraceStep = { provider: string; model: string; outcome: string; reason: string; cloud: boolean };

const MODE_LABELS: Record<string, string> = {
  local_only: "Local Only",
  hybrid: "Hybrid",
  cloud_preferred: "Cloud Preferred",
  manual: "Manual",
};

export function Assistant() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [models, setModels] = useState<AiModels | null>(null);
  const [settings, setSettings] = useState<AiSettings | null>(null);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [mode, setMode] = useState("hybrid");
  const [model, setModel] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const [lastRoute, setLastRoute] = useState<{ provider: string; cloud: boolean } | null>(null);
  const [health, setHealth] = useState<AiHealth | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const toast = useToast();

  const loadMeta = useCallback(async () => {
    const [conversationList, modelList, settingsData, usageData, healthData] =
      await Promise.allSettled([
        get<{ conversations: Conversation[] }>("/api/ai/conversations"),
        get<AiModels>("/api/ai/models"),
        get<AiSettings>("/api/ai/settings"),
        get<AiUsage>("/api/ai/usage"),
        get<AiHealth>("/api/ai/health"),
      ]);
    if (conversationList.status === "fulfilled") setConversations(conversationList.value.conversations);
    if (modelList.status === "fulfilled") setModels(modelList.value);
    if (settingsData.status === "fulfilled") {
      setSettings(settingsData.value);
      setMode(settingsData.value.mode);
    }
    if (usageData.status === "fulfilled") setUsage(usageData.value);
    if (healthData.status === "fulfilled") setHealth(healthData.value);
  }, []);

  useEffect(() => {
    loadMeta().catch(() => undefined);
  }, [loadMeta]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const openConversation = async (id: string) => {
    setActiveId(id);
    setTrace([]);
    const data = await get<{ messages: Message[] }>(`/api/ai/conversations/${id}/messages`);
    setMessages(data.messages);
  };

  const newConversation = () => {
    setActiveId("");
    setMessages([]);
    setTrace([]);
    setLastRoute(null);
  };

  const removeConversation = async (id: string) => {
    await del(`/api/ai/conversations/${id}`);
    setConversations((prev) => prev.filter((item) => item.id !== id));
    if (activeId === id) newConversation();
  };

  const changeMode = async (nextMode: string) => {
    setMode(nextMode);
    try {
      const updated = await put<AiSettings>("/api/ai/settings", { mode: nextMode });
      setSettings(updated);
      await loadMeta();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось изменить режим");
    }
  };

  const updateConsent = async (patch: Partial<AiSettings>) => {
    try {
      const updated = await put<AiSettings>("/api/ai/settings", patch);
      setSettings(updated);
      await loadMeta();
      toast.success("Настройки приватности сохранены");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось сохранить");
    }
  };

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    setStreaming(true);
    setTrace([]);
    const requestId = crypto.randomUUID();

    const stop = streamChat(
      {
        message: text,
        conversation_id: activeId || undefined,
        mode,
        model: model || undefined,
        request_id: requestId,
      },
      (event) => {
        if (event.type === "meta" && event.conversation_id) {
          setActiveId((prev) => prev || event.conversation_id);
        }
        if (event.type === "route") {
          setLastRoute({ provider: event.provider, cloud: Boolean(event.cloud) });
        }
        if (event.type === "chunk") {
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            copy[copy.length - 1] = { ...last, content: last.content + event.text };
            return copy;
          });
        }
        if (event.type === "done") {
          setStreaming(false);
          setTrace(event.trace || []);
          setMessages((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = {
              ...copy[copy.length - 1],
              content: event.text || copy[copy.length - 1].content,
              provider: event.provider,
              model: event.model,
            };
            return copy;
          });
          setLastRoute({ provider: event.provider, cloud: Boolean(event.cloud) });
        }
        if (event.type === "cancelled" || event.type === "error") {
          setStreaming(false);
          setTrace(event.trace || []);
          if (event.type === "error") {
            setMessages((prev) => {
              const copy = [...prev];
              copy[copy.length - 1] = { ...copy[copy.length - 1], content: event.message || "AI недоступен" };
              return copy;
            });
          }
        }
      },
      (error) => toast.error(error),
    );
    cancelRef.current = stop;
    window.setTimeout(() => {
      cancelRef.current = null;
      loadMeta().catch(() => undefined);
      get<{ conversations: Conversation[] }>("/api/ai/conversations")
        .then((list) => setConversations(list.conversations))
        .catch(() => undefined);
    }, 800);
  };

  const cancel = () => {
    cancelRef.current?.();
    cancelRef.current = null;
    setStreaming(false);
  };

  return (
    <div className="chat-layout">
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10, overflow: "hidden" }}>
        <button className="btn primary small" onClick={newConversation}>＋ Новый диалог</button>
        <div className="list scroll-y" style={{ flex: 1 }}>
          {conversations.length === 0 ? <Empty text="Диалогов нет" /> : conversations.map((conversation) => (
            <div className={`list-item ${activeId === conversation.id ? "hoverable" : ""}`} key={conversation.id}
                 style={activeId === conversation.id ? { borderColor: "var(--accent-border)" } : undefined}>
              <button className="grow truncate"
                      style={{ background: "none", border: "none", textAlign: "left", cursor: "pointer", color: "inherit" }}
                      onClick={() => openConversation(conversation.id)}>
                {conversation.title}
              </button>
              <button className="btn small ghost" onClick={() => removeConversation(conversation.id)}>✕</button>
            </div>
          ))}
        </div>
        <div className="divider" />
        <div className="stack small">
          <div className="row between"><span className="muted">Приватность</span>
            <Badge tone={models?.allow_cloud ? "warning" : "success"}>
              {models?.allow_cloud ? "облако разрешено" : "только локально"}
            </Badge>
          </div>
          <div className="row between"><span className="muted">Запросов сегодня</span>
            <span>{usage?.today_requests ?? 0}</span></div>
          <div className="row between"><span className="muted">Расход месяца</span>
            <span>{usage?.month_cost ?? 0}</span></div>
          {usage && !usage.cloud_allowed_now ? (
            <span className="hint">{usage.cloud_block_reason}</span>
          ) : null}
        </div>
        <div className="divider" />
        <div className="stack small">
          <div className="label">Согласие на облако</div>
          <label className="row small" style={{ gap: 8 }}>
            <input type="checkbox" checked={Boolean(settings?.allow_cloud)}
                   onChange={(event) => updateConsent({ allow_cloud: event.target.checked })} />
            <span>Разрешить отправку запросов</span>
          </label>
          <label className="row small" style={{ gap: 8 }}>
            <input type="checkbox" checked={Boolean(settings?.allow_history_to_cloud)}
                   disabled={!settings?.allow_cloud}
                   onChange={(event) => updateConsent({ allow_history_to_cloud: event.target.checked })} />
            <span>Разрешить передачу истории диалога</span>
          </label>
          <span className="hint">
            Без первого согласия Router работает только с локальной моделью —
            режим Local Only принудительно отключает облако.
          </span>
        </div>
        {health ? (
          <>
            <div className="divider" />
            <div className="stack small">
              <div className="label">Провайдеры</div>
              <div className="row between">
                <span className="muted">LM Studio</span>
                <Badge tone={health.local.available ? "success" : "warning"}>
                  {health.local.available ? `${health.local.models.length} модел.` : "недоступен"}
                </Badge>
              </div>
              <div className="row between">
                <span className="muted">Домашний узел</span>
                <Badge tone={health.remote_node.available ? "success" : "danger"}>
                  {health.remote_node.configured
                    ? health.remote_node.available ? "онлайн" : "офлайн"
                    : "не настроен"}
                </Badge>
              </div>
              <div className="row between">
                <span className="muted">Облако ({health.cloud.provider})</span>
                <Badge tone={health.cloud.usable ? "warning" : "danger"}>
                  {health.cloud.usable ? "готово" : health.cloud.reason || "запрещено"}
                </Badge>
              </div>
              {health.fallback_plan.length > 0 ? (
                <span className="hint">
                  Маршрут: {health.fallback_plan.map((step) => step.label).join(" → ")}
                </span>
              ) : (
                <span className="hint">Нет доступных провайдеров — проверь Настройки AI.</span>
              )}
            </div>
          </>
        ) : null}
      </div>

      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
        <div className="row" style={{ gap: 8 }}>
          <select className="select" style={{ width: "auto" }} value={mode}
                  onChange={(event) => changeMode(event.target.value)}>
            {Object.entries(MODE_LABELS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
          <select className="select" style={{ width: "auto" }} value={model}
                  onChange={(event) => setModel(event.target.value)}>
            <option value="">Авто (локальная)</option>
            {models?.local.models.map((name) => <option key={name} value={name}>{name}</option>)}
            {models?.cloud.models.map((name) => <option key={name} value={name}>{name} (облако)</option>)}
            {models?.remote_node.available ? <option value="home-node">home-node (RTX 3080)</option> : null}
          </select>
          <span className="spacer" />
          <Badge tone={models?.local.available ? "success" : "warning"}>
            локально: {models?.local.available ? "онлайн" : "нет"}
          </Badge>
          {lastRoute ? (
            <Badge tone={lastRoute.cloud ? "warning" : "success"}>
              {lastRoute.provider}{lastRoute.cloud ? " · облако" : " · локально"}
            </Badge>
          ) : null}
        </div>

        <div className="chat-messages" style={{ flex: 1 }}>
          {messages.length === 0 ? (
            <Empty text="Спроси что угодно. В режиме Local Only данные не уходят в облако." />
          ) : messages.map((message, index) => (
            <div className={`bubble ${message.role}`} key={index}>
              {message.content || (streaming && index === messages.length - 1 ? "…" : "")}
              {message.role === "assistant" && message.provider ? (
                <div className="meta">{message.provider}{message.model ? ` · ${message.model}` : ""}</div>
              ) : null}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {trace.length > 0 ? (
          <details className="small">
            <summary className="muted">Маршрут запроса ({trace.length} шагов)</summary>
            <div className="stack" style={{ marginTop: 6 }}>
              {trace.map((step, index) => (
                <div className="row between small" key={index}>
                  <span>{step.provider}{step.model ? ` · ${step.model}` : ""}</span>
                  <Badge tone={step.outcome === "ok" ? "success" : step.outcome === "blocked" ? "warning" : "danger"}>
                    {step.outcome}{step.reason ? `: ${step.reason}` : ""}
                  </Badge>
                </div>
              ))}
            </div>
          </details>
        ) : null}

        <div className="row" style={{ alignItems: "flex-end" }}>
          <textarea className="textarea" style={{ minHeight: 52, maxHeight: 160 }} value={input}
                    placeholder="Сообщение F.E.D.O. (Enter — отправить, Shift+Enter — новая строка)"
                    onChange={(event) => setInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        send();
                      }
                    }} />
          {streaming ? (
            <button className="btn danger" onClick={cancel}>Стоп</button>
          ) : (
            <button className="btn primary" onClick={send} disabled={!input.trim()}>Отправить</button>
          )}
        </div>
        {settings && settings.mode !== mode ? (
          <span className="hint">Режим изменён только для этого запроса</span>
        ) : null}
      </div>
    </div>
  );
}
