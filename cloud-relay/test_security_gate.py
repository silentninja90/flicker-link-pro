"""Security regression checks that must fail before fixing the relay."""
import asyncio
import os
import secrets
import time

os.environ["FLICKER_SECRET"] = "test-only-" + "a" * 48
os.environ["BASE_URL"] = "https://flicker-link-pro.onrender.com"
os.environ["GOOGLE_CLIENT_ID"] = "test-google-client.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "not-a-real-google-secret"

import httpx
import main
from fastapi import HTTPException

async def run():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=main.BASE_URL) as client:
        metadata = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert metadata["grant_types_supported"] == ["authorization_code"], "Refresh tokens must not be offered without secure rotation"
        registration = await client.post("/oauth/register", json={
            "redirect_uris": ["https://chatgpt.com/verify"], "token_endpoint_auth_method": "none"})
        assert registration.status_code == 201
        assert registration.json()["grant_types"] == ["authorization_code"]

        code = main.sign("auth_code", "verified-google-user", main.BASE_URL + "/authcode",
                         90, client_hash="test", redirect_uri="https://chatgpt.com/verify",
                         challenge="test", resource=main.RESOURCE)
        old_key = main.PROCESS_CODE_KEY
        try:
            main.PROCESS_CODE_KEY = secrets.token_urlsafe(48)
            try:
                main.verify(code, "auth_code", main.BASE_URL + "/authcode")
                raise AssertionError("Old authorization code was valid after process-key rotation")
            except HTTPException as exc:
                assert exc.status_code == 401
        finally:
            main.PROCESS_CODE_KEY = old_key

        reg = registration.json()["client_id"]
        bogus_refresh = main.sign("refresh", "user", main.RESOURCE, 3600, client_hash=main.digest(reg))
        exchange = await client.post("/oauth/token", data={
            "grant_type":"refresh_token", "client_id":reg,
            "refresh_token":bogus_refresh, "resource":main.RESOURCE})
        assert exchange.status_code == 400, "Do not accept refresh grant before rotation support"

        saved_codes = main.REDEEMED_CODES.copy()
        try:
            main.REDEEMED_CODES.clear()
            expiry = int(time.time()) + 90
            main.consume_auth_code("first", expiry)
            for n in range(9999):
                main.consume_auth_code(f"fill-{n}", expiry)
            try:
                main.consume_auth_code("overflow", expiry)
                raise AssertionError("Replay cache must fail closed when full")
            except HTTPException as exc:
                assert exc.status_code == 503
            assert "first" in main.REDEEMED_CODES
            try:
                main.consume_auth_code("first", expiry)
                raise AssertionError("Previously used authorization code was reused")
            except HTTPException as exc:
                assert exc.status_code == 400
        finally:
            main.REDEEMED_CODES.clear()
            main.REDEEMED_CODES.update(saved_codes)

    print("PASS: no refresh grant, restart invalidation, bounded fail-closed code replay cache")

if __name__ == "__main__":
    asyncio.run(run())
