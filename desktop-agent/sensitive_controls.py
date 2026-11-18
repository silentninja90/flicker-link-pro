"""Local, pairing-bound consent for sensitive remote computer controls."""
from __future__ import annotations

import time
from pathlib import Path

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
        root.geometry("700x570")
        root.minsize(700, 570)
        root.resizable(False, False)
        root.configure(bg="#0D1023")
        root.attributes("-topmost", True)

        icon_path = Path(__file__).resolve().with_name("flicker-link.ico")
        if icon_path.is_file():
            try:
                root.iconbitmap(default=str(icon_path))
            except (OSError, tk.TclError):
                pass

        # Use the same navy, cyan, amber, and pale text palette as the website.
        background = "#0D1023"
        panel = "#14172F"
        line = "#343D5C"
        text_color = "#F6F7FF"
        muted = "#B8C1D9"
        cyan = "#43E3EE"
        amber = "#FFBC63"

        outer = tk.Frame(root, bg=background)
        outer.pack(fill="both", expand=True, padx=20, pady=18)

        header = tk.Frame(outer, bg=background)
        header.pack(fill="x", pady=(0, 14))
        logo = None
        if icon_path.is_file():
            try:
                from PIL import Image, ImageTk

                with Image.open(icon_path) as image:
                    image = image.convert("RGBA")
                    image.thumbnail((42, 42), Image.Resampling.LANCZOS)
                    logo = ImageTk.PhotoImage(image)
            except (OSError, ImportError, tk.TclError):
                logo = None
        if logo is not None:
            logo_label = tk.Label(header, image=logo, bg=background)
            logo_label.image = logo
            logo_label.pack(side="left", padx=(0, 12))
        brand = tk.Frame(header, bg=background)
        brand.pack(side="left", fill="y")
        tk.Label(
            brand, text="Flicker Link Pro", bg=background, fg=text_color,
            font=("Segoe UI", 13, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            brand, text="WINDOWS COMPANION  ·  ACCESS REVIEW", bg=background,
            fg=cyan, font=("Segoe UI", 8, "bold"), anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        card = tk.Frame(
            outer, bg=panel, highlightbackground=line, highlightthickness=1,
        )
        card.pack(fill="both", expand=True)

        heading = tk.Label(
            card, text="Approve sensitive controls?", bg=panel, fg=text_color,
            font=("Segoe UI", 16, "bold"), anchor="w", justify="left",
        )
        heading.pack(fill="x", padx=22, pady=(22, 6))

        request = tk.Label(
            card, text=f"Waiting to use: {tool_name}", bg=panel, fg=amber,
            font=("Segoe UI", 10, "bold"), anchor="w", justify="left",
        )
        request.pack(fill="x", padx=22, pady=(0, 10))

        warning = (
            "If you approve, this paired connection can use all sensitive Flicker Link Pro tools "
            "until you sign out or remove this computer. It will not ask again for each action.\n\n"
            "That includes reading, creating, changing, moving, and deleting any files your "
            "Windows account can access; running commands including WSL; controlling processes "
            "and Docker; running SQL with connection details you provide; transferring files "
            "over HTTPS; taking screenshots; and using the keyboard, mouse, and windows.\n\n"
            "Approve only if you initiated this connection and want to grant this access."
        )
        body = tk.Label(
            card, text=warning, bg=panel, fg=muted, font=("Segoe UI", 10),
            anchor="nw", justify="left", wraplength=630,
        )
        body.pack(fill="both", expand=True, padx=22, pady=(0, 10))

        buttons = tk.Frame(card, bg=panel)
        buttons.pack(fill="x", padx=22, pady=(8, 20))

        def choose(value: bool):
            choice["allowed"] = value
            if root is not None:
                root.destroy()

        def dismiss():
            if root is not None:
                root.destroy()

        deny = tk.Button(
            buttons, text="Deny", width=14, command=lambda: choose(False),
            bg=panel, fg=text_color, activebackground=line, activeforeground=text_color,
            relief="flat", bd=1, highlightthickness=1, highlightbackground=line,
            font=("Segoe UI", 10, "bold"), cursor="hand2", padx=8, pady=8,
        )
        deny.pack(side="right", padx=(8, 0))
        approve = tk.Button(
            buttons, text="Approve for this pairing", width=24,
            command=lambda: choose(True), bg=cyan, fg=background,
            activebackground="#A3F7FC", activeforeground=background,
            relief="flat", bd=0, font=("Segoe UI", 10, "bold"),
            cursor="hand2", padx=8, pady=9,
        )
        approve.pack(side="right")
        root.protocol("WM_DELETE_WINDOW", dismiss)
        root.bind("<Escape>", lambda _event: dismiss())
        root.after(timeout_ms, dismiss)
        deny.focus_set()
        root.update_idletasks()
        x = max(0, (root.winfo_screenwidth() - root.winfo_width()) // 2)
        y = max(0, (root.winfo_screenheight() - root.winfo_height()) // 2)
        root.geometry(f"+{x}+{y}")
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
