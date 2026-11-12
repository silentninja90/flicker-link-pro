"""Fail closed on Render when durable disk isn't mounted."""
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["FLICKER_SECRET"] = "only-a-test-secret-" + "x"*48
os.environ["BASE_URL"] = "https://flicker-link-pro.onrender.com"
import httpx
import main

async def run():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["RENDER"] = "true"
        os.environ["FLICKER_DB_PATH"] = str(Path(directory) / "pairings.sqlite3")
        os.environ["FLICKER_DISK_MOUNT"] = "/var/data"
        csrf = "csrf-secret"
        signed = main.sign("session", "google-sub", main.BASE_URL + "/session", 3600, csrf=csrf, email="x@example.test")
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url=main.BASE_URL) as client:
                with patch.object(main.os.path, "ismount", return_value=False):
                    response = await client.post("/devices/pair",cookies={"flp_session": signed},
                        headers={"Origin":main.BASE_URL},data={"csrf":csrf})
                    assert response.status_code == 503, "Cannot persist device pairings on an unmounted Render disk"
        finally:
            os.environ.pop("RENDER",None)
            os.environ.pop("FLICKER_DISK_MOUNT",None)
            os.environ.pop("FLICKER_DB_PATH",None)
    print("PASS: no device pairing when Render disk isn't mounted")

if __name__ == "__main__":
    asyncio.run(run())
