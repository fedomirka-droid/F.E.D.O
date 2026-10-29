import { useEffect, useState } from "react";
import { api, post, setToken } from "../api";
import { Field, Spinner, useToast } from "../ui";

type Status = { owner_exists: boolean; needs_setup: boolean; setup_token_required: boolean; role: string };

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [username, setUsername] = useState("owner");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api<Status>("/api/auth/status")
      .then(setStatus)
      .catch(() => setError("Backend недоступен. Запусти локальный сервер F.E.D.O."));
  }, []);

  const submit = async () => {
    setError("");
    setBusy(true);
    try {
      if (status?.needs_setup) {
        if (password !== confirm) throw new Error("Пароли не совпадают");
        const result = await api<{ token: string }>("/api/auth/setup", {
          method: "POST",
          headers: status.setup_token_required ? { "X-Setup-Token": setupToken } : {},
          body: JSON.stringify({ username, password }),
        });
        setToken(result.token);
        toast.success("Владелец создан. Добро пожаловать!");
      } else {
        const result = await post<{ token: string }>("/api/auth/login", { username, password });
        setToken(result.token);
        toast.success("Вход выполнен");
      }
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка входа");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="card login-card">
        <div className="brand">
          <div className="brand-mark">FE</div>
          <div className="brand-text">
            <strong>F.E.D.O.</strong>
            <span>Ecosystem · Personal Edition</span>
          </div>
        </div>

        {!status ? (
          <div className="row" style={{ gap: 10 }}>
            <Spinner /> <span className="muted">Проверка backend…</span>
          </div>
        ) : (
          <div className="stack">
            <h2>{status.needs_setup ? "Первичная настройка" : "Вход в систему"}</h2>
            <p className="muted small">
              {status.needs_setup
                ? "Создаётся единственный владелец Personal Edition. Публичная регистрация отключена."
                : "Данные хранятся локально на этом устройстве."}
            </p>

            <Field label="Имя владельца">
              <input className="input" value={username}
                     onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
            </Field>
            <Field label="Пароль (минимум 8 символов)">
              <input className="input" type="password" value={password}
                     onChange={(event) => setPassword(event.target.value)}
                     autoComplete={status.needs_setup ? "new-password" : "current-password"} />
            </Field>
            {status.needs_setup ? (
              <>
                <Field label="Повтори пароль">
                  <input className="input" type="password" value={confirm}
                         onChange={(event) => setConfirm(event.target.value)} autoComplete="new-password" />
                </Field>
                {status.setup_token_required ? (
                  <Field label="Токен первичной настройки">
                    <input className="input" value={setupToken}
                           onChange={(event) => setSetupToken(event.target.value)} />
                  </Field>
                ) : null}
              </>
            ) : null}

            {error ? <div className="badge danger">{error}</div> : null}

            <button className="btn primary" onClick={submit} disabled={busy || !password}>
              {busy ? <Spinner /> : null}
              {status.needs_setup ? "Создать владельца" : "Войти"}
            </button>
            <p className="hint">Роль: {status.role === "hub" ? "HUB" : "Desktop"} · F.E.D.O. 2.0</p>
          </div>
        )}
      </div>
    </div>
  );
}
