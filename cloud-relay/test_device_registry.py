"""Red/green tests: durable, revocable device pairings for Flicker Link Pro."""
import json
import sqlite3
import tempfile
from pathlib import Path

from device_registry import DeviceRegistry

def run():
    with tempfile.TemporaryDirectory() as temp:
        db = str(Path(temp) / "pairings.sqlite3")
        one = DeviceRegistry(db, "test-only-secret-key-longer-than-32")
        owner = "google-sub-123"
        created = one.issue(owner, "Laptop A")
        token = created["token"]
        assert token.startswith("flk2_")
        assert created["id"] and len(token) > 60
        assert one.authenticate(token)["sub"] == owner
        assert one.authenticate("flk2_not_a_valid_credential") is None
        assert one.list_owned(owner)[0]["id"] == created["id"]
        assert one.list_owned("different-user") == []

        # Simulates a full server restart. Credentials survive across processes.
        two = DeviceRegistry(db, "test-only-secret-key-longer-than-32")
        assert two.authenticate(token)["sub"] == owner
        raw_db = Path(db).read_bytes()
        assert token.encode() not in raw_db, "Plaintext device secret must never be on disk"

        # Other users cannot revoke someone else's device.
        assert two.revoke_owned("different-user", created["id"]) is False
        assert two.authenticate(token) is not None

        # User may revoke remotely, which invalidates this device immediately.
        assert two.revoke_owned(owner, created["id"]) is True
        assert one.authenticate(token) is None
        assert two.revoke_owned(owner, created["id"]) is False

        second = one.issue(owner, "Laptop B")
        assert one.revoke_credential(second["token"]) is True
        assert one.authenticate(second["token"]) is None
        assert one.revoke_credential(second["token"]) is False
        assert "token" not in str(one.list_owned(owner))
    print("PASS: durable pairings, ownership, no plaintext secrets, immediate remote/local revocation")

if __name__ == "__main__":
    run()
