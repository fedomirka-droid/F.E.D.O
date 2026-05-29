import os
import certifi

from core.proxy_guard import disable_proxy_for_local_project


disable_proxy_for_local_project()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from interface.gui import run_gui


if __name__ == "__main__":
    run_gui()