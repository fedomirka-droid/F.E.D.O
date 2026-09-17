"""
F.E.D.O — точка входа (v1.4)

Режимы:
    python main.py            → GUI (CustomTkinter)
    python main.py --console  → консольный режим (Linux/сервер/terminal)
"""
import os
import sys

import certifi

from core.proxy_guard import disable_proxy_for_local_project


disable_proxy_for_local_project()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()


def main():
    if "--console" in sys.argv:
        from core.assistant import run_assistant
        run_assistant()
    else:
        from interface.gui import run_gui
        run_gui()


if __name__ == "__main__":
    main()
