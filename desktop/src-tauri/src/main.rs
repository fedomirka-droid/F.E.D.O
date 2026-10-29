// F.E.D.O. Desktop — точка входа Tauri 2.
//
// Логика запуска:
//   1) старт локального Python-backend как sidecar (Windows: fedo-backend.exe,
//      dev: python -m ecosystem.backend);
//   2) ожидание готовности /api/health (TCP + HTTP);
//   3) открытие окна на http://127.0.0.1:8765 (backend раздаёт собранный frontend);
//   4) при закрытии окна backend корректно останавливается.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

const BACKEND_PORT: u16 = 8765;
const BACKEND_URL: &str = "http://127.0.0.1:8765";

struct BackendProcess(Mutex<Option<Child>>);

fn health_ok() -> bool {
    let addr: SocketAddr = format!("127.0.0.1:{}", BACKEND_PORT).parse().unwrap();
    let mut stream = match TcpStream::connect_timeout(&addr, Duration::from_millis(600)) {
        Ok(stream) => stream,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(900)));
    let request = "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut buffer = [0u8; 512];
    match stream.read(&mut buffer) {
        Ok(size) if size > 0 => {
            let text = String::from_utf8_lossy(&buffer[..size]);
            text.starts_with("HTTP/1.1 200") || text.starts_with("HTTP/1.0 200")
        }
        _ => false,
    }
}

fn repo_root() -> PathBuf {
    // dev: <repo>/desktop/src-tauri → <repo>
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .map(|path| path.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."))
}

fn spawn_backend(app: &tauri::AppHandle) -> Option<Child> {
    if health_ok() {
        // backend уже запущен (например, при отладке) — не дублируем
        return None;
    }

    let mut command = if cfg!(debug_assertions) {
        let python = if cfg!(windows) {
            repo_root().join(".venv").join("Scripts").join("python.exe")
        } else {
            repo_root().join(".venv").join("bin").join("python")
        };
        let mut cmd = Command::new(python);
        cmd.args(["-m", "ecosystem.backend", "--role", "desktop", "--port", "8765"]);
        cmd.current_dir(repo_root());
        cmd
    } else {
        // release: sidecar-бинарь рядом с приложением
        let sidecar = app
            .path()
            .resource_dir()
            .map(|dir| dir.join("binaries").join(if cfg!(windows) { "fedo-backend.exe" } else { "fedo-backend" }))
            .unwrap_or_else(|_| PathBuf::from("fedo-backend.exe"));
        let mut cmd = Command::new(sidecar);
        cmd.args(["--role", "desktop", "--port", "8765"]);
        cmd
    };

    command.stdout(Stdio::null()).stderr(Stdio::null()).stdin(Stdio::null());
    command.spawn().ok()
}

fn wait_for_backend(timeout: Duration) -> bool {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if health_ok() {
            return true;
        }
        sleep(Duration::from_millis(400));
    }
    false
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let child = spawn_backend(app.handle());
            let ready = wait_for_backend(Duration::from_secs(45));
            app.manage(BackendProcess(Mutex::new(child)));

            let url = if ready {
                WebviewUrl::External(BACKEND_URL.parse().unwrap())
            } else {
                WebviewUrl::App("index.html".into())
            };
            WebviewWindowBuilder::new(app, "main", url)
                .title("F.E.D.O. Desktop")
                .inner_size(1280.0, 840.0)
                .min_inner_size(960.0, 640.0)
                .resizable(true)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("ошибка запуска F.E.D.O. Desktop")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
                if let Some(state) = app_handle.try_state::<BackendProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
            }
        });
}
