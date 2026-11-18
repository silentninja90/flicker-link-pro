"""Entry point for the consumer Windows app."""

import argparse
import ctypes
import os
from pathlib import Path
import sys


def show_startup_banner(connecting: bool = True) -> None:
    """Print a compact, readable brand header before the relay initializes."""
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetConsoleTitleW("Flicker Link Pro - Windows Companion")
        except (AttributeError, OSError):
            pass
    print(r"""
  +------------------------------------------------------------+
  |  🔗 Flicker Link Pro                                        |
  |  🖥️ Windows Companion                                      |
  +------------------------------------------------------------+
  |  Secure computer connection for ChatGPT                   |
  |  Keep this window open; you can minimize it.               |
  +------------------------------------------------------------+
""", flush=True)
    if connecting:
        print("🔗  Starting secure connection...", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flicker Link Pro")
    parser.add_argument("--logout", action="store_true", help="Sign out and remove this pairing")
    args = parser.parse_args()
    show_startup_banner(connecting=not args.logout)
    origin = Path(__file__).with_name("consumer-relay.txt").read_text(encoding="ascii").strip()
    sys.argv[1:] = ["--profile", "consumer", "--server", origin]
    if args.logout:
        sys.argv.append("--logout")
    from flicker_relay_agent import main
    main()
