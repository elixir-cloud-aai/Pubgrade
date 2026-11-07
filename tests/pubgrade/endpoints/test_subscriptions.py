"""Tests for /subscriptions endpoint"""

import json
import logging
import threading
import time
from unittest.mock import MagicMock, patch

from flask import Flask
from foca.models.config import Config, MongoConfig
import mongomock
from pymongo.errors import DuplicateKeyError
import pytest
import requests
from werkzeug.exceptions import InternalServerError, Unauthorized

from pubgrade.errors.exceptions import (
    BuildNotFound,
    RegistrationDisabled,
    RepositoryNotFound,
    SubscriptionNotFound,
    TooManySubscriptions,
    UserNotFound,
    UserNotVerified,
)
from pubgrade.modules.endpoints.subscriptions import (
    delete_subscription,
    get_subscription_info,
    get_subscriptions,
    notify_all_subscriptions,
    notify_subscriptions,
    register_subscription,
)
from tests.mock_data import (
    ENDPOINT_CONFIG,
    MOCK_BUILD_INFO,
    MOCK_BUILD_INFO_2,
    MOCK_REPOSITORIES,
    MOCK_SUBSCRIPTION_INFO,
    MOCK_USER,
    MOCK_USER_DB,
    MOCK_USER_NOT_VERIFIED,
    MONGO_CONFIG,
    SUBSCRIPTION_PAYLOAD,
)


def mocked_request_api(method, url, data, headers, **kwargs):
    return MagicMock(status_code=200)


def mocked_request_api_timeout_error(method, url, data, headers, **kwargs):
    raise requests.exceptions.Timeout


def mocked_request_api_too_many_redirects(method, url, data, headers, **kwargs):
    raise requests.exceptions.TooManyRedirects


def mocked_request_api_request_exception(method, url, data, headers, **kwargs):
    raise requests.exceptions.RequestException


