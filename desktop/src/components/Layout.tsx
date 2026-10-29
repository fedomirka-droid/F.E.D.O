import { useState, type ReactNode } from "react";

export type PageKey =
  | "dashboard"
  | "assistant"
  | "tasks"
  | "calendar"
  | "schedule"
  | "devices"
  | "monitor"
  | "settings";

export const PAGE_TITLES: Record<PageKey, string> = {
  dashboard: "Dashboard",
  assistant: "AI Assistant",
  tasks: "Задачи",
  calendar: "Календарь",
  schedule: "Расписание",
  devices: "Устройства",
  monitor: "System Monitor",
  settings: "Настройки",
};

const NAV: { key: PageKey; label: string; icon: string }[] = [
  { key: "dashboard", label: "Dashboard", icon: "◈" },
  { key: "assistant", label: "AI Assistant", icon: "✦" },
  { key: "tasks", label: "Задачи", icon: "☑" },
  { key: "calendar", label: "Календарь", icon: "▤" },
  { key: "schedule", label: "Расписание", icon: "⌚" },
  { key: "devices", label: "Устройства", icon: "⌘" },
  { key: "monitor", label: "System Monitor", icon: "▥" },
  { key: "settings", label: "Настройки", icon: "⚙" },
];

export type ConnectionState = {
  backend: boolean;
  syncOnline: boolean;
  aiMode: string;
  pendingOps: number;
};

export function Layout({
  page,
  onNavigate,
  children,
  connection,
  onLogout,
  theme,
  onToggleTheme,
}: {
  page: PageKey;
  onNavigate: (page: PageKey) => void;
  children: ReactNode;
  connection: ConnectionState;
  onLogout: () => void;
  theme: string;
  onToggleTheme: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="app-shell">
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">FE</div>
          <div className="brand-text">
            <strong>F.E.D.O.</strong>
            <span>Personal Edition</span>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.key}
              className={`nav-item ${page === item.key ? "active" : ""}`}
              onClick={() => {
                onNavigate(item.key);
                setOpen(false);
              }}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="divider" />
          <div className="small faint" style={{ padding: "0 8px" }}>
            {connection.backend ? "Backend: подключён" : "Backend: нет связи"}
            <br />
            AI: {connection.aiMode}
          </div>
          <button className="btn ghost small" onClick={onToggleTheme}>
            {theme === "dark" ? "☀ Светлая тема" : "🌙 Тёмная тема"}
          </button>
          <button className="btn ghost small" onClick={onLogout}>
            Выйти
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            <button className="btn ghost icon menu-toggle" onClick={() => setOpen((v) => !v)} aria-label="Меню">
              ☰
            </button>
            <h2>{PAGE_TITLES[page]}</h2>
          </div>
          <div className="status-dots">
            <span>
              <i className={`dot ${connection.backend ? "online" : "danger"}`} />
              Desktop
            </span>
            <span>
              <i className={`dot ${connection.syncOnline ? "online" : connection.pendingOps ? "warn" : "offline"}`} />
              Sync{connection.pendingOps ? ` · ${connection.pendingOps}` : ""}
            </span>
          </div>
        </header>
        <main className="content">
          <div className="content-inner">{children}</div>
        </main>
      </div>
    </div>
  );
}
