"""PostgreSQL-backed, revocable Flicker Link Pro device pairings.

Designed for a Neon pooled DATABASE_URL, with verified TLS and parameterized
queries. Only HMAC digests of high-entropy device credentials are persisted.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit
import uuid

import certifi
import psycopg2

USAGE_PERIOD_SECONDS = 30 * 24 * 3600
REVOKED_RETENTION_SECONDS = 30 * 24 * 3600


class PostgresDeviceRegistry:
    def __init__(self, dsn: str, secret: str, *, meter_usage: bool = False):
        parsed = urlsplit(dsn)
        if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname:
            raise ValueError("DATABASE_URL must be a PostgreSQL connection URL")
        if len(secret) < 24:
            raise ValueError("A strong server secret is required")
        self.dsn = dsn
        self.secret = secret.encode("utf-8")
        self.meter_usage = meter_usage
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
                    cur.execute("""CREATE INDEX IF NOT EXISTS revoked_devices_by_date
                                   ON device_credentials(revoked_at)
                                   WHERE revoked_at IS NOT NULL""")
                    if not self.meter_usage:
                        return
                    cur.execute("""CREATE TABLE IF NOT EXISTS account_usage (
                        owner_sub TEXT PRIMARY KEY,
                        first_connected_at BIGINT NOT NULL,
                        window_number BIGINT NOT NULL DEFAULT 0,
                        calls INTEGER NOT NULL DEFAULT 0
                    )""")
                    cur.execute("""CREATE TABLE IF NOT EXISTS stripe_billing (
                        owner_sub TEXT PRIMARY KEY REFERENCES account_usage(owner_sub) ON DELETE CASCADE,
                        customer_id TEXT NOT NULL UNIQUE,
                        paid_through BIGINT
                    )""")

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
                    if cur.fetchone()[0] >= 1:
                        raise ValueError("One-computer limit reached. Remove the currently paired computer before pairing a replacement.")
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
                    now = int(time.time())
                    cur.execute("""UPDATE device_credentials SET last_seen_at=%s
                                   WHERE id=%s AND revoked_at IS NULL
                                   RETURNING owner_sub""", (now, device_id))
                    owner = cur.fetchone()
                    if owner and self.meter_usage:
                        cur.execute("""INSERT INTO account_usage (owner_sub, first_connected_at)
                                       VALUES (%s, %s) ON CONFLICT (owner_sub) DO NOTHING""",
                                    (owner[0], now))

    def usage(self, owner_sub: str, allowance: int, *, consume: bool = False) -> dict | None:
        with closing(self._connect()) as conn, conn, conn.cursor() as cur:
            query = """SELECT u.first_connected_at, u.window_number, u.calls, b.paid_through,
                              b.customer_id IS NOT NULL
                       FROM account_usage AS u LEFT JOIN stripe_billing AS b USING (owner_sub)
                       WHERE u.owner_sub=%s"""
            cur.execute(query + (" FOR UPDATE OF u" if consume else ""), (owner_sub,))
            row = cur.fetchone()
            if row is None:
                return None
            first_connected_at, previous_window, calls, paid_through, has_billing = row
            now = int(time.time())
            window = max(0, (now - first_connected_at) // USAGE_PERIOD_SECONDS)
            if window != previous_window:
                calls = 0
            unlimited = paid_through is not None and paid_through > now
            allowed = unlimited or calls < allowance
            if consume and allowed and not unlimited:
                calls += 1
                cur.execute("""UPDATE account_usage SET window_number=%s, calls=%s
                               WHERE owner_sub=%s""", (window, calls, owner_sub))
            return {
                "allowed": allowed,
                "unlimited": unlimited,
                "used": calls,
                "allowance": allowance,
                "resets_at": first_connected_at + (window + 1) * USAGE_PERIOD_SECONDS,
                "has_billing": has_billing,
            }

    @contextmanager
    def billing_transaction(self):
        with closing(self._connect()) as conn, conn, conn.cursor() as cur:
            yield cur

    def purge_revoked(self) -> None:
        with closing(self._connect()) as conn, conn, conn.cursor() as cur:
            cur.execute("DELETE FROM device_credentials WHERE revoked_at <= %s",
                        (int(time.time()) - REVOKED_RETENTION_SECONDS,))

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

    def rename_owned(self, owner_sub: str, device_id: str, label: str) -> bool:
        with closing(self._connect()) as conn, conn, conn.cursor() as cur:
            cur.execute("""UPDATE device_credentials SET label=%s
                           WHERE owner_sub=%s AND id=%s AND revoked_at IS NULL""",
                        (label, owner_sub, device_id))
            return cur.rowcount == 1

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
