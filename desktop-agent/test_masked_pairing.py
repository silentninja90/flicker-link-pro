"""Masking, editing, rejected-token retry, and launcher regressions (staging only)."""
import io
import sys
from unittest import mock

import flicker_relay_agent as agent
import install_staging_shortcut as installer


def masked(keys):
    it = iter(keys)
    output = io.StringIO()
    result = agent.read_masked_pairing("TOKEN: ", read_key=lambda: next(it), output=output)
    return result, output.getvalue()


def test():
    token = "flk2_" + "AbC123-_Z" * 4
    result, output = masked([*token, "\r"])
    assert result == token
    assert output.startswith("TOKEN: ") and output.endswith("\n")
    assert output.count("*") == len(token)
    assert token not in output

    result, output = masked(["a", "b", "\b", "c", "\r"])
    assert result == "ac", result
    assert output == "TOKEN: **\b \b*\n", repr(output)

    result, output = masked(["a", "\xe0", "K", "b", "\x7f", "c", "\n"])
    assert result == "ac"
    assert output.count("*") == 3

    output = io.StringIO()
    with mock.patch.object(agent, "read_masked_pairing",
                           side_effect=["python agent.py --token " + token, token]) as read:
        with mock.patch.object(agent.webbrowser, "open"):
            assert agent.prompt_pairing(agent.STAGING_SERVER) == (agent.STAGING_SERVER, token)
            assert read.call_count == 2

    with mock.patch.object(agent, "resolve_pairing",
                           return_value=(agent.STAGING_SERVER, "old-token")):
        with mock.patch.object(agent, "prompt_pairing",
                               return_value=(agent.STAGING_SERVER, token)) as reprompt:
            with mock.patch.object(agent, "_save_for") as save:
                outcomes = iter([False, KeyboardInterrupt()])
                def fake_asyncio_run(coro):
                    coro.close()
                    outcome = next(outcomes)
                    if isinstance(outcome, BaseException):
                        raise outcome
                    return outcome
                with mock.patch.object(agent.asyncio, "run", side_effect=fake_asyncio_run) as run:
                    with mock.patch.object(sys, "argv", ["agent.py", "--profile", "staging"]):
                        agent.main()
                assert run.call_count == 2
                reprompt.assert_called_once_with(agent.STAGING_SERVER)
                save.assert_called_once_with("staging", agent.STAGING_SERVER, token)

    assert "pause >nul" in installer.START
    assert 'set "FLP_EXIT=%ERRORLEVEL%"' in installer.START
    assert '--profile staging' in installer.START
    assert "--profile staging --logout" in installer.SIGNOUT
    print("PASS: asterisk mask, backspace, paste, format retry, invalid-token retry, visible exit")


if __name__ == "__main__":
    test()
