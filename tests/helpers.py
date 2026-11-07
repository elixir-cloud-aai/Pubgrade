"""Helpers shared by the tests."""

from typing import Any

from flask import Flask
from foca.models.config import Config, MongoConfig

from tests.mock_data import MONGO_CONFIG


class FocaApp(Flask):
    """Flask app whose configuration holds the FOCA configuration."""

    config: Any


def make_config(endpoints: dict[str, Any]) -> Config:
    """Create a FOCA configuration with the mock database.

    Args:
        endpoints: Configuration of the endpoints.

    Returns:
        The FOCA configuration.
    """
    extra: dict[str, Any] = {"endpoints": endpoints}
    return Config(db=MongoConfig(**MONGO_CONFIG), **extra)


def set_foca(app: Flask, **settings: Any) -> None:
    """Set the FOCA configuration of an app.

    Args:
        app: Flask app.
        **settings: Settings of the configuration.
    """
    flask_config: Any = app.config
    flask_config.foca = Config(**settings)


def foca_config(app: Flask) -> Any:
    """Get the FOCA configuration of an app.

    Args:
        app: Flask app.

    Returns:
        The configuration, with the collections of the database.
    """
    flask_config: Any = app.config
    return flask_config.foca


def unwrap(controller: Any) -> Any:
    """Get a controller without its decorators.

    Args:
        controller: Decorated controller.

    Returns:
        The controller as defined, without authentication and the like.
    """
    return controller.__wrapped__
