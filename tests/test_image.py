"""Tests for the image build (`Dockerfile`) and its requirements."""

import json
from pathlib import Path
import re

from foca import gunicorn_config

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
    assert "python:foca.gunicorn_config" in args
    assert args[-1] == "pubgrade.app:create_app()"
    assert gunicorn_config.bind == ["0.0.0.0:8080"]
