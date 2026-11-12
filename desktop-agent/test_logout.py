"""Test logout revokes server credential before deleting Windows Credential Manager data."""
from unittest import mock
from urllib.error import URLError, HTTPError
import flicker_relay_agent as agent

URL = "https://flicker-link-pro.onrender.com"
TOKEN = "flk2_dummy-not-real-for-local-tests"

class Response:
    status = 204
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False

def run():
    saved = (URL, TOKEN)
    with mock.patch.object(agent, "load_credential", return_value=saved):
        with mock.patch.object(agent, "delete_credential") as remove:
            with mock.patch.object(agent, "urlopen", return_value=Response()) as request:
                assert agent.logout_pairing() is True
                assert request.call_args.kwargs["timeout"] <= 20
                sent = request.call_args.args[0]
                assert sent.full_url == URL + "/devices/revoke-current"
                assert sent.get_method() == "POST"
                assert sent.get_header("Authorization") == "Bearer " + TOKEN
                remove.assert_called_once()

    with mock.patch.object(agent, "load_credential", return_value=saved):
        with mock.patch.object(agent, "delete_credential") as remove:
            with mock.patch.object(agent, "urlopen", side_effect=URLError("offline")):
                assert agent.logout_pairing() is False
                remove.assert_not_called()

    with mock.patch.object(agent, "load_credential", return_value=saved):
        with mock.patch.object(agent, "delete_credential") as remove:
            with mock.patch.object(agent, "urlopen", side_effect=HTTPError(URL,401,"revoked",None,None)):
                assert agent.logout_pairing() is True
                remove.assert_called_once()
    print("PASS: logout revokes remotely before local removal; offline failure preserves credential")

if __name__ == "__main__":
    run()
