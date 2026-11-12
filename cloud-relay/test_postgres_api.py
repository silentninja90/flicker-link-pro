"""API regression: Render Free chooses durable external Postgres when DATABASE_URL exists."""
import asyncio
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["FLICKER_SECRET"] = "dev-only-test-secret-" + "A"*40
os.environ["BASE_URL"] = "https://flicker-link-pro.onrender.com"

import httpx
import main
from postgres_registry import PostgresDeviceRegistry
from test_postgres_registry import Connection

async def run():
    with tempfile.TemporaryDirectory() as tmp:
        file = str(Path(tmp) / "fake-postgres.sqlite3")
        dsn = "postgresql://test:fake@ep-test.neon.tech/testdb?sslmode=require"
        os.environ["RENDER"] = "true"
        os.environ["DATABASE_URL"] = dsn
        os.environ.pop("FLICKER_DB_PATH", None)
        account = "verified-google-user"
        csrf = "csrf-" + "k"*32
        session_token = main.sign("session",account,main.BASE_URL+"/session",3600,email="test@example.test",csrf=csrf)
        cookies = {"flp_session":session_token}
        def fake_connect(*args,**kwargs):
            assert kwargs["sslmode"] == "verify-full"
            return Connection(file)

        try:
            with patch("postgres_registry.psycopg2.connect",side_effect=fake_connect):
                assert isinstance(main.device_registry(), PostgresDeviceRegistry)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                              base_url=main.BASE_URL,follow_redirects=False) as client:
                    x = await client.post("/devices/pair",headers={"Origin":main.BASE_URL},
                                          cookies=cookies,data={"csrf":csrf,"label":"Home PC"})
                    assert x.status_code == 200, (x.status_code,x.text[:300])
                    token = re.search(r"--token\s+(flk2_[A-Za-z0-9_-]+)",x.text).group(1)
                    assert main.device_registry().authenticate(token)["sub"] == account
                    assert main.device_registry().authenticate(token)["label"] == "Home PC"
                    x = await client.get("/devices",cookies=cookies)
                    assert x.status_code == 200 and "Home PC" in x.text
                    assert token not in x.text
                    x = await client.post("/devices/revoke-current",headers={"Authorization":"Bearer "+token})
                    assert x.status_code == 204
                    assert main.device_registry().authenticate(token) is None
        finally:
            os.environ.pop("RENDER",None)
            os.environ.pop("DATABASE_URL",None)
            main._postgres_registry_cached.cache_clear()
    print("PASS: Render Free routes pairing and revocation through external Postgres")

if __name__ == "__main__":
    asyncio.run(run())
