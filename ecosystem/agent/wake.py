"""Wake-on-LAN: магический пакет (без внешних зависимостей)."""
from __future__ import annotations

import re
import socket


def normalize_mac(mac: str) -> bytes:
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(cleaned) != 12:
        raise ValueError("MAC-адрес должен содержать 12 hex-символов")
    return bytes.fromhex(cleaned)


def magic_packet(mac: str) -> bytes:
    return b"\xff" * 6 + normalize_mac(mac) * 16


def send_magic_packet(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> int:
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        return sock.sendto(packet, (broadcast, port))