class TestSubscriptions:
    app = Flask(__name__)

    def setup(self):
        self.app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config.foca.db.dbs["pubgradeStore"].collections[
                "repositories"
            ].client.insert_one(repository)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO_2)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_NOT_VERIFIED)

    def insert_subscription(self):
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client.update_one(
            {"uid": MOCK_USER_DB["uid"]},
            {"$set": {"subscription_list": MOCK_USER_DB["subscription_list"]}},
        )
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)

    def test_register_subscription_logs_no_token(self, caplog):
        """Log messages don't contain the subscription's token."""
        self.setup()
        caplog.set_level(logging.DEBUG)
        with self.app.app_context():
            res = register_subscription(
                MOCK_USER["uid"],
                MOCK_USER["user_access_token"],
                {**SUBSCRIPTION_PAYLOAD, "access_token": "subscription-secret"},
            )
        assert f"Added subscription {res['subscription_id']}." in caplog.messages
        assert "subscription-secret" not in caplog.text

    def test_register_subscription_charset(self, monkeypatch):
        """Identifiers use the characters of the repositories' setting."""
        self.setup()
        monkeypatch.setitem(
            self.app.config.foca.endpoints["repository"], "id_charset", "qz"
        )
        with self.app.app_context():
            res = register_subscription(
                MOCK_USER["uid"],
                MOCK_USER["user_access_token"],
                SUBSCRIPTION_PAYLOAD,
            )
        assert len(res["subscription_id"]) == 6
        assert set(res["subscription_id"]) <= {"q", "z"}

    def test_register_subscription(self):
        self.setup()
        with self.app.app_context():
            res = register_subscription(
                MOCK_USER["uid"],
                MOCK_USER["user_access_token"],
                SUBSCRIPTION_PAYLOAD,
            )
            data = (
                self.app.config.foca.db.dbs["pubgradeStore"]
                .collections["repositories"]
                .client.find_one({"id": SUBSCRIPTION_PAYLOAD["repository_id"]})
            )
            subscription = (
                self.app.config.foca.db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": res["subscription_id"]})
            )
            assert isinstance(res, dict)
            assert res["subscription_id"] in data["subscription_list"]
            assert subscription["state"] == "Inactive"

    def test_register_subscription_closed(self):
        """Registration can be closed by configuration."""
        self.setup()
        self.app.config.foca.endpoints["subscriptions"]["registration_enabled"] = False
        with self.app.app_context():
            with pytest.raises(RegistrationDisabled):
                register_subscription(
                    MOCK_USER["uid"],
                    MOCK_USER["user_access_token"],
                    SUBSCRIPTION_PAYLOAD,
                )

    def test_register_subscription_limit(self):
        """A repository takes no more subscriptions than configured."""
        self.setup()
        self.app.config.foca.endpoints["subscriptions"]["max_per_repository"] = 1
        with self.app.app_context():
            register_subscription(
                MOCK_USER["uid"],
                MOCK_USER["user_access_token"],
                dict(SUBSCRIPTION_PAYLOAD),
            )
            with pytest.raises(TooManySubscriptions):
                register_subscription(
                    MOCK_USER["uid"],
                    MOCK_USER["user_access_token"],
                    dict(SUBSCRIPTION_PAYLOAD),
                )

    def test_register_subscription_duplicate_key_error(self):
        self.setup()
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one = mock_resp
        with self.app.app_context():
            with pytest.raises(InternalServerError):
                register_subscription(
                    MOCK_USER["uid"],
                    MOCK_USER["user_access_token"],
                    SUBSCRIPTION_PAYLOAD,
                )

    def test_register_subscription_repo_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                SUBSCRIPTION_PAYLOAD["repository_id"] = "abcd"
                register_subscription(
                    MOCK_USER["uid"],
                    MOCK_USER["user_access_token"],
                    SUBSCRIPTION_PAYLOAD,
                )

    def test_register_subscription_user_not_verified(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(UserNotVerified):
                register_subscription(
                    MOCK_USER_NOT_VERIFIED["uid"],
                    MOCK_USER_NOT_VERIFIED["user_access_token"],
                    SUBSCRIPTION_PAYLOAD,
                )

    def test_register_subscription_unauthorized(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                register_subscription(
                    MOCK_USER["uid"], "user_access_token", SUBSCRIPTION_PAYLOAD
                )

    def test_register_subscription_user_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                register_subscription(
                    "uid", MOCK_USER["user_access_token"], SUBSCRIPTION_PAYLOAD
                )

    def test_get_subscriptions(self):
        self.app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config.foca.db.dbs["pubgradeStore"].collections[
                "repositories"
            ].client.insert_one(repository)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO_2)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_DB)
        with self.app.app_context():
            res = get_subscriptions(MOCK_USER["uid"], MOCK_USER["user_access_token"])
            assert isinstance(res, list)
            assert res[0]["subscription_id"] == MOCK_USER_DB["subscription_list"][0]

    def test_get_subscriptions_subscription_not_found(self):
        self.setup()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_DB)
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                get_subscriptions(MOCK_USER["uid"], MOCK_USER["user_access_token"])

    def test_get_subscriptions_unauthorized(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                get_subscriptions(MOCK_USER["uid"], "user_access_token")

    def test_get_subscriptions_user_not_found(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                get_subscriptions("uid", MOCK_USER["user_access_token"])

    def test_get_subscriptions_user_not_verified(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(UserNotVerified):
                get_subscriptions(
                    MOCK_USER_NOT_VERIFIED["uid"],
                    MOCK_USER_NOT_VERIFIED["user_access_token"],
                )

    def test_get_subscription_info(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            res = get_subscription_info(
                MOCK_USER["uid"],
                MOCK_USER["user_access_token"],
                MOCK_SUBSCRIPTION_INFO["id"],
            )
            assert isinstance(res, dict)
            assert "access_token" not in res
            assert "id" in res
            assert res["state"] == "Inactive"

    def test_get_subscription_info_old_format(self):
        """Subscriptions written by the previous version get a time zone."""
        self.setup()
        self.insert_subscription()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.update_one(
            {"id": MOCK_SUBSCRIPTION_INFO["id"]},
            {"$set": {"updated_at": "2026-01-02T03:04:05"}},
        )
        with self.app.app_context():
            res = get_subscription_info(
                MOCK_USER["uid"],
                MOCK_USER["user_access_token"],
                MOCK_SUBSCRIPTION_INFO["id"],
            )
        assert res["updated_at"] == "2026-01-02T03:04:05+00:00"

    def test_get_subscription_info_subscription_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                get_subscription_info(
                    MOCK_USER["uid"],
                    MOCK_USER["user_access_token"],
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    def test_get_subscription_info_unauthorized(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                get_subscription_info(
                    MOCK_USER["uid"],
                    "access_token",
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    def test_get_subscription_info_user_not_found(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                get_subscription_info(
                    "uid",
                    MOCK_USER["user_access_token"],
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    def test_get_subscription_info_user_not_verified(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(UserNotVerified):
                get_subscription_info(
                    MOCK_USER_NOT_VERIFIED["uid"],
                    MOCK_USER_NOT_VERIFIED["user_access_token"],
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    def test_delete_subscription(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            delete_subscription(
                MOCK_USER["uid"],
                MOCK_USER["user_access_token"],
                MOCK_SUBSCRIPTION_INFO["id"],
            )

    def test_delete_subscription_subscription_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                delete_subscription(
                    MOCK_USER["uid"], MOCK_USER["user_access_token"], "id"
                )

    def test_delete_subscription_unauthorized(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                delete_subscription(
                    MOCK_USER["uid"],
                    "access_token",
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    def test_delete_subscription_user_not_found(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                delete_subscription(
                    "uid",
                    MOCK_USER["user_access_token"],
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    def test_delete_subscription_user_not_verified(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(UserNotVerified):
                delete_subscription(
                    MOCK_USER_NOT_VERIFIED["uid"],
                    MOCK_USER_NOT_VERIFIED["user_access_token"],
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    @patch("requests.request", mocked_request_api)
    def test_notify_subscriptions(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "elixir-cloud-aai/pubgrade:0.0.1",
                MOCK_BUILD_INFO["id"],
            )
            data = (
                self.app.config.foca.db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": MOCK_SUBSCRIPTION_INFO["id"]})
            )
            assert isinstance(data, dict)
            assert data["state"] == "Active"
            assert data["build_id"] == MOCK_BUILD_INFO["id"]

    @patch("requests.request", mocked_request_api)
    def test_notify_subscriptions_subscription_not_found(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                notify_subscriptions(
                    "id",
                    "elixir-cloud-aai/pubgrade:0.0.1",
                    MOCK_BUILD_INFO["id"],
                )

    @patch("requests.request", mocked_request_api)
    def test_notify_subscriptions_build_not_found(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(BuildNotFound):
                notify_subscriptions(
                    MOCK_SUBSCRIPTION_INFO["id"],
                    "elixir-cloud-aai/pubgrade:0.0.1",
                    "id",
                )

    @patch("requests.request", mocked_request_api_timeout_error)
    def test_notify_subscriptions_timeout(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            result = notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "elixir-cloud-aai/pubgrade:0.0.1",
                MOCK_BUILD_INFO["id"],
            )
            assert result["result"] == "failed"
            assert result["http_status"] is None
            data = (
                self.app.config.foca.db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": MOCK_SUBSCRIPTION_INFO["id"]})
            )
            assert data["state"] == "Inactive"

    @patch("requests.request", mocked_request_api_too_many_redirects)
    def test_notify_subscriptions_too_many_redirects(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            result = notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "elixir-cloud-aai/pubgrade:0.0.1",
                MOCK_BUILD_INFO["id"],
            )
            assert result["result"] == "failed"
            assert result["http_status"] is None
            data = (
                self.app.config.foca.db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": MOCK_SUBSCRIPTION_INFO["id"]})
            )
            assert data["state"] == "Inactive"

    @patch("requests.request", mocked_request_api_request_exception)
    def test_notify_subscriptions_request_exception(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            result = notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "elixir-cloud-aai/pubgrade:0.0.1",
                MOCK_BUILD_INFO["id"],
            )
            assert result["result"] == "failed"
            assert result["http_status"] is None
            data = (
                self.app.config.foca.db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": MOCK_SUBSCRIPTION_INFO["id"]})
            )
            assert data["state"] == "Inactive"

    @patch("requests.request", mocked_request_api)
    def test_notify_subscriptions_value_not_matched(self):
        self.setup()
        MOCK_SUBSCRIPTION_INFO["value"] = "master"
        self.insert_subscription()
        with self.app.app_context():
            notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "elixir-cloud-aai/pubgrade:0.0.1",
                MOCK_BUILD_INFO["id"],
            )
            data = (
                self.app.config.foca.db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": MOCK_SUBSCRIPTION_INFO["id"]})
            )
            assert isinstance(data, dict)
            assert data["state"] == "Inactive"
            assert "build_id" not in data

    @patch("requests.request", mocked_request_api)
    def test_notify_subscriptions_type_not_matched(self):
        self.setup()
        MOCK_SUBSCRIPTION_INFO["type"] = "tag"
        self.insert_subscription()
        with self.app.app_context():
            notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "elixir-cloud-aai/pubgrade:0.0.1",
                MOCK_BUILD_INFO["id"],
            )
            data = (
                self.app.config.foca.db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": MOCK_SUBSCRIPTION_INFO["id"]})
            )
            assert isinstance(data, dict)
            assert data["state"] == "Inactive"
            assert "build_id" not in data

    @patch("requests.request")
    def test_notify_subscriptions_error_status(self, request):
        """A response other than 2xx counts as a failure."""
        request.return_value = MagicMock(status_code=500)
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            result = notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "elixir-cloud-aai/pubgrade:0.0.1",
                MOCK_BUILD_INFO["id"],
            )
        assert result["result"] == "failed"
        assert result["http_status"] == 500

    @patch("requests.request")
    def test_notify_subscriptions_request(self, request):
        """The call has a timeout and follows no redirects."""
        request.return_value = MagicMock(status_code=200)
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "registry.example.org:5000/pubgrade:0.0.1",
                MOCK_BUILD_INFO["id"],
            )
        kwargs = request.call_args[1]
        assert kwargs["timeout"] == 10
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        request.return_value.close.assert_called_once_with()
        assert json.loads(kwargs["data"]) == {
            "image_name": "registry.example.org:5000/pubgrade",
            "tag": "0.0.1",
        }

    def insert_subscriptions(self, *ids):
        """Insert subscriptions that match `MOCK_BUILD_INFO`.

        Args:
            *ids: Identifiers of the subscriptions; each one's callback URL
                ends with its identifier.
        """
        for subscription_id in ids:
            self.app.config.foca.db.dbs["pubgradeStore"].collections[
                "subscriptions"
            ].client.insert_one(
                {
                    **MOCK_SUBSCRIPTION_INFO,
                    "id": subscription_id,
                    "callback_url": f"https://example.org/{subscription_id}",
                }
            )

    def get_stored_notifications(self):
        """Get the results stored on the build.

        Returns:
            The field `notifications` of the build.
        """
        return (
            self.app.config.foca.db.dbs["pubgradeStore"]
            .collections["builds"]
            .client.find_one({"id": MOCK_BUILD_INFO["id"]})["notifications"]
        )

    def test_notify_all_concurrently(self):
        """All calls are in progress at the same time."""
        barrier = threading.Barrier(3, timeout=10)

        def request(*args, **kwargs):
            barrier.wait()
            return MagicMock(status_code=200)

        self.setup()
        self.insert_subscriptions("sub1", "sub2", "sub3")
        with self.app.app_context(), patch("requests.request", request):
            results = notify_all_subscriptions(
                ["sub1", "sub2", "sub3"], "org/image:1", MOCK_BUILD_INFO["id"]
            )
        assert [result["result"] for result in results] == ["delivered"] * 3

    def test_notify_all_does_not_queue_behind_hanging_calls(self):
        """Every subscriber gets its call, however many others hang."""
        count = 40
        ids = [f"sub{i}" for i in range(count)]
        barrier = threading.Barrier(count, timeout=10)

        def request(*args, **kwargs):
            barrier.wait()
            return MagicMock(status_code=200)

        self.setup()
        self.insert_subscriptions(*ids)
        with self.app.app_context(), patch("requests.request", request):
            results = notify_all_subscriptions(
                ids, "org/image:1", MOCK_BUILD_INFO["id"]
            )
        assert [result["result"] for result in results] == ["delivered"] * count

    def test_notify_all_bounds_threads_by_limit(self):
        """IDs beyond the limit, e.g., from older data, add no more threads."""
        lock = threading.Lock()
        running = [0]
        highest = [0]

        def request(*args, **kwargs):
            with lock:
                running[0] += 1
                highest[0] = max(highest[0], running[0])
            time.sleep(0.05)
            with lock:
                running[0] -= 1
            return MagicMock(status_code=200)

        ids = [f"sub{i}" for i in range(6)]
        self.setup()
        self.app.config.foca.endpoints["subscriptions"]["max_per_repository"] = 2
        self.insert_subscriptions(*ids)
        with self.app.app_context(), patch("requests.request", request):
            results = notify_all_subscriptions(
                ids, "org/image:1", MOCK_BUILD_INFO["id"]
            )
        assert [result["result"] for result in results] == ["delivered"] * 6
        assert highest[0] == 2

    def test_notify_all_failure_does_not_stop_others(self):
        """Failures of any kind stay with their subscription."""

        def request(method, url, **kwargs):
            if url.endswith("timeout"):
                raise requests.exceptions.Timeout
            if url.endswith("unexpected"):
                raise ValueError
            return MagicMock(status_code=200)

        self.setup()
        ids = ["timeout", "unexpected", "good"]
        self.insert_subscriptions(*ids)
        with self.app.app_context(), patch("requests.request", request):
            results = notify_all_subscriptions(
                ids, "org/image:1", MOCK_BUILD_INFO["id"]
            )
        assert {r["subscription_id"]: r["result"] for r in results} == {
            "timeout": "failed",
            "unexpected": "failed",
            "good": "delivered",
        }

    def test_notify_all_deleted_subscription(self):
        """A deleted subscription, still listed at its repository, is skipped."""
        self.setup()
        with self.app.app_context():
            results = notify_all_subscriptions(
                ["gone"], "org/image:1", MOCK_BUILD_INFO["id"]
            )
        assert results[0]["result"] == "skipped"

    @patch("requests.request", mocked_request_api)
    def test_notify_all_stores_results_without_secrets(self):
        """Builds are public: their results hold no URLs or tokens."""
        self.setup()
        self.insert_subscriptions("sub1")
        with self.app.app_context():
            notify_all_subscriptions(["sub1"], "org/image:1", MOCK_BUILD_INFO["id"])
        stored = self.get_stored_notifications()
        assert stored[0]["subscription_id"] == "sub1"
        assert stored[0]["http_status"] == 200
        assert "example.org" not in str(stored)
        assert MOCK_SUBSCRIPTION_INFO["access_token"] not in str(stored)

    def test_notify_all_without_subscriptions(self):
        """Without subscriptions, the build has an empty list of results."""
        self.setup()
        with self.app.app_context():
            results = notify_all_subscriptions([], "org/image:1", MOCK_BUILD_INFO["id"])
        assert results == []
        assert self.get_stored_notifications() == []

    def test_notify_all_bounds_total_time(self):
        """A call that goes on past its timeouts counts as failed."""
        release = threading.Event()

        def request(method, url, **kwargs):
            if url.endswith("hanging"):
                release.wait(30)
            return MagicMock(status_code=200)

        self.setup()
        self.app.config.foca.endpoints["subscriptions"]["notification_timeout"] = 0.1
        self.insert_subscriptions("hanging", "good")
        try:
            with (
                self.app.app_context(),
                patch("requests.request", request),
                patch(
                    "pubgrade.modules.endpoints.subscriptions.NOTIFICATION_MARGIN",
                    0,
                ),
            ):
                results = notify_all_subscriptions(
                    ["hanging", "good"], "org/image:1", MOCK_BUILD_INFO["id"]
                )
        finally:
            release.set()
        assert {r["subscription_id"]: r["result"] for r in results} == {
            "hanging": "failed",
            "good": "delivered",
        }

    def test_get_subscription_info_of_other_user(self):
        """Users only see their own subscriptions."""
        self.setup()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                get_subscription_info(
                    MOCK_USER["uid"],
                    MOCK_USER["user_access_token"],
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    def test_delete_subscription_of_other_user(self):
        """Users only delete their own subscriptions."""
        self.setup()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                delete_subscription(
                    MOCK_USER["uid"],
                    MOCK_USER["user_access_token"],
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    def test_subscription_gone_but_listed(self):
        """A subscription listed for its user, but deleted, isn't found."""
        self.setup()
        self.insert_subscription()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.delete_many({})
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                get_subscription_info(
                    MOCK_USER["uid"],
                    MOCK_USER["user_access_token"],
                    MOCK_SUBSCRIPTION_INFO["id"],
                )
            with pytest.raises(SubscriptionNotFound):
                delete_subscription(
                    MOCK_USER["uid"],
                    MOCK_USER["user_access_token"],
                    MOCK_SUBSCRIPTION_INFO["id"],
                )

    @patch("requests.request", mocked_request_api)
    def test_notify_subscriptions_any_value(self):
        """The value `*` matches any value of the subscription's type."""
        self.setup()
        MOCK_SUBSCRIPTION_INFO["value"] = "*"
        self.insert_subscription()
        with self.app.app_context():
            result = notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "org/image:1",
                MOCK_BUILD_INFO["id"],
            )
        assert result["result"] == "delivered"

    @patch("requests.request", mocked_request_api)
    def test_notify_subscriptions_any_value_other_type(self):
        """The value `*` doesn't match other types."""
        self.setup()
        MOCK_SUBSCRIPTION_INFO["value"] = "*"
        MOCK_SUBSCRIPTION_INFO["type"] = "tag"
        self.insert_subscription()
        with self.app.app_context():
            result = notify_subscriptions(
                MOCK_SUBSCRIPTION_INFO["id"],
                "org/image:1",
                MOCK_BUILD_INFO["id"],
            )
        assert result["result"] == "skipped"
