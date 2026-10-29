import { useCallback, useEffect, useState } from "react";
import { get, getToken, SCALE_KEY, setToken, THEME_KEY, type SyncStatus } from "./api";
import { Layout, type ConnectionState, type PageKey } from "./components/Layout";
import { Assistant } from "./pages/Assistant";
import { Calendar } from "./pages/Calendar";
import { Dashboard } from "./pages/Dashboard";
import { Devices } from "./pages/Devices";
import { Login } from "./pages/Login";
import { Monitor } from "./pages/Monitor";
import { Schedule } from "./pages/Schedule";
import { Settings } from "./pages/Settings";
import { Tasks } from "./pages/Tasks";
import { useToast } from "./ui";

type Health = { status: string; role: string; version: string; core: string };

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()));
  const [page, setPage] = useState<PageKey>("dashboard");
  const [health, setHealth] = useState<Health | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || "dark");
  const [scale, setScale] = useState(() => Number(localStorage.getItem(SCALE_KEY) || 1));
  const toast = useToast();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.setProperty("--scale", String(scale));
  }, [theme, scale]);

  useEffect(() => {
    const onUnauthorized = () => setAuthed(false);
    window.addEventListener("fedo:unauthorized", onUnauthorized);
    return () => window.removeEventListener("fedo:unauthorized", onUnauthorized);
  }, []);

  const poll = useCallback(async () => {
    try {
      const data = await get<Health>("/api/health");
      setHealth(data);
      if (getToken()) {
        const status = await get<SyncStatus>("/api/sync/status").catch(() => null);
        if (status) setSync(status);
      }
    } catch {
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    poll();
    const timer = window.setInterval(poll, 15000);
    return () => window.clearInterval(timer);
  }, [poll, authed]);

  // Первичная настройка темы/масштаба с сервера (предпочтения синхронизируются)
  useEffect(() => {
    if (!authed) return;
    get<{ preferences: Record<string, unknown> }>("/api/preferences")
      .then((data) => {
        const remoteTheme = data.preferences.theme;
        const remoteScale = data.preferences.ui_scale;
        if (typeof remoteTheme === "string" && !localStorage.getItem(THEME_KEY)) setTheme(remoteTheme);
        if (typeof remoteScale === "number" && !localStorage.getItem(SCALE_KEY)) setScale(remoteScale);
      })
      .catch(() => undefined);
  }, [authed]);

  const savePreference = (key: string, value: unknown) => {
    getToken() && fetch("/api/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ key, value }),
    }).catch(() => undefined);
  };

  const changeTheme = (next: string) => {
    setTheme(next);
    savePreference("theme", next);
  };

  const changeScale = (next: number) => {
    setScale(next);
    savePreference("ui_scale", next);
  };

  const logout = async () => {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
      });
    } catch {
      /* игнорируем сетевые ошибки при выходе */
    }
    setToken("");
    setAuthed(false);
    toast.notify("Выход выполнен");
  };

  if (!authed) {
    return <Login onSuccess={() => { setAuthed(true); toast.success("Готово"); }} />;
  }

  const connection: ConnectionState = {
    backend: Boolean(health),
    syncOnline: Boolean(sync?.online),
    aiMode: sync?.role === "hub" ? "HUB" : "Desktop",
    pendingOps: sync?.pending_operations ?? 0,
  };

  return (
    <Layout page={page} onNavigate={setPage} connection={connection}
            onLogout={logout} theme={theme} onToggleTheme={() => changeTheme(theme === "dark" ? "light" : "dark")}>
      {page === "dashboard" ? <Dashboard onNavigate={setPage} /> : null}
      {page === "assistant" ? <Assistant /> : null}
      {page === "tasks" ? <Tasks /> : null}
      {page === "calendar" ? <Calendar /> : null}
      {page === "schedule" ? <Schedule /> : null}
      {page === "devices" ? <Devices /> : null}
      {page === "monitor" ? <Monitor /> : null}
      {page === "settings" ? (
        <Settings theme={theme} onThemeChange={changeTheme} scale={scale} onScaleChange={changeScale} />
      ) : null}
      {!health ? (
        <div className="badge danger" style={{ alignSelf: "flex-start" }}>
          Нет связи с локальным backend — данные могут быть неактуальны
        </div>
      ) : null}
    </Layout>
  );
}
