"""PostgreSQL-backed, revocable Flicker Link Pro device pairings.

Designed for a Neon pooled DATABASE_URL, with verified TLS and parameterized
queries. Only HMAC digests of high-entropy device credentials are persisted.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit
import uuid

import certifi
import psycopg2


class PostgresDeviceRegistry:
    def __init__(self, dsn: str, secret: str):
        parsed = urlsplit(dsn)
        if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname:
            raise ValueError("DATABASE_URL must be a PostgreSQL connection URL")
        if len(secret) < 24:
            raise ValueError("A strong server secret is required")
        self.dsn = dsn
        self.secret = secret.encode("utf-8")
        with closing(self._connect()) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""CREATE TABLE IF NOT EXISTS device_credentials (
                        id TEXT PRIMARY KEY,
                        owner_sub TEXT NOT NULL,
                        label TEXT NOT NULL,
                        key_digest TEXT NOT NULL UNIQUE,
                        created_at BIGINT NOT NULL,
                        last_seen_at BIGINT,
                        revoked_at BIGINT
                    )""")
                    cur.execute("""CREATE INDEX IF NOT EXISTS devices_by_owner
                                   ON device_credentials(owner_sub)""")

    def _connect(self):
        return psycopg2.connect(
            self.dsn,
            sslmode="verify-full",
            sslrootcert=certifi.where(),
            connect_timeout=10,
            application_name="flicker-link-pro",
        )

    def _digest(self, token: str) -> str:
        return hmac.new(self.secret, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def issue(self, owner_sub: str, label: str = "Windows computer") -> dict:
        if not owner_sub or len(owner_sub) > 300:
            raise ValueError("Invalid user identity")
        name = (str(label).strip() or "Windows computer")[:80]
        token = "flk2_" + secrets.token_urlsafe(48)
        device_id = uuid.uuid4().hex
        now = int(time.time())
        with closing(self._connect()) as conn:
            with conn:
                with conn.cursor() as cur:
                    # Serializes concurrent pairings for the same Google subject.
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (owner_sub,))
                    cur.execute("""SELECT COUNT(*) FROM device_credentials
                                   WHERE owner_sub=%s AND revoked_at IS NULL""", (owner_sub,))
                    if cur.fetchone()[0] >= 10:
                        raise ValueError("Device limit reached. Revoke a device before pairing another.")
                    cur.execute("""INSERT INTO device_credentials
                                   (id, owner_sub, label, key_digest, created_at)
                                   VALUES (%s, %s, %s, %s, %s)""",
                                (device_id, owner_sub, name, self._digest(token), now))
        return {"id": device_id, "token": token, "label": name}

    def authenticate(self, token: str) -> dict | None:
        if not isinstance(token, str) or not token.startswith("flk2_") or len(token) > 150:
            return None
        with closing(self._connect()) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT id, owner_sub, label FROM device_credentials
                                   WHERE key_digest=%s AND revoked_at IS NULL""",
                                (self._digest(token),))
                    row = cur.fetchone()
        return {"id": row[0], "sub": row[1], "label": row[2]} if row else None

    def is_active(self, device_id: str) -> bool:
        with closing(self._connect()) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT id FROM device_credentials
                                   WHERE id=%s AND revoked_at IS NULL""", (device_id,))
                    return cur.fetchone() is not None

    def touch(self, device_id: str) -> None:
        with closing(self._connect()) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""UPDATE device_credentials SET last_seen_at=%s
                                   WHERE id=%s AND revoked_at IS NULL""",
                                (int(time.time()), device_id))

    def list_owned(self, owner_sub: str) -> list[dict]:
        with closing(self._connect()) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT id, label, created_at, last_seen_at, revoked_at
                                   FROM device_credentials WHERE owner_sub=%s
                                   ORDER BY created_at DESC""", (owner_sub,))
                    rows = cur.fetchall()
        fields = ("id", "label", "created_at", "last_seen_at", "revoked_at")
        return [dict(zip(fields, row)) for row in rows]

    def revoke_owned(self, owner_sub: str, device_id: str) -> bool:
        with closing(self._connect()) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""UPDATE device_credentials SET revoked_at=%s
                                   WHERE owner_sub=%s AND id=%s AND revoked_at IS NULL""",
                                (int(time.time()), owner_sub, device_id))
                    return cur.rowcount == 1

    def revoke_credential(self, token: str) -> bool:
        if not isinstance(token, str) or not token.startswith("flk2_") or len(token) > 150:
            return False
        with closing(self._connect()) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""UPDATE device_credentials SET revoked_at=%s
                                   WHERE key_digest=%s AND revoked_at IS NULL""",
                                (int(time.time()), self._digest(token)))
                    return cur.rowcount == 1
