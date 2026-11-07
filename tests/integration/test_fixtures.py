"""Tests of the fixtures of the integration tests."""

from typing import Any

from flask.testing import FlaskClient
import mongomock
from pymongo import MongoClient

from pubgrade.settings import collection
from tests.integration.conftest import MONGODB_TEST_URI


def test_response_validation(api: FlaskClient) -> None:
    """The app is configured to validate its responses against the API."""
    flask_config: Any = api.application.config
    spec = flask_config.foca.api.specs[0]
    assert spec.connexion.validate_responses is True


def test_database(api: FlaskClient) -> None:
    """The app uses MongoDB at `MONGODB_TEST_URI` if it is set, else mongomock."""
    with api.application.app_context():
        client = collection("repositories").database.client
    if MONGODB_TEST_URI:
        assert isinstance(client, MongoClient)
    else:
        assert isinstance(client, mongomock.MongoClient)
