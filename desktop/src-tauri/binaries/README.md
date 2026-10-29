# Sidecar backend

Сюда кладётся собранный бинарник backend (Windows: `fedo-backend.exe`).
Он попадает в установщик как resource и запускается при старте приложения
(`src-tauri/src/main.rs` → `spawn_backend`).

Сборка (Windows, PowerShell):

```powershell
.\desktop\scripts\build-sidecar.ps1
```

В dev-режиме (`npm run tauri dev`) sidecar не нужен: Tauri запускает
`.venv\Scripts\python.exe -m ecosystem.backend` из корня репозитория.

Бинарники не коммитятся в Git (см. .gitignore).
