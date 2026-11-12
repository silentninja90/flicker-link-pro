"""Staging database readiness endpoint should not expose secrets."""
import asyncio
import logging
from unittest.mock import Mock, patch
import httpx
import main

async def run():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app),
        base_url="https://flicker-link-pro-2-staging.onrender.com",
    ) as client:
        fake = Mock()
        fake.list_owned.return_value = []
        with patch.object(main, "device_registry", return_value=fake):
            response = await client.get("/healthz")
            assert response.status_code == 200, response.text
            assert response.json() == {"status": "ok", "database": "ready"}
            fake.list_owned.assert_called_once()
        with patch.object(main, "device_registry", side_effect=Exception("postgresql://user:password@secret-host/db")):
            with patch.object(logging.Logger, "warning") as warning:
                response = await client.get("/healthz")
                assert response.status_code == 503
                assert "password" not in response.text
                assert "secret-host" not in response.text
                warning.assert_called_once()
                logged = str(warning.call_args)
                assert "Exception" in logged
                assert "password" not in logged
                assert "secret-host" not in logged
    print("PASS: staging health endpoint probes DB and redacts failures")

if __name__ == "__main__":
    asyncio.run(run())
