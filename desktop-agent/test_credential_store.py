"""Tests that Windows Credential Manager remembers paired laptop credentials securely."""
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from credential_store import save_credential, load_credential, delete_credential

def run():
    target = "FlickerLinkPro2-Test-" + uuid.uuid4().hex
    assert load_credential(target) is None
    try:
        save_credential("https://flicker-link-pro.onrender.com", "dummy-test-token-not-a-real-secret", target)
        assert load_credential(target) == ("https://flicker-link-pro.onrender.com", "dummy-test-token-not-a-real-secret")
    finally:
        delete_credential(target)
    assert load_credential(target) is None
    print("PASS: Windows Credential Manager saved, reloaded, and removed a dummy pairing credential")

if __name__ == "__main__":
    run()
