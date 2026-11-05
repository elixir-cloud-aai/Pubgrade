"""Tests for the default configuration, which ends up in the public image."""

from pathlib import Path
from typing import Any, Dict

import pytest
import yaml


@pytest.fixture(name="config")
def fixture_config() -> Dict[str, Any]:
    """Load the default configuration.

    Returns:
        The content of `pubgrade/config.yaml`.
    """
    path = Path(__file__).parent.parent / "pubgrade" / "config.yaml"
    return yaml.safe_load(path.read_text())


def test_no_debug_mode(config: Dict[str, Any]) -> None:
    """Debug and development settings are off."""
    assert config["server"]["debug"] is False
    assert config["server"]["testing"] is False
    assert config["server"]["use_reloader"] is False
    assert config["server"]["environment"] == "production"


def test_no_users(config: Dict[str, Any]) -> None:
    """Deployments bring their own admin users and tokens."""
    assert config["endpoints"]["subscriptions"]["admin_users"] == []


def test_builds_off(config: Dict[str, Any]) -> None:
    """Builds are off, without settings for particular deployments."""
    builds = config["endpoints"]["builds"]
    assert builds["enabled"] is False
    assert builds["gh_action_path"] == ""
    assert builds["intermediate_registery_format"] == ""
