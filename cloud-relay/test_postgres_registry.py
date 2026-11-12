"""TDD: PostgreSQL device registry behavior against a local SQL-compatible fake.

Fake maps parameterized Postgres queries onto SQLite. This tests adapter logic,
not real Neon wire connectivity (requires a connected Neon account).
"""
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from postgres_registry import PostgresDeviceRegistry


class Cursor:
    def __init__(self, connection):
        self.inner = connection.cursor()
        self.rowcount = 0
    def execute(self, statement, params=()):
        if statement.strip().startswith("SELECT pg_advisory_xact_lock"):
            self.inner.execute("SELECT 1")
        else:
            self.inner.execute(statement.replace("%s", "?"), params)
        self.rowcount = self.inner.rowcount
        return self
    def fetchone(self):
        return self.inner.fetchone()
    def fetchall(self):
        return self.inner.fetchall()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.inner.close()


class Connection:
    def __init__(self, path):
        self.inner = sqlite3.connect(path)
    def cursor(self):
        return Cursor(self.inner)
    def commit(self):
        self.inner.commit()
    def rollback(self):
        self.inner.rollback()
    def close(self):
        self.inner.close()
    def __enter__(self):
        self.inner.execute("BEGIN")
        return self
    def __exit__(self, typ, exc, tb):
        self.inner.rollback() if typ else self.inner.commit()


def run():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "postgres-fake.sqlite3")
        dsn = "postgresql://test:fake@ep-sample.neon.tech/testdb?sslmode=disable"
        secret = "test-only-hmac-secret-strong-" + "a" * 32
        seen = []
        def connect(*args, **kwargs):
            seen.append((args, kwargs))
            return Connection(path)

        with patch("postgres_registry.psycopg2.connect", side_effect=connect):
            registry = PostgresDeviceRegistry(dsn, secret)
            assert seen and seen[-1][1]["sslmode"] == "verify-full", "TLS override is mandatory"
            assert seen[-1][1]["sslrootcert"] and seen[-1][1]["connect_timeout"] <= 15
            user = "google-user-1"
            pair = registry.issue(user, "My PC")
            token = pair["token"]
            assert token.startswith("flk2_") and len(token) > 65
            assert registry.authenticate(token)["sub"] == user
            assert registry.authenticate("flk2_fake-not-valid") is None
            assert registry.is_active(pair["id"])
            assert registry.list_owned(user)[0]["label"] == "My PC"
            assert registry.list_owned("other") == []
            registry.touch(pair["id"])
            assert registry.list_owned(user)[0]["last_seen_at"] is not None
            restarted = PostgresDeviceRegistry(dsn, secret)
            assert restarted.authenticate(token)["sub"] == user
            assert token.encode() not in Path(path).read_bytes(), "Never persist raw device token"
            assert not registry.revoke_owned("other", pair["id"])
            assert restarted.revoke_owned(user, pair["id"])
            assert not registry.is_active(pair["id"])
            assert restarted.authenticate(token) is None
            assert not restarted.revoke_owned(user, pair["id"])
            two = registry.issue(user, "Laptop")
            assert restarted.revoke_credential(two["token"])
            assert not registry.is_active(two["id"])
            assert not registry.revoke_credential(two["token"])
            for i in range(10):
                registry.issue("bulk-user", "Device "+str(i))
            try:
                registry.issue("bulk-user", "Eleventh")
                raise AssertionError("Device limit not enforced")
            except ValueError as exc:
                assert "limit" in str(exc).lower()
            assert len(registry.list_owned("bulk-user")) == 10
            assert "token" not in repr(registry.list_owned(user))
    print("PASS: PostgreSQL adapter SQL, TLS verify-full, HMAC, persistence, owner-only revocation, 10-device limit")

if __name__ == "__main__":
    run()
