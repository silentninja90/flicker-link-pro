"""Unit checks for first-launch versus returning-user pairing."""
from unittest import mock
import flicker_relay_agent as agent

def run():
    url = "https://flicker-link-pro.onrender.com"
    with mock.patch.object(agent, "load_credential", return_value=(url, "cached-dummy")):
        with mock.patch.object(agent, "save_credential") as save:
            with mock.patch.object(agent, "prompt_pairing", side_effect=AssertionError("must not prompt")):
                assert agent.resolve_pairing(None, None) == (url, "cached-dummy")
                assert agent.resolve_pairing(url, None) == (url, "cached-dummy")
                save.assert_not_called()
    with mock.patch.object(agent, "load_credential", return_value=(url, "cached-dummy")):
        with mock.patch.object(agent, "save_credential") as save:
            assert agent.resolve_pairing(url, "replacement-dummy") == (url, "replacement-dummy")
            save.assert_called_once_with(url, "replacement-dummy")
    with mock.patch.object(agent, "load_credential", return_value=None):
        with mock.patch.object(agent, "prompt_pairing", return_value=(url, "first-dummy")) as prompt:
            with mock.patch.object(agent, "save_credential") as save:
                assert agent.resolve_pairing(None, None) == (url, "first-dummy")
                prompt.assert_called_once()
                save.assert_called_once_with(url, "first-dummy")
    print("PASS: returning user skips login, new pairing saved, explicit replacement supported")

if __name__ == "__main__":
    run()
