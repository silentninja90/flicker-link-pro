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
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from credential_store import save_credential, load_credential, delete_credential
from flicker_server import handle, CATALOG

DEFAULT_SERVER = "https://flicker-link-pro.onrender.com"
STAGING_SERVER = "https://flicker-link-pro-2-staging.onrender.com"
STAGING_CREDENTIAL_TARGET = "FlickerLinkPro2/StagingDevicePairing"


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


def _save_for(profile: str, server: str, token: str):
    if profile == "staging":
        save_credential(server, token, target=STAGING_CREDENTIAL_TARGET)
    else:
        save_credential(server, token)


def _delete_for(profile: str):
    if profile == "staging":
        delete_credential(target=STAGING_CREDENTIAL_TARGET)
    else:
        delete_credential()

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
        print("[OK] Saved device pairing loaded securely from Windows.")
        return base, saved[1]
    new_server, new_token = prompt_pairing(base)
    _save_for(selected, new_server, new_token)
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
    # Staging needs a direct WSS connection on this machine; leave other profiles unchanged.
    direct_staging = (server_url.rstrip("/") == STAGING_SERVER and
                      "proxy" in inspect.signature(websockets.connect).parameters)
    connection_options = {"proxy": None} if direct_staging else {}
    print("Flicker Link Pro | Tools loaded:", len(CATALOG))
    print("Connecting securely to", base)

    while True:
        try:
            async with websockets.connect(
                endpoint, max_size=15 * 1024 * 1024,
                ping_interval=20, ping_timeout=20, **headers, **connection_options
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
    base, token = resolve_pairing(args.server, args.token, profile=args.profile)
    try:
        asyncio.run(run_relay(base, token))
    except KeyboardInterrupt:
        print("Flicker Link Pro stopped. Saved pairing retained.")

if __name__ == "__main__":
    main()
