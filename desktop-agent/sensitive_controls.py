"""Local, pairing-bound consent for sensitive remote computer controls."""
from __future__ import annotations

import time

from credential_store import load_sensitive_consent, save_sensitive_consent


# Only basic identity, pairing, and health reads are available before consent.
# Every other catalog entry, including future tools, is sensitive by default.
NON_SENSITIVE_TOOLS = frozenset({
    "who_am_i",
    "list_devices",
    "get_config",
    "system_resources",
    "get_usage_stats",
})

PROMPT_TIMEOUT_MS = 30_000


def is_sensitive_tool(name: str) -> bool:
    return name not in NON_SENSITIVE_TOOLS


def _show_local_warning(tool_name: str, timeout_ms: int) -> bool | None:
    """Show one timed local prompt; None means it was unavailable or unanswered."""
    try:
        import tkinter as tk
    except Exception:
        return None

    choice: dict[str, bool] = {}
    root = None
    try:
        root = tk.Tk()
        root.title("Flicker Link Pro — Sensitive Controls")
        root.geometry("620x470")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        heading = tk.Label(
            root,
            text="Approve sensitive controls for this computer?",
            font=("Segoe UI", 14, "bold"),
            anchor="w",
            justify="left",
        )
        heading.pack(fill="x", padx=22, pady=(20, 8))

        warning = (
            "A ChatGPT request is waiting to use: " + tool_name + ".\n\n"
            "If you approve, this paired connection can use all sensitive Flicker Link Pro tools "
            "until you sign out or remove this computer. It will not ask again for each action.\n\n"
            "That includes reading, creating, changing, moving, and deleting any files your "
            "Windows account can access; running commands including WSL; controlling processes "
            "and Docker; running SQL with connection details you provide; transferring files "
            "over HTTPS; taking screenshots; and using the keyboard, mouse, and windows.\n\n"
            "Approve only if you initiated this connection and want to grant this access."
        )
        body = tk.Label(
            root,
            text=warning,
            font=("Segoe UI", 10),
            anchor="nw",
            justify="left",
            wraplength=570,
        )
        body.pack(fill="both", expand=True, padx=22, pady=8)

        buttons = tk.Frame(root)
        buttons.pack(fill="x", padx=22, pady=(8, 18))

        def choose(value: bool):
            choice["allowed"] = value
            if root is not None:
                root.destroy()

        def dismiss():
            if root is not None:
                root.destroy()

        deny = tk.Button(buttons, text="Deny", width=16, command=lambda: choose(False))
        deny.pack(side="right", padx=(8, 0))
        approve = tk.Button(
            buttons, text="Approve for this pairing", width=24,
            command=lambda: choose(True),
        )
        approve.pack(side="right")
        root.protocol("WM_DELETE_WINDOW", dismiss)
        root.bind("<Escape>", lambda _event: dismiss())
        root.after(timeout_ms, dismiss)
        deny.focus_set()
        root.mainloop()
    except Exception:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass
        return None
    return choice.get("allowed")


def authorize_sensitive_tool(
    name: str, server: str, token: str, target: str,
    deadline_unix: float | None = None,
) -> bool:
    """Return true only when this pairing has a saved or newly approved grant."""
    if deadline_unix is not None and time.time() >= deadline_unix:
        return False
    decision = load_sensitive_consent(server, token, target)
    if decision == "allowed":
        return True
    if decision == "denied":
        return False

    timeout_ms = PROMPT_TIMEOUT_MS
    if deadline_unix is not None:
        timeout_ms = min(timeout_ms, max(1, int((deadline_unix - time.time()) * 1000)))
    answer = _show_local_warning(name, timeout_ms)
    if answer is None:
        return False
    if deadline_unix is not None and time.time() >= deadline_unix:
        return False
    save_sensitive_consent(
        server, token, "allowed" if answer else "denied", target
    )
    return answer
