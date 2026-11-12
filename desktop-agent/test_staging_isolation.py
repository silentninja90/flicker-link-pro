"""Staging pairing must not access or modify the default Windows credential target."""
from unittest import mock
from urllib.error import URLError
import flicker_relay_agent as agent

STAGE = "https://flicker-link-pro-2-staging.onrender.com"

class NoContent:
    status = 204
    def __enter__(self): return self
    def __exit__(self, *args): return False


def test():
    # A saved ngrok/main credential must never be reused for staging.
    def load_separate(*args, **kwargs):
        if "target" not in kwargs:
            return ("https://ngrok.example.test", "legacy-secret")
        assert kwargs["target"] == agent.STAGING_CREDENTIAL_TARGET
        return None

    with mock.patch.object(agent, "load_credential", side_effect=load_separate) as load:
        with mock.patch.object(agent, "prompt_pairing", return_value=(STAGE,"stage-pairing-secret")) as prompt:
            with mock.patch.object(agent, "save_credential") as save:
                result = agent.resolve_pairing(None,None,profile="staging")
                assert result == (STAGE,"stage-pairing-secret")
                prompt.assert_called_once_with(STAGE)
                save.assert_called_once_with(STAGE,"stage-pairing-secret",
                                             target=agent.STAGING_CREDENTIAL_TARGET)
                assert all("target" in c.kwargs for c in load.call_args_list)

    with mock.patch.object(agent, "load_credential", return_value=(STAGE,"cached-staging")) as load:
        with mock.patch.object(agent, "prompt_pairing", side_effect=AssertionError("unexpected prompt")):
            with mock.patch.object(agent, "save_credential") as save:
                assert agent.resolve_pairing(None,None,profile="staging") == (STAGE,"cached-staging")
                load.assert_called_once_with(target=agent.STAGING_CREDENTIAL_TARGET)
                save.assert_not_called()

    with mock.patch.object(agent, "load_credential", return_value=("https://ngrok.example.test","legacy")) as load:
        with mock.patch.object(agent, "save_credential") as save:
            assert agent.resolve_pairing(None,None) == ("https://ngrok.example.test","legacy")
            load.assert_called_once_with()
            save.assert_not_called()

    # Explicit staging server must also select the isolated vault automatically.
    with mock.patch.object(agent, "load_credential", return_value=(STAGE,"cached")) as load:
        assert agent.resolve_pairing(STAGE,None) == (STAGE,"cached")
        load.assert_called_once_with(target=agent.STAGING_CREDENTIAL_TARGET)

    with mock.patch.object(agent, "load_credential", return_value=(STAGE,"staging-secret")):
        with mock.patch.object(agent, "delete_credential") as remove:
            with mock.patch.object(agent, "urlopen", return_value=NoContent()) as request:
                assert agent.logout_pairing(profile="staging")
                remove.assert_called_once_with(target=agent.STAGING_CREDENTIAL_TARGET)
                assert request.call_args.args[0].full_url == STAGE+"/devices/revoke-current"

    # Failure never deletes either credential.
    with mock.patch.object(agent, "load_credential", return_value=(STAGE,"staging-secret")):
        with mock.patch.object(agent, "delete_credential") as remove:
            with mock.patch.object(agent, "urlopen", side_effect=URLError("offline")):
                assert not agent.logout_pairing(profile="staging")
                remove.assert_not_called()
    print("PASS: staging vault isolated from ngrok/main, cached login, logout and offline failure")


if __name__ == "__main__":
    test()
