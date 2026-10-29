"""Точка входа для PyInstaller-сборки backend (Tauri sidecar)."""
import uvicorn

from ecosystem.backend.app import create_app
from ecosystem.backend.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host="127.0.0.1", port=settings.port, log_level="info")
