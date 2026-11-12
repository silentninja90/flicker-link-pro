"""Flicker Link Pro Windows agent: Google pairing once, reconnect automatically.

Device credentials are stored in Windows Credential Manager, never in the shortcut,
a query string, a plaintext config file, or console output.
"""
from __future__ import annotations
import argparse
import asyncio
import getpass
import inspect
import json
import os
import webbrowser
import websockets

from credential_store import save_credential, load_credential, delete_credential
from flicker_server import handle, CATALOG

DEFAULT_SERVER = "https://flicker-link-pro.onrender.com"

def prompt_pairing(server: str):
    print("\nFlicker Link Pro - first-time setup")
    print("Opening the secure device-pairing page in your browser.")
    print("1. Sign in with Google.")
    print("2. Select Generate device pairing credential.")
    print("3. Copy the value after --token (not the entire command).")
    try:
        webbrowser.open(server.rstrip("/") + "/devices")
    except Exception:
        pass
    token = ""
    while not token:
        token = getpass.getpass("Paste your pairing credential (input hidden): ").strip()
    return server, token

def resolve_pairing(server: str | None, token: str | None):
    saved = load_credential()
    base = (server or (saved[0] if saved else DEFAULT_SERVER)).rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("Pairing requires an HTTPS cloud relay.")
    if token:
        save_credential(base, token)
        return base, token
    if saved and saved[0].rstrip("/") == base:
        print("[OK] Saved device pairing loaded securely from Windows.")
        return base, saved[1]
    new_server, new_token = prompt_pairing(base)
    save_credential(new_server, new_token)
    return new_server, new_token

async def run_relay(server_url: str, token: str):
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
    print("Flicker Link Pro | Tools loaded:", len(CATALOG))
    print("Connecting securely to", base)

    while True:
        try:
            async with websockets.connect(
                endpoint, max_size=15 * 1024 * 1024,
                ping_interval=20, ping_timeout=20, **headers
            ) as ws:
                print("[CONNECTED] Saved pairing accepted. Ready for ChatGPT commands.")
                while True:
                    request = json.loads(await ws.recv())
                    if request.get("method") == "tools/list":
                        result = {"tools": CATALOG}
                    else:
                        result_json = handle(request)
                        result = result_json.get("result", {}) if result_json else {}
                        if result_json and "error" in result_json:
                            result = {"isError": True, "error": result_json["error"]}
                    await ws.send(json.dumps({"id": request.get("id"), "result": result}))
        except (websockets.exceptions.InvalidStatus, websockets.exceptions.InvalidStatusCode) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (401, 403):
                print("[PAIRING INVALID] Device authorization expired or revoked.")
                print("Sign in to the relay, generate a new pairing, then launch with --token.")
                return
            print("[RETRY] Relay unavailable; retrying in 5 seconds.")
            await asyncio.sleep(5)
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError):
            print("[DISCONNECTED] Retrying in 5 seconds.")
            await asyncio.sleep(5)
        except Exception as exc:
            print("[ERROR]", type(exc).__name__, "retrying in 5 seconds.")
            await asyncio.sleep(5)

def main():
    parser = argparse.ArgumentParser(description="Flicker Link Pro Windows agent")
    parser.add_argument("--server", help="Optional HTTPS relay URL")
    parser.add_argument("--token", help="One-time pairing credential; saved securely")
    parser.add_argument("--logout", action="store_true", help="Forget this device's saved pairing")
    parser.add_argument("--uninstall", action="store_true", help="Erase saved pairing before uninstall")
    args = parser.parse_args()
    if args.logout or args.uninstall:
        delete_credential()
        print("[OK] Saved pairing removed from Windows Credential Manager.")
        return
    base, token = resolve_pairing(args.server, args.token)
    try:
        asyncio.run(run_relay(base, token))
    except KeyboardInterrupt:
        print("Flicker Link Pro stopped. Saved pairing retained.")

if __name__ == "__main__":
    main()
