"""Offline regression checks for Flicker Link Pro relay."""
import asyncio
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
        assert x.status_code == 200 and "Allow laptop control" in x.text
        x = await client.post("/devices/pair", cookies=cookies,
                              headers={"Origin": BASE}, data={"csrf":"bad"})
        assert x.status_code == 403
        x = await client.post("/devices/pair", cookies=cookies,
                              headers={"Origin": BASE}, data={"csrf":csrf})
        assert x.status_code == 200
        match = re.search(r"--token\s+([A-Za-z0-9_.-]+)", x.text)
        assert match and main.device_registry().authenticate(match.group(1))["sub"] == account
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
        assert x.status_code == 200 and len(x.json()["result"]["tools"]) == 66
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
