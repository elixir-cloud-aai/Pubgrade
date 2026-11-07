"""Fixtures of the integration tests.

The tests run the app as deployed (`create_app()`, with response validation)
against an in-memory database (mongomock), or, if the environment variable
`MONGODB_TEST_URI` is set, against the MongoDB at that URI. That MongoDB must
not have a database `pubgradeStore`: the tests drop it before each test and at
the end.
"""

from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from typing import Any

from flask.testing import FlaskClient
from foca.database import register_mongodb
import mongomock
from pymongo import MongoClient
import pytest
import yaml

import pubgrade.app
from pubgrade.app import CONFIG_FILE, DB, create_app

MONGODB_TEST_URI = os.environ.get("MONGODB_TEST_URI", "")

# Admin user of the configuration, who verifies users
ADMIN = {"name": "Admin", "uid": "admin", "user_access_token": "admin-token"}


@pytest.fixture(scope="session")
def mongodb() -> Iterator[MongoClient[dict[str, Any]] | None]:
    """Get a client of the MongoDB at `MONGODB_TEST_URI`, if it is set.

    Yields:
        The client, or `None` to use mongomock.
    """
    if not MONGODB_TEST_URI:
        yield None
        return
    client: MongoClient[dict[str, Any]] = MongoClient(
        MONGODB_TEST_URI, serverSelectionTimeoutMS=5000
    )
    if DB in client.list_database_names():
        client.close()
        pytest.fail(
            f"MongoDB at MONGODB_TEST_URI has a database '{DB}', which the tests"
            " would drop; use a MongoDB without it."
        )
    yield client
    client.drop_database(DB)
    client.close()


@pytest.fixture
def api(
    mongodb: MongoClient[dict[str, Any]] | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> FlaskClient:
    """Create the app with an empty database, and get a client of its API.

    The configuration is the app's own, with an admin user (`ADMIN`) and a
    shorter notification timeout.

    Args:
        mongodb: Client of the MongoDB to use, or `None` for mongomock.
        tmp_path: Temporary directory for the configuration.
        monkeypatch: Pytest's monkeypatch fixture.

    Returns:
        Test client of the app.
    """
    config = yaml.safe_load(CONFIG_FILE.read_text())
    spec = config["api"]["specs"]["pubgrade"]
    spec["path"] = str(CONFIG_FILE.parent / spec["path"])
    subscriptions = config["endpoints"]["subscriptions"]
    subscriptions["admin_users"] = [ADMIN]
    subscriptions["notification_timeout"] = 5
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(pubgrade.app, "CONFIG_FILE", config_file)
    if mongodb is None:
        monkeypatch.setattr(
            register_mongodb,
            "MongoClient",
            lambda *args, **kwargs: mongomock.MongoClient(),
        )
    else:
        monkeypatch.setenv("MONGO_URI", MONGODB_TEST_URI)
        mongodb.drop_database(DB)
    return create_app().app.test_client()


class Subscriber:
    """A deployment that receives notifications, on a local port.

    Answers each notification with `status` and records it in `received`.
    """

    def __init__(self) -> None:
        """Start the server in a thread."""
        self.status = 200
        self.received: list[dict[str, Any]] = []
        subscriber = self

        class Handler(BaseHTTPRequestHandler):
            """Records notifications."""

            def do_PUT(self) -> None:
                """Record a notification and answer it."""
                length = int(self.headers["Content-Length"])
                subscriber.received.append(
                    {
                        "path": self.path,
                        "token": self.headers["X-Access-Token"],
                        "body": json.loads(self.rfile.read(length)),
                    }
                )
                self.send_response(subscriber.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                """Don't log requests.

                Args:
                    format: Format of the message.
                    *args: Values of the message.
                """

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/update"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop the server."""
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def subscriber(monkeypatch: pytest.MonkeyPatch) -> Iterator[Subscriber]:
    """Run a subscriber that receives notifications.

    Requests to it bypass proxies from the environment.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.

    Yields:
        The subscriber.
    """
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    server = Subscriber()
    yield server
    server.stop()
