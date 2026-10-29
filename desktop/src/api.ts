/** Единый клиент API: токен в localStorage, обработка 401, типы сущностей. */
export const TOKEN_KEY = "fedo_token";
export const THEME_KEY = "fedo_theme";
export const SCALE_KEY = "fedo_scale";

export type Task = {
  id: string;
  title: string;
  description: string;
  priority: "low" | "normal" | "high";
  status: "todo" | "in_progress" | "done" | "skipped";
  due_at: string | null;
  remind_at: string | null;
  planned_minutes: number;
  actual_minutes: number;
  category: string;
  started_at: string | null;
  completed_at: string | null;
  version: number;
  updated_at: string;
};

export type Lesson = {
  id: string;
  group_name: string;
  date: string;
  slot: number;
  start_time: string;
  end_time: string;
  subject: string;
  teacher: string;
  room: string;
  lesson_type: string;
};

export type Event = {
  id: string;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string | null;
  location: string;
  category: string;
  remind_at: string | null;
};

export type Device = {
  id: string;
  name: string;
  kind: string;
  platform: string;
  status: "online" | "offline" | "sleeping" | "revoked";
  ai_available: boolean;
  capabilities: string[];
  metrics: Record<string, unknown>;
  last_seen_at: string | null;
  notes: string;
  pending_commands: number;
};

export type CommandAction = {
  action: string;
  dangerous: boolean;
  description: string;
  params: string[];
};

export type DeviceCommand = {
  id: string;
  device_id: string;
  action: string;
  params: Record<string, unknown>;
  status: string;
  requires_confirmation: boolean;
  result: Record<string, unknown>;
  created_at: string;
  finished_at: string | null;
};

export type AiSettings = {
  mode: "local_only" | "hybrid" | "cloud_preferred" | "manual";
  modes: Record<string, string>;
  allow_cloud: boolean;
  allow_history_to_cloud: boolean;
  allow_remote_node: boolean;
  cloud_provider: string;
  manual_model: string;
  local_model: string;
  daily_request_limit: number;
  monthly_budget: number;
  temperature: number;
};

export type AiModels = {
  mode: string;
  allow_cloud: boolean;
  local: { available: boolean; models: string[]; selected: string };
  cloud: { provider: string; configured: boolean; models: string[]; allowed: boolean };
  remote_node: { available: boolean; models: string[] };
  privacy: string;
};

export type AiUsage = {
  today_requests: number;
  today_cloud_requests: number;
  month_requests: number;
  month_tokens: number;
  month_cost: number;
  daily_request_limit: number;
  monthly_budget: number;
  cloud_allowed_now: boolean;
  cloud_block_reason: string;
};

export type SyncStatus = {
  online: boolean;
  cursor: number;
  pending_operations: number;
  open_conflicts: number;
  last_push_at: string | null;
  last_pull_at: string | null;
  last_error: string;
  hub_url: string;
  sync_enabled: boolean;
  hub_configured: boolean;
  role: string;
};

export type Conflict = {
  id: string;
  entity: string;
  entity_id: string;
  base_version: number;
  server_version: number;
  incoming: Record<string, unknown>;
  server: Record<string, unknown>;
  status: string;
  created_at: string;
};

export type SystemSnapshot = {
  snapshot: Record<string, any>;
  summary: string;
  core: { available: boolean; version: string; build: string };
  role: string;
  collected_at: string;
};

export const isTauri = () =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    setToken("");
    window.dispatchEvent(new CustomEvent("fedo:unauthorized"));
    throw new ApiError("Требуется вход", 401);
  }
  if (!response.ok) {
    let detail = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });

export async function uploadSchedule(file: File, group: string, date: string): Promise<any> {
  const form = new FormData();
  form.append("file", file);
  form.append("group", group);
  form.append("date_override", date);
  form.append("replace_existing", "true");
  return api("/api/schedule/import", { method: "POST", body: form });
}

/** SSE-стрим ответа AI. Возвращает функцию отмены. */
export function streamChat(
  payload: { message: string; conversation_id?: string; mode?: string; model?: string; request_id: string },
  onEvent: (event: any) => void,
  onError: (error: string) => void,
): () => void {
  const controller = new AbortController();
  (async () => {
    try {
      const response = await fetch("/api/ai/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        onError(`Ошибка ${response.status}`);
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch {
            /* игнорируем битый чанк */
          }
        }
      }
    } catch (error) {
      if ((error as Error).name !== "AbortError") onError(String(error));
    }
  })();
  return () => {
    controller.abort();
    post(`/api/ai/cancel/${payload.request_id}`).catch(() => undefined);
  };
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "long" });
}

export function todayIso(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60000).toISOString().slice(0, 10);
}
