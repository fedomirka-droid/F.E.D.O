import os


def disable_proxy_for_local_project():
    """
    Защита F.E.D.O от VPN / SOCKS / proxy-переменных,
    которые могут ломать pip, requests, torch.hub и локальный LM Studio.
    """

    proxy_vars = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "PIP_PROXY",
    ]

    for var in proxy_vars:
        if var in os.environ:
            os.environ.pop(var, None)

    os.environ["NO_PROXY"] = "localhost,127.0.0.1"
    os.environ["no_proxy"] = "localhost,127.0.0.1"

    print("[PROXY] Proxy-переменные очищены.")
    print("[PROXY] localhost и 127.0.0.1 добавлены в исключения.")