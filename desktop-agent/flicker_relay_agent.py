"""Flicker Link Pro Windows agent: Google pairing once, reconnect automatically.

Device credentials are stored in Windows Credential Manager, never in the shortcut,
a query string, a plaintext config file, or console output.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import nullcontext
from datetime import datetime
import errno
import getpass
import inspect
import json
import os
import platform
from pathlib import Path
import re
import sys
import time
import webbrowser
import websockets
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from credential_store import (
    save_credential, load_credential, delete_credential,
    delete_sensitive_consent,
)
from flicker_server import handle, CATALOG
from sensitive_controls import authorize_sensitive_tool, is_sensitive_tool

DEFAULT_SERVER = "https://flicker-link-pro.onrender.com"
STAGING_SERVER = "https://flicker-link-pro-2-staging.onrender.com"
STAGING_CREDENTIAL_TARGET = "FlickerLinkPro2/StagingDevicePairing"
DEFAULT_CONSENT_TARGET = "FlickerLinkPro2/DeviceConsent"
STAGING_CONSENT_TARGET = "FlickerLinkPro2/StagingDeviceConsent"
CATALOG_NAMES = frozenset(tool["name"] for tool in CATALOG)


def console_status(icon: str, message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {icon}  {message}", flush=True)


def _websocket_is_open(ws) -> bool:
    state = getattr(ws, "state", None)
    if state is not None:
        return getattr(state, "name", str(state)).upper() == "OPEN"
    return bool(getattr(ws, "open", False))


def _server_confirms_revoked(server_url: str, token: str) -> bool:
    request = Request(
        server_url.rstrip("/") + "/devices/current",
        headers={"Authorization": "Bearer " + token},
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status == 401
    except HTTPError as exc:
        return exc.code == 401
    except (URLError, TimeoutError, OSError):
        return False


def _profile_for(server: str | None, profile: str | None) -> str:
    if profile not in (None, "default", "staging"):
        raise ValueError("Unknown pairing profile")
    if profile == "staging" or (server and server.rstrip("/") == STAGING_SERVER):
        if server and server.rstrip("/") != STAGING_SERVER:
            raise ValueError("Staging profile only accepts the staging relay")
        return "staging"
    return "default"


def _load_for(profile: str):
    return (load_credential(target=STAGING_CREDENTIAL_TARGET)
            if profile == "staging" else load_credential())


def _consent_target_for(profile: str) -> str:
    return STAGING_CONSENT_TARGET if profile == "staging" else DEFAULT_CONSENT_TARGET


def _save_for(profile: str, server: str, token: str):
    saved = _load_for(profile)
    if (not saved or saved[0].rstrip("/") != server.rstrip("/") or
            saved[1] != token):
        delete_sensitive_consent(_consent_target_for(profile))
    if profile == "staging":
        save_credential(server, token, target=STAGING_CREDENTIAL_TARGET)
    else:
        save_credential(server, token)


def _delete_for(profile: str):
    delete_sensitive_consent(_consent_target_for(profile))
    if profile == "staging":
        delete_credential(target=STAGING_CREDENTIAL_TARGET)
    else:
        delete_credential()

def read_masked_pairing(prompt: str, read_key=None, output=None) -> str:
    """Show an asterisk per console character; support paste and Backspace."""
    if read_key is None:
        if os.name != "nt":
            return getpass.getpass(prompt).strip()
        import msvcrt
        read_key = msvcrt.getwch
    output = output or sys.stdout
    output.write(prompt)
    output.flush()
    chars = []
    while True:
        key = read_key()
        if key in ("\r", "\n"):
            output.write("\n")
            output.flush()
            return "".join(chars).strip()
        if key in ("\b", "\x7f"):
            if chars:
                chars.pop()
                output.write("\b \b")
        elif key in ("\x00", "\xe0"):
            read_key()  # Ignore arrow/function-key scan code.
        elif key == "\x03":
            output.write("\n")
            output.flush()
            raise KeyboardInterrupt
        elif key.isprintable() and len(chars) < 1024:
            chars.append(key)
            output.write("*")
        output.flush()


def prompt_pairing(server: str):
    print("\nFlicker Link Pro 2 - computer pairing")
    print("Opening the secure device-pairing page in your browser.")
    print("1. Sign in with Google.")
    print("2. Choose Pair a new computer.")
    print("3. Copy ONLY the token beginning with flk2_ (after --token).")
    print("4. Paste it below. * appears for each character; Backspace erases.")
    try:
        webbrowser.open(server.rstrip("/") + "/devices")
    except Exception:
        pass
    while True:
        token = read_masked_pairing("Pairing token (* = typed/pasted character): ")
        if not token:
            print("[INPUT EMPTY] Paste the token, then press Enter.")
            continue
        if server.rstrip("/") == STAGING_SERVER and not re.fullmatch(
            r"flk2_[A-Za-z0-9_-]{16,512}", token
        ):
            print("[INVALID FORMAT] Paste only the flk2_ token, not the full command.")
            continue
        return server, token

def resolve_pairing(server: str | None, token: str | None,
                    profile: str | None = None):
    selected = _profile_for(server, profile)
    saved = _load_for(selected)
    fallback = STAGING_SERVER if selected == "staging" else DEFAULT_SERVER
    base = (server or (saved[0] if saved else fallback)).rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("Pairing requires an HTTPS cloud relay.")
    if selected == "staging" and base != STAGING_SERVER:
        raise ValueError("Staging credentials must use the staging relay.")
    if token:
        _save_for(selected, base, token)
        return base, token
    if saved and saved[0].rstrip("/") == base:
        console_status("🔒", "Saved pairing loaded from Windows.")
        return base, saved[1]
    new_server, new_token = prompt_pairing(base)
    _save_for(selected, new_server, new_token)
    return new_server, new_token

async def run_relay(server_url: str, token: str,
                    consent_target: str = DEFAULT_CONSENT_TARGET):
    base = server_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[8:]
    elif base.startswith("http://"):
        raise ValueError("An HTTPS relay is required")
    elif not base.startswith("wss://"):
        raise ValueError("Invalid relay URL")
    endpoint = base + "/ws/device"
    header_name = ("additional_headers"
                   if "additional_headers" in inspect.signature(websockets.connect).parameters
                   else "extra_headers")
    headers = {header_name: {"Authorization": "Bearer " + token}}
    # Staging needs a direct WSS connection on this machine; leave other profiles unchanged.
    direct_staging = (server_url.rstrip("/") == STAGING_SERVER and
                      "proxy" in inspect.signature(websockets.connect).parameters)
    connection_options = {"proxy": None} if direct_staging else {}
    console_status("🖥️", f"Computer: {platform.node()} | Tools: {len(CATALOG)}")
    console_status("🔗", "Connecting securely...")

    while True:
        try:
            async with websockets.connect(
                endpoint, max_size=15 * 1024 * 1024,
                ping_interval=20, ping_timeout=20, **headers, **connection_options
            ) as ws:
                console_status("✅", "Online. Ready for ChatGPT.")
                while True:
                    request = json.loads(await ws.recv())
                    if request.get("method") == "tools/list":
                        result = {"tools": CATALOG}
                    else:
                        params = request.get("params") or {}
                        tool_name = params.get("name") if request.get("method") == "tools/call" else None
                        if isinstance(tool_name, str) and tool_name in CATALOG_NAMES:
                            console_status("⚙️", f"Request: {tool_name}")
                        deadline = request.get("_flicker_deadline_unix")
                        if not isinstance(deadline, (int, float)):
                            deadline = None
                        if (request.get("method") == "tools/call" and deadline is not None
                                and time.time() >= deadline):
                            result = {
                                "isError": True,
                                "content": [{"type": "text", "text": "Tool request expired before execution; no action was run."}],
                            }
                            await ws.send(json.dumps({"id": request.get("id"), "result": result}))
                            continue
                        if isinstance(tool_name, str) and tool_name in CATALOG_NAMES and is_sensitive_tool(tool_name):
                            try:
                                approved = await asyncio.to_thread(
                                    authorize_sensitive_tool, tool_name, server_url,
                                    token, consent_target, deadline,
                                )
                            except Exception:
                                approved = False
                            # Revocation can close the WebSocket while the local
                            # approval dialog is open. Do not start the action.
                            if not _websocket_is_open(ws):
                                break
                            if deadline is not None and time.time() >= deadline:
                                approved = False
                            if not approved:
                                result = {
                                    "isError": True,
                                    "content": [{
                                        "type": "text",
                                        "text": (
                                            "Sensitive controls are not approved for this pairing; "
                                            "no action was run. If no warning appeared, open the "
                                            "Flicker Link Pro app on this computer. To change a "
                                            "saved denial, sign out and pair this computer again."
                                        ),
                                    }],
                                }
                                await ws.send(json.dumps({"id": request.get("id"), "result": result}))
                                continue
                        if request.get("method") == "tools/call":
                            if not _websocket_is_open(ws):
                                break
                            if deadline is not None and time.time() >= deadline:
                                result = {
                                    "isError": True,
                                    "content": [{"type": "text", "text": "Tool request expired before execution; no action was run."}],
                                }
                                await ws.send(json.dumps({"id": request.get("id"), "result": result}))
                                continue
                        result_json = await asyncio.to_thread(handle, request)
                        result = result_json.get("result", {}) if result_json else {}
                        if result_json and "error" in result_json:
                            result = {"isError": True, "error": result_json["error"]}
                    await ws.send(json.dumps({"id": request.get("id"), "result": result}))
        except websockets.exceptions.InvalidHandshake as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", getattr(exc, "status_code", None))
            if status in (401, 403):
                if _server_confirms_revoked(server_url, token):
                    print("[PAIRING INVALID] Device authorization expired or revoked.")
                    print("Sign in to staging and generate a fresh device token to retry.")
                    return False
                print("[RETRY] Pairing status could not be confirmed; keeping saved credentials.")
            console_status("⚠️", "Relay unavailable. Retrying in 5 seconds.")
            await asyncio.sleep(5)
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError):
            console_status("🔄", "Disconnected. Reconnecting in 5 seconds.")
            await asyncio.sleep(5)
        except Exception as exc:
            console_status("⚠️", f"{type(exc).__name__}. Retrying in 5 seconds.")
            await asyncio.sleep(5)

def logout_pairing(profile: str | None = None) -> bool:
    """Revoke only the selected server credential before deleting its local copy."""
    selected = _profile_for(None, profile)
    saved = _load_for(selected)
    if not saved:
        _delete_for(selected)
        print("[LOGGED OUT] No pairing credential remains on this computer.")
        return True
    server, token = saved
    if not server.startswith("https://"):
        print("[LOGOUT FAILED] Refusing to send a credential over an insecure connection.")
        return False
    request = Request(
        server.rstrip("/") + "/devices/revoke-current",
        headers={"Authorization": "Bearer " + token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 204:
                print("[LOGOUT FAILED] Server did not confirm revocation.")
                return False
    except HTTPError as exc:
        if exc.code != 401:
            print("[LOGOUT FAILED] Server did not confirm revocation.")
            return False
        # 401 means this credential is already invalid server-side.
    except (URLError, TimeoutError, OSError):
        print("[LOGOUT FAILED] Could not reach the server to revoke this computer.")
        print("Saved pairing retained; retry logout when online or revoke from your web dashboard.")
        return False
    _delete_for(selected)
    print("[LOGGED OUT] Server authorization revoked and saved pairing removed.")
    return True

def staging_instance_lock():
    """Hold a Windows file lock for the life of the staging process."""
    if os.name != "nt":
        return nullcontext()
    import msvcrt

    folder = Path(os.environ["LOCALAPPDATA"]) / "FlickerLinkPro2"
    folder.mkdir(parents=True, exist_ok=True)
    lock = (folder / "staging-agent.lock").open("a+b")
    try:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        lock.close()
        if exc.errno == errno.EACCES:
            return None
        raise
    return lock


def main():
    parser = argparse.ArgumentParser(description="Flicker Link Pro Windows agent")
    parser.add_argument("--server", help="Optional HTTPS relay URL")
    parser.add_argument("--profile", choices=("default", "staging"), default=None,
                        help="Independent credential profile; staging never changes existing pairing")
    parser.add_argument("--token", help="Pairing credential; saved securely")
    parser.add_argument("--logout", action="store_true", help="Forget this device's saved pairing")
    parser.add_argument("--uninstall", action="store_true", help="Erase saved pairing before uninstall")
    args = parser.parse_args()
    if args.logout or args.uninstall:
        if not logout_pairing(profile=args.profile):
            raise SystemExit(1)
        return
    selected = _profile_for(args.server, args.profile)
    print("\n  Flicker Link Pro\n  Windows Companion · Staging", flush=True)
    print("  ----------------------------------------", flush=True)
    print("  Keep this window open. You can minimize it.", flush=True)
    print("  Ctrl+C to disconnect. Use Sign Out to unpair.\n", flush=True)
    lock = staging_instance_lock() if selected == "staging" else nullcontext()
    if lock is None:
        print("[ALREADY RUNNING] The staging agent is already connected or starting.")
        return
    with lock:
        run_agent(args, selected)


def run_agent(args, selected):
    try:
        base, token = resolve_pairing(args.server, args.token, profile=args.profile)
        while True:
            result = asyncio.run(run_relay(base, token, _consent_target_for(selected)))
            if result is not False:
                break
            # A rejected device credential confirms revocation; remove its local
            # pairing and consent before exiting or asking for a replacement.
            _delete_for(selected)
            if selected != "staging":
                break
            print("[RETRY PAIRING] The previous staging token was not accepted.")
            print("Create a fresh device pairing from the staging dashboard.")
            base, token = prompt_pairing(STAGING_SERVER)
            _save_for("staging", base, token)
    except KeyboardInterrupt:
        console_status("⏹️", "Disconnected. Saved pairing retained.")

if __name__ == "__main__":
    main()
