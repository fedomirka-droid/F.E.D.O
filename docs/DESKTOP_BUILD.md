# F.E.D.O. Desktop — сборка и запуск

## Что внутри

```
desktop/
├── src/                 React + TypeScript (интерфейс, 8 разделов)
├── src-tauri/           Tauri 2: окно, запуск backend, завершение
│   ├── src/main.rs      spawn sidecar → health-check → окно → kill при выходе
│   ├── tauri.conf.json  конфигурация, CSP, targets: nsis + msi
│   └── binaries/        fedo-backend.exe (собирается отдельно)
├── scripts/             build-sidecar.ps1, sidecar_entry.py
└── package.json         vite / tsc / tauri
```

## Требования (Windows 11)

1. Node.js 20+ и npm.
2. Python 3.11+ (для backend и sidecar).
3. Rust toolchain (rustup, target `x86_64-pc-windows-msvc`).
4. Visual Studio Build Tools с «Desktop development with C++»
   и WebView2 (в Windows 11 уже есть).

## Режим разработки

```powershell
# 1. backend (локальный, без Tauri)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-ecosystem.txt
$env:FEDO_ROLE="desktop"
python -m ecosystem.backend --role desktop --port 8765

# 2. интерфейс (второй терминал)
cd desktop
npm install
npm run dev          # http://localhost:5173, /api проксируется на :8765
```

Dev-режим Tauri (окно приложения, backend запускается из `.venv`):

```powershell
cd desktop
npm run tauri dev
```

## Сборка установщика

```powershell
# sidecar backend → desktop\src-tauri\binaries\fedo-backend.exe
.\desktop\scripts\build-sidecar.ps1

cd desktop
npm install
npm run build                  # tsc + vite build → desktop\dist
npm run tauri build            # установщики в desktop\src-tauri\target\release\bundle
```

Результат:

* `bundle\nsis\F.E.D.O._2.0.0_x64-setup.exe`
* `bundle\msi\F.E.D.O._2.0.0_x64_en-US.msi`

## Как запускается приложение

1. `main.rs` проверяет `http://127.0.0.1:8765/api/health`.
2. Если backend не запущен — стартует sidecar (`release`) или
   `.venv\Scripts\python.exe -m ecosystem.backend` (`dev`).
3. Ждёт health до 45 секунд, создаёт окно `http://127.0.0.1:8765`.
   Backend раздаёт собранный frontend и API по одному origin — CORS не нужен.
4. При закрытии окна процесс backend получает `kill` и `wait`.

Если backend не поднялся, окно откроется с локальной сборкой `index.html`
и покажет предупреждение «Нет связи с локальным backend».

## Где хранятся данные

`%APPDATA%\FEDO\`:

```
fedo.db                SQLite (задачи, календарь, расписание, outbox)
secret.key             ключ шифрования секретов (0600)
backups\               копии перед миграциями
logs\
```

HUB-токен устройства и адрес сервера — переменные окружения
`FEDO_SYNC_DEVICE_TOKEN`, `FEDO_HUB_URL` (или `.env` рядом с приложением).

## Проверка перед сборкой

```powershell
cd desktop
npm run typecheck
npm run build
```

CI-аналог локально:

```bash
pytest -q            # backend + интеграционные тесты (моки, без железа)
```

## Linux (позже)

`src-tauri` кросс-платформенный: достаточно установить
`webkit2gtk-4.1`, `libappindicator3`, Rust target и собрать
`npm run tauri build`. Sidecar собирается PyInstaller под Linux.
