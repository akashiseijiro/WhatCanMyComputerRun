"""On GitHub Actions, report each failed test as an annotation.

Annotations are visible without signing in (job logs are not), which makes CI failures on
Windows easy to diagnose from outside the repo.
"""

import os

import pytest


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape(text).replace(":", "%3A").replace(",", "%2C")


def pytest_runtest_logreport(report):  # type: ignore[no-untyped-def]
    if os.environ.get("GITHUB_ACTIONS") != "true" or not report.failed:
        return
    crash = getattr(getattr(report.longrepr, "reprcrash", None), "message", None)
    message = crash or str(report.longrepr)[-600:]
    print(f"\n::error title={_escape_property(report.nodeid)}::{_escape(message[:900])}")


@pytest.fixture(autouse=True)
def _no_real_api_keys(monkeypatch):  # type: ignore[no-untyped-def]
    """Env vars beat .env files, so a developer's real keys never reach the tests."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("WHATCANMYCOMPUTERRUN_LLM_PROVIDER", raising=False)
