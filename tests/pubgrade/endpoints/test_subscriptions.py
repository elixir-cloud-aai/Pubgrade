"""Tests for /subscriptions endpoint """
from unittest.mock import patch, MagicMock

import mongomock
import pytest
import requests
from flask import Flask
from foca.models.config import Config, MongoConfig
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized, InternalServerError

from pubgrade.errors.exceptions import (
    RepositoryNotFound,
    UserNotFound,
    SubscriptionNotFound,
    BuildNotFound,
    RequestNotSent,
    UserNotVerified,
)
from pubgrade.modules.endpoints.subscriptions import (
    register_subscription,
    get_subscriptions,
    get_subscription_info,
    delete_subscription,
    notify_subscriptions,
)
from tests.mock_data import (
    MONGO_CONFIG,
    ENDPOINT_CONFIG,
    MOCK_REPOSITORIES,
    MOCK_BUILD_INFO,
    MOCK_BUILD_INFO_2,
    MOCK_USER,
    MOCK_SUBSCRIPTION_INFO,
    SUBSCRIPTION_PAYLOAD,
    MOCK_USER_DB,
    MOCK_USER_NOT_VERIFIED,
)


def mocked_request_api(method, url, data, headers):
    return "successful"


def mocked_request_api_timeout_error(method, url, data, headers):
    raise requests.exceptions.Timeout


def mocked_request_api_too_many_redirects(method, url, data, headers):
    raise requests.exceptions.TooManyRedirects


def mocked_request_api_request_exception(method, url, data, headers):
    raise requests.exceptions.RequestException


class TestSubscriptions:
    app = Flask(__name__)

    def setup(self):
        self.app.config["FOCA"] = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "builds"
        ].client = mongomock.MongoClient().db.collection
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client = mongomock.MongoClient().db.collection
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
                "repositories"
            ].client.insert_one(repository)
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO)
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO_2)
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER)
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_NOT_VERIFIED)

    def insert_subscription(self):
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_DB)
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)

    def test_register_subscription(self):
        self.setup()
        with self.app.app_context():
            res = register_subscription(
                MOCK_USER["uid"],
                MOCK_USER["user_access_token"],
                SUBSCRIPTION_PAYLOAD,
            )
            data = (
                self.app.config["FOCA"]
                .db.dbs["pubgradeStore"]
                .collections["repositories"]
                .client.find_one({"id": SUBSCRIPTION_PAYLOAD["repository_id"]})
            )
            subscription = (
                self.app.config["FOCA"]
                .db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": res["subscription_id"]})
            )
            assert isinstance(res, dict)
            assert res["subscription_id"] in data["subscription_list"]
            assert subscription["state"] == "Inactive"

    def test_register_subscription_duplicate_key_error(self):
        self.setup()
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
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
        self.app.config["FOCA"] = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "builds"
        ].client = mongomock.MongoClient().db.collection
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client = mongomock.MongoClient().db.collection
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
                "repositories"
            ].client.insert_one(repository)
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO)
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO_2)
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_DB)
        with self.app.app_context():
            res = get_subscriptions(
                MOCK_USER["uid"], MOCK_USER["user_access_token"]
            )
            assert isinstance(res, list)
            assert (
                res[0]["subscription_id"]
                == MOCK_USER_DB["subscription_list"][0]
            )

    def test_get_subscriptions_subscription_not_found(self):
        self.setup()
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_DB)
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                get_subscriptions(
                    MOCK_USER["uid"], MOCK_USER["user_access_token"]
                )

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
                self.app.config["FOCA"]
                .db.dbs["pubgradeStore"]
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
            with pytest.raises(RequestNotSent):
                notify_subscriptions(
                    MOCK_SUBSCRIPTION_INFO["id"],
                    "elixir-cloud-aai/pubgrade:0.0.1",
                    MOCK_BUILD_INFO["id"],
                )
            data = (
                self.app.config["FOCA"]
                .db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": MOCK_SUBSCRIPTION_INFO["id"]})
            )
            assert data["state"] == "Inactive"

    @patch("requests.request", mocked_request_api_too_many_redirects)
    def test_notify_subscriptions_too_many_redirects(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(RequestNotSent):
                notify_subscriptions(
                    MOCK_SUBSCRIPTION_INFO["id"],
                    "elixir-cloud-aai/pubgrade:0.0.1",
                    MOCK_BUILD_INFO["id"],
                )
            data = (
                self.app.config["FOCA"]
                .db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": MOCK_SUBSCRIPTION_INFO["id"]})
            )
            assert data["state"] == "Inactive"

    @patch("requests.request", mocked_request_api_request_exception)
    def test_notify_subscriptions_request_exception(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(RequestNotSent):
                notify_subscriptions(
                    MOCK_SUBSCRIPTION_INFO["id"],
                    "elixir-cloud-aai/pubgrade:0.0.1",
                    MOCK_BUILD_INFO["id"],
                )
            data = (
                self.app.config["FOCA"]
                .db.dbs["pubgradeStore"]
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
                self.app.config["FOCA"]
                .db.dbs["pubgradeStore"]
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
                self.app.config["FOCA"]
                .db.dbs["pubgradeStore"]
                .collections["subscriptions"]
                .client.find_one({"id": MOCK_SUBSCRIPTION_INFO["id"]})
            )
            assert isinstance(data, dict)
            assert data["state"] == "Inactive"
            assert "build_id" not in data
