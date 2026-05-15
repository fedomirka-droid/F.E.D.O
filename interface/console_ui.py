from colorama import Fore, Style, init

init(autoreset=True)


def show_banner():
    print(Fore.YELLOW + r"""
███████╗   ███████╗   ██████╗    ██████╗
██╔════╝   ██╔════╝   ██╔══██╗   ██╔══██╗
█████╗     █████╗     ██║  ██║   ██║  ██║
██╔══╝     ██╔══╝     ██║  ██║   ██║  ██║
██║        ███████╗   ██████╔╝   ██████╔╝
╚═╝        ╚══════╝   ╚═════╝    ╚═════╝
""" + Style.RESET_ALL)

    print(Fore.LIGHTBLACK_EX + "Functional Event Detection Operator")
    print(Fore.YELLOW + "VERSION: 1.0")
    print(Fore.LIGHTBLACK_EX + "STATUS: ONLINE")
    print("-" * 45)


def print_user(text: str):
    print(Fore.CYAN + f"Ты: {text}")


def print_assistant(text: str):
    print(Fore.YELLOW + f"F.E.D.O: {text}")


def print_system(text: str):
    print(Fore.LIGHTBLACK_EX + f"[SYSTEM] {text}")


def input_user():
    return input(Fore.CYAN + "Ты: " + Style.RESET_ALL)