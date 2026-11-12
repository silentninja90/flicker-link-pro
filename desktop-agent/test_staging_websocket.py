"""Staging-only transport probe: invalid device credential must be rejected."""
import asyncio
import inspect
import websockets

ENDPOINT = "wss://flicker-link-pro-2-staging.onrender.com/ws/device"

async def run():
    header_arg = ("additional_headers" if "additional_headers" in
                  inspect.signature(websockets.connect).parameters
                  else "extra_headers")
    try:
        async with websockets.connect(
            ENDPOINT,
            open_timeout=40,
            proxy=None,
            **{header_arg: {"Authorization": "Bearer flk2_staging_probe_invalid"}},
        ):
            raise AssertionError("Invalid staging credential was accepted")
    except (websockets.exceptions.InvalidStatus,
            websockets.exceptions.InvalidStatusCode) as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(exc, "status_code", None)
        assert status in (401, 403), f"Unexpected WebSocket rejection: {status}"
        print("PASS: Staging WebSocket reachable, invalid pairing correctly denied")

if __name__ == "__main__":
    asyncio.run(run())
