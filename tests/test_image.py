"""Tests for the image build (`Dockerfile`) and its requirements."""

import json
from pathlib import Path
import re
import sys

from foca import gunicorn_config
from gunicorn.app.wsgiapp import WSGIApplication
import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE = re.compile(
    r"^FROM elixircloud/foca:(?P<version>[^-\s@]+)-py(?P<python>[0-9.]+)@sha256:",
    re.MULTILINE,
)


def _dockerfile() -> str:
    """Read the `Dockerfile`.

    Returns:
        Its content.
    """
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_base_image_has_required_foca() -> None:
    """The base image has the FOCA release of `requirements.txt`.

    Otherwise the image build would install another FOCA on top of it.
    """
    match = BASE_IMAGE.search(_dockerfile())
    assert match is not None, "No FOCA base image pinned by digest"
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert f"foca=={match['version']}" in requirements.splitlines()


def test_image_serves_app_with_gunicorn() -> None:
    """The image serves the app factory with FOCA's Gunicorn settings."""
    command = re.search(
        r"^CMD (\[.*?\])$", _dockerfile().replace("\\\n", ""), re.M | re.S
    )
    assert command is not None, "No CMD in exec form"
    args = json.loads(command[1])
    assert args[0] == "gunicorn"
    assert "python:pubgrade.gunicorn_config" in args
    assert args[-1] == "pubgrade.app:create_app()"
    assert gunicorn_config.bind == ["0.0.0.0:8080"]


def test_image_runs_as_unprivileged_user() -> None:
    """The image runs as the FOCA image's user, not as root."""
    users = re.findall(r"^USER (\S+)$", _dockerfile(), re.MULTILINE)
    assert users[-1] == "1000"


def test_image_serves_with_more_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Long requests (publishes, slow clients) don't take all threads.

    Settings are loaded as the image's command does, without the app; they
    leave `GUNICORN_CMD_ARGS` to deployments.

    Args:
        monkeypatch: Fixture to set the command line.
    """
    assert "ENV GUNICORN_CMD_ARGS" not in _dockerfile()
    command = re.search(
        r"^CMD (\[.*?\])$", _dockerfile().replace("\\\n", ""), re.M | re.S
    )
    assert command is not None, "No CMD in exec form"
    monkeypatch.delenv("GUNICORN_CMD_ARGS", raising=False)
    monkeypatch.setattr(sys, "argv", json.loads(command[1]))
    settings = WSGIApplication().cfg
    assert settings.threads == 16
    assert settings.workers == gunicorn_config.workers
    assert settings.bind == gunicorn_config.bind
    # Running requests finish within Kubernetes' default grace period
    assert gunicorn_config.graceful_timeout < settings.graceful_timeout < 30
