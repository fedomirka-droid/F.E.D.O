"""Запуск бэкенда: python -m ecosystem.backend [--role hub|desktop]."""
from __future__ import annotations

import argparse
import os

import uvicorn

from .app import create_app
from .config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="F.E.D.O. Ecosystem backend")
    parser.add_argument("--role", choices=["hub", "desktop"], default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    if args.role:
        os.environ["FEDO_ROLE"] = args.role
    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
