"""Persistent, revocable device credentials.

Requires a durable SQLite database file on a mounted persistent volume in production.
Do not set FLICKER_DB_PATH to the ephemeral Render deployment filesystem.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid


class DeviceRegistry:
    """Store a high-entropy bearer credential's keyed digest, never the credential."""

    def __init__(self, path: str, secret: str):
        if not path or not Path(path).is_absolute():
            raise ValueError("The device registry requires an absolute, persistent database path")
        if len(secret) < 24:
            raise ValueError("The device registry requires a strong server secret")
        self.path = str(Path(path))
        self.secret = secret.encode("utf-8")
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS device_credentials (
                id TEXT PRIMARY KEY,
                owner_sub TEXT NOT NULL,
                label TEXT NOT NULL,
                key_digest TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER,
                revoked_at INTEGER
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS devices_by_owner ON device_credentials(owner_sub)")
        if os.name != "nt":
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 10000")
            with conn:
                yield conn
        finally:
            conn.close()

    def _digest(self, token: str) -> str:
        return hmac.new(self.secret, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def issue(self, owner_sub: str, label: str = "Windows computer") -> dict:
        if not owner_sub or len(owner_sub) > 300:
            raise ValueError("Invalid user identity")
        name = (str(label).strip() or "Windows computer")[:80]
        token = "flk2_" + secrets.token_urlsafe(48)
        identity = uuid.uuid4().hex
        now = int(time.time())
        with self._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM device_credentials WHERE owner_sub=? AND revoked_at IS NULL",
                (owner_sub,)).fetchone()[0]
            if count >= 10:
                raise ValueError("Device limit reached. Revoke a device before pairing another.")
            connection.execute(
                """INSERT INTO device_credentials
                   (id, owner_sub, label, key_digest, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (identity, owner_sub, name, self._digest(token), now))
        return {"id": identity, "token": token, "label": name}

    def authenticate(self, token: str) -> dict | None:
        if not isinstance(token, str) or not token.startswith("flk2_") or len(token) > 150:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id, owner_sub, label FROM device_credentials
                   WHERE key_digest=? AND revoked_at IS NULL""",
                (self._digest(token),)).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "sub": row["owner_sub"], "label": row["label"]}

    def is_active(self, device_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM device_credentials WHERE id=? AND revoked_at IS NULL",
                (device_id,)).fetchone()
        return row is not None

    def touch(self, device_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE device_credentials SET last_seen_at=? WHERE id=? AND revoked_at IS NULL",
                (int(time.time()), device_id))

    def list_owned(self, owner_sub: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, label, created_at, last_seen_at, revoked_at
                   FROM device_credentials WHERE owner_sub=?
                   ORDER BY created_at DESC""",
                (owner_sub,)).fetchall()
        return [dict(row) for row in rows]

    def revoke_owned(self, owner_sub: str, device_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE device_credentials SET revoked_at=?
                   WHERE owner_sub=? AND id=? AND revoked_at IS NULL""",
                (int(time.time()), owner_sub, device_id))
            return cursor.rowcount == 1

    def revoke_credential(self, token: str) -> bool:
        if not isinstance(token, str) or not token.startswith("flk2_"):
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE device_credentials SET revoked_at=?
                   WHERE key_digest=? AND revoked_at IS NULL""",
                (int(time.time()), self._digest(token)))
            return cursor.rowcount == 1
