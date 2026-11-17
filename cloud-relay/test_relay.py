"""Offline regression checks for Flicker Link Pro relay."""
import asyncio
import json
from unittest.mock import patch
import os
import re
import secrets
import urllib.parse
import tempfile
import atexit
from pathlib import Path

_registry_temp = tempfile.TemporaryDirectory()
atexit.register(_registry_temp.cleanup)
os.environ["FLICKER_DB_PATH"] = str(Path(_registry_temp.name) / "pairings.sqlite3")

os.environ["FLICKER_SECRET"] = "test-only-" + "a" * 48
os.environ["BASE_URL"] = "https://flicker-link-pro.onrender.com"
os.environ["GOOGLE_CLIENT_ID"] = "test-google-client.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "not-a-real-google-secret"

import httpx
import main

BASE = main.BASE_URL
RESOURCE = main.RESOURCE

async def test():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                 base_url=BASE, follow_redirects=False) as client:
        x = await client.get("/.well-known/oauth-protected-resource")
        assert x.status_code == 200 and x.json()["resource"] == RESOURCE
        x = await client.get("/.well-known/oauth-authorization-server")
        assert x.status_code == 200 and x.json()["code_challenge_methods_supported"] == ["S256"]
        x = await client.post("/mcp", json={"jsonrpc":"2.0","id":1,"method":"initialize"})
        assert x.status_code == 401 and "resource_metadata" in x.headers["www-authenticate"]
        x = await client.post("/oauth/register", json={
            "redirect_uris":["http://evil.com/callback"], "token_endpoint_auth_method":"none"})
        assert x.status_code == 400
        callback = "https://chatgpt.com/flicker-oauth-test-callback"
        x = await client.post("/oauth/register", json={
            "redirect_uris":[callback], "client_name":"Flicker test", "token_endpoint_auth_method":"none"})
        assert x.status_code == 201, x.text
        cid = x.json()["client_id"]
        verifier = secrets.token_urlsafe(48)
        params = {"client_id":cid, "redirect_uri":callback,"response_type":"code",
                  "state":"sample-state","scope":"laptop:control","resource":RESOURCE,
                  "code_challenge":main.digest(verifier),"code_challenge_method":"S256"}
        x = await client.get("/oauth/authorize",params=params)
        assert x.status_code == 307 and x.headers["location"].startswith("/auth/google/start")
        bad = dict(params, redirect_uri="https://evil.com/callback")
        x = await client.get("/oauth/authorize",params=bad)
        assert x.status_code == 400
        account = "verified-google-sub-not-email"
        csrf = secrets.token_urlsafe(24)
        session_token = main.sign("session", account, BASE + "/session",
                                  3600, email="verified@example.com", csrf=csrf)
        cookies = {"flp_session":session_token}
        x = await client.get("/oauth/authorize", params=params, cookies=cookies)
        assert x.status_code == 200 and "Allow computer access" in x.text
        x = await client.post("/devices/pair", cookies=cookies,
                              headers={"Origin": BASE}, data={"csrf":"bad"})
        assert x.status_code == 403
        x = await client.post("/devices/pair", cookies=cookies,
                              headers={"Origin": BASE}, data={"csrf":csrf})
        assert x.status_code == 200
        match = re.search(r"<pre[^>]*>(flk2_[A-Za-z0-9_-]+)</pre>", x.text)
        assert match and main.device_registry().authenticate(match.group(1))["sub"] == account
        device_id = main.device_registry().authenticate(match.group(1))["id"]
        assert "--token" not in x.text
        x = await client.get("/devices", cookies=cookies)
        assert x.status_code == 200 and "Paired, waiting for the Windows app" in x.text
        form = {"csrf": csrf, "device_id": device_id, "label": "Travel Laptop"}
        x = await client.post("/devices/rename", cookies=cookies, headers={"Origin": BASE},
                              data={**form, "csrf": "wrong"})
        assert x.status_code == 403
        other_token = main.sign("session", "another-account", BASE + "/session", 3600, csrf=csrf)
        x = await client.post("/devices/rename", cookies={"flp_session": other_token},
                              headers={"Origin": BASE}, data=form)
        assert x.status_code == 404
        x = await client.post("/devices/rename", cookies=cookies, headers={"Origin": BASE},
                              data={**form, "label": "   "})
        assert x.status_code == 400
        x = await client.post("/devices/rename", cookies=cookies, headers={"Origin": BASE}, data=form)
        assert x.status_code == 303
        assert main.device_registry().authenticate(match.group(1))["label"] == "Travel Laptop"
        code = main.sign("auth_code", account, BASE + "/authcode", 90,
                         client_hash=main.digest(cid), redirect_uri=callback,
                         challenge=main.digest(verifier), resource=RESOURCE, scope="laptop:control")
        exchange = {"grant_type":"authorization_code","client_id":cid,"code":code,
                    "redirect_uri":callback,"code_verifier":verifier,"resource":RESOURCE}
        x = await client.post("/oauth/token",data=dict(exchange,code_verifier="bad"))
        assert x.status_code == 400
        x = await client.post("/oauth/token",data=exchange)
        assert x.status_code == 200, x.text
        body = x.json()
        x = await client.post("/oauth/token",data=exchange)
        assert x.status_code == 400
        assert "refresh_token" not in body
        auth = {"Authorization":"Bearer " + body["access_token"]}
        x = await client.post("/mcp",headers=auth,
                              json={"jsonrpc":"2.0","id":11,"method":"initialize",
                                    "params":{"protocolVersion":"2025-11-25"}})
        assert x.status_code == 200 and x.json()["result"]["protocolVersion"] == "2025-11-25"
        x = await client.post("/mcp",headers=auth,
                              json={"jsonrpc":"2.0","id":12,"method":"tools/list"})
        assert x.status_code == 200
        catalog = x.json()["result"]["tools"]
        assert len(catalog) == 66
        expected_auth = [{"type": "oauth2", "scopes": ["laptop:control"]}]
        assert all(tool["securitySchemes"] == expected_auth for tool in catalog)
        assert all(tool["_meta"]["securitySchemes"] == expected_auth for tool in catalog)
        x = await client.post("/mcp", headers=auth, json={
            "jsonrpc": "2.0", "id": 15, "method": "tools/call", "params": {"name": "list_devices"}
        })
        assert x.json()["result"]["structuredContent"]["devices"][0]["label"] == "Travel Laptop"

        class Desktop:
            async def send_text(self, data):
                call_id = json.loads(data)["id"]
                main.PENDING_CALLS[call_id][1].set_result({
                    "structuredContent": {"hostname": "DESKTOP-TEST", "platform": "win32"}
                })

        main.ACTIVE_SOCKETS[account] = Desktop()
        main.ACTIVE_DEVICE_IDS[account] = device_id
        try:
            x = await client.post("/mcp", headers=auth, json={
                "jsonrpc": "2.0", "id": 16, "method": "tools/call", "params": {"name": "who_am_i"}
            })
            identity = x.json()["result"]["structuredContent"]
            assert identity["device_name"] == "Travel Laptop"
            assert identity["hostname"] == "DESKTOP-TEST"
        finally:
            main.ACTIVE_SOCKETS.pop(account, None)
            main.ACTIVE_DEVICE_IDS.pop(account, None)

        class IdleDevice:
            def __init__(self, token):
                self.headers = {"authorization": "Bearer " + token}
                self.accepted = False
                self.ping = None
                self.receives = 0

            async def accept(self):
                self.accepted = True

            async def receive_text(self):
                self.receives += 1
                if self.receives == 1:
                    await asyncio.Event().wait()
                if self.receives == 2:
                    return json.dumps({"id": self.ping["id"], "result": {}})
                raise main.WebSocketDisconnect()

            async def send_json(self, message):
                self.ping = message

        idle_device = IdleDevice(match.group(1))
        with patch.object(main, "DEVICE_HEARTBEAT_INTERVAL", 0.01):
            await main.device_websocket(idle_device)
        assert idle_device.accepted and idle_device.ping["method"] == "ping"
        assert idle_device.receives == 3 and account not in main.ACTIVE_SOCKETS
        assert not main.PENDING_CALLS
        x = await client.post("/mcp",headers=auth,
                              json={"jsonrpc":"2.0","id":13,"method":"tools/call",
                                    "params":{"name":"unused"}})
        assert x.status_code == 200 and "offline" in x.json()["error"]["message"].lower()
        x = await client.post("/mcp",headers={"Authorization":"Bearer " + session_token},
                              json={"jsonrpc":"2.0","id":14,"method":"tools/list"})
        assert x.status_code == 401
    print("PASS: OAuth discovery, PKCE, DCR, session/CSRF, device pairing, 66 tools, token audience, replay checks")

if __name__ == "__main__":
    asyncio.run(test())
