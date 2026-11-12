"""API tests for durable pairing, owner-only revoke, and desktop logout."""
import asyncio
import os
import re
import tempfile
from pathlib import Path

os.environ["FLICKER_SECRET"] = "test-secret-flicker-link-" + "z" * 45
os.environ["BASE_URL"] = "https://flicker-link-pro.onrender.com"
os.environ["GOOGLE_CLIENT_ID"] = "fake.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-only-not-real"

import httpx
import main

BASE = main.BASE_URL

async def run():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["FLICKER_DB_PATH"] = str(Path(tmp) / "device_registry.sqlite3")
        owner = "google-account-1"
        csrf = "csrf-strong-" + "x" * 24
        cookies = {"flp_session": main.sign("session", owner, BASE + "/session", 3600, email="owner@example.com", csrf=csrf)}
        outsider = {"flp_session": main.sign("session", "other-user", BASE + "/session", 3600, email="other@example.com", csrf=csrf)}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=BASE, follow_redirects=False) as client:
            r = await client.post("/devices/pair", cookies=cookies, headers={"Origin":BASE}, data={"csrf":csrf,"label":"Office computer"})
            assert r.status_code == 200, r.text
            match = re.search(r"--token\s+(flk2_[A-Za-z0-9_-]+)", r.text)
            assert match, "New device pairing must have opaque persistent credential"
            token = match.group(1)
            assert main.device_registry().authenticate(token)["sub"] == owner
            assert main.device_registry().authenticate(token)["label"] == "Office computer"
            assert "expires after 30 days" not in r.text

            d = main.device_registry().list_owned(owner)
            assert len(d) == 1
            device_id = d[0]["id"]
            r = await client.get("/devices", cookies=cookies)
            assert r.status_code == 200 and "Office computer" in r.text
            assert token not in r.text, "Never repeat a device secret in a listing"

            r = await client.post("/devices/revoke",cookies=outsider,headers={"Origin":BASE},
                                  data={"csrf":csrf,"device_id":device_id})
            assert r.status_code in (403,404)
            assert main.device_registry().authenticate(token) is not None

            r = await client.post("/devices/revoke",cookies=cookies,headers={"Origin":BASE},
                                  data={"csrf":"bad","device_id":device_id})
            assert r.status_code == 403
            assert main.device_registry().authenticate(token) is not None

            r = await client.post("/devices/revoke",cookies=cookies,headers={"Origin":BASE},
                                  data={"csrf":csrf,"device_id":device_id})
            assert r.status_code in (200,303)
            assert main.device_registry().authenticate(token) is None

            r = await client.post("/devices/revoke-current",headers={"Authorization":"Bearer " + token})
            assert r.status_code == 401

            new_pair = await client.post("/devices/pair",cookies=cookies,headers={"Origin":BASE},
                                         data={"csrf":csrf, "label":"Travel laptop"})
            other_token = re.search(r"--token\s+(flk2_[A-Za-z0-9_-]+)",new_pair.text).group(1)
            r = await client.post("/devices/revoke-current", headers={"Authorization":"Bearer "+other_token})
            assert r.status_code == 204
            assert main.device_registry().authenticate(other_token) is None

            r = await client.post("/devices/revoke-current", headers={"Authorization":"Bearer "+other_token})
            assert r.status_code == 401

    os.environ.pop("FLICKER_DB_PATH",None)
    print("PASS: account-owned pairings persist, browser revoke and device logout revoke server-side")

if __name__ == "__main__":
    asyncio.run(run())
