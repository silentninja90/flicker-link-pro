"""Security regression for safe Google token diagnostics and callback URL logs."""
import logging
from unittest.mock import Mock, patch
import main


def test():
    response = Mock(status_code=401)
    response.json.return_value = {"error": "invalid_client", "error_description": "client_secret=DO_NOT_LOG_ME"}
    assert main.google_token_error_category(response) == "invalid_client"
    response.json.return_value = {"error": "invalid_grant", "error_description": "code=DO_NOT_LOG_ME"}
    assert main.google_token_error_category(response) == "invalid_grant"
    response.json.return_value = {"error": "DO_NOT_LOG_ME"}
    assert main.google_token_error_category(response) == "unknown"
    response.json.side_effect = ValueError("token=DO_NOT_LOG_ME")
    assert main.google_token_error_category(response) == "unknown"

    request = "/auth/google/callback?state=DO_NOT_LOG_ME&code=DO_NOT_LOG_ME"
    log = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("192.0.2.1", "GET", request, "1.1", 400), None)
    result = main.GoogleCallbackAccessLogFilter().filter(log)
    assert result
    rendered = log.getMessage()
    assert "DO_NOT_LOG_ME" not in rendered and "/auth/google/callback" in rendered

    other = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("192.0.2.1", "GET", "/healthz", "1.1", 200), None)
    main.GoogleCallbackAccessLogFilter().filter(other)
    assert "/healthz" in other.getMessage()
    print("PASS: Google error category allowlisted, callback authorization code redacted from logs")


if __name__ == "__main__":
    test()
