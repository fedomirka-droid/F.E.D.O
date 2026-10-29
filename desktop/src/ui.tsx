import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/* ------------------------------------------------------------------ Тосты */
type ToastKind = "info" | "success" | "error";
type Toast = { id: number; kind: ToastKind; text: string };

type ToastApi = {
  notify: (text: string, kind?: ToastKind) => void;
  error: (text: string) => void;
  success: (text: string) => void;
};

const ToastContext = createContext<ToastApi>({
  notify: () => undefined,
  error: () => undefined,
  success: () => undefined,
});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const notify = useCallback((text: string, kind: ToastKind = "info") => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, kind, text }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((item) => item.id !== id));
    }, 4200);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      notify,
      error: (text: string) => notify(text, "error"),
      success: (text: string) => notify(text, "success"),
    }),
    [notify],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-stack">
        {items.map((item) => (
          <div key={item.id} className={`toast ${item.kind}`}>
            {item.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

/* ------------------------------------------------------------------ Модалка */
export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="row between" style={{ marginBottom: 14 }}>
          <h2>{title}</h2>
          <button className="btn ghost icon" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="stack">{children}</div>
        {footer ? <div className="row end" style={{ marginTop: 18 }}>{footer}</div> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Поля */
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ Прочее */
export function Empty({ text }: { text: string }) {
  return <div className="empty">{text}</div>;
}

export function Spinner() {
  return <span className="spinner" aria-label="Загрузка" />;
}

export function Bar({ value, tone }: { value: number; tone?: "success" | "warning" | "danger" }) {
  const percent = Math.max(0, Math.min(100, value));
  return (
    <div className={`bar ${tone || ""}`}>
      <span style={{ width: `${percent}%` }} />
    </div>
  );
}

export function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: "" | "accent" | "success" | "warning" | "danger" | "info";
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function statusTone(status: string): "success" | "warning" | "danger" | "" {
  if (status === "online" || status === "done") return "success";
  if (status === "sleeping" || status === "in_progress") return "warning";
  if (status === "revoked" || status === "failed") return "danger";
  return "";
}

export function useAsyncAction() {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const run = useCallback(
    async (action: () => Promise<void>, errorText = "Не удалось выполнить действие") => {
      setBusy(true);
      try {
        await action();
      } catch (error) {
        toast.error(error instanceof Error ? `${errorText}: ${error.message}` : errorText);
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );
  return { busy, run };
}
