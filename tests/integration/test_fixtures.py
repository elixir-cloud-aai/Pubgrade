"""Tests of the fixtures of the integration tests."""

from flask.testing import FlaskClient
import mongomock
from pymongo import MongoClient

from pubgrade.settings import collection
from tests.integration.conftest import MONGODB_TEST_URI


def test_database(api: FlaskClient) -> None:
    """The app uses MongoDB at `MONGODB_TEST_URI` if it is set, else mongomock."""
    with api.application.app_context():
        client = collection("repositories").database.client
    if MONGODB_TEST_URI:
        assert isinstance(client, MongoClient)
    else:
        assert isinstance(client, mongomock.MongoClient)
