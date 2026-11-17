"""Scheduled backup cleanup for revoked device records when the relay is idle."""

import os

from postgres_registry import PostgresDeviceRegistry


if __name__ == "__main__":
    try:
        registry = PostgresDeviceRegistry(os.environ["DATABASE_URL"], os.environ["FLICKER_SECRET"])
        registry.purge_revoked()
    except Exception as exc:
        raise SystemExit(f"Revoked device cleanup failed ({type(exc).__name__})") from None
