"""Tests for /users endpoint """
from unittest.mock import MagicMock

import logging
import mongomock
import pytest
from flask import Flask
from foca.models.config import MongoConfig, Config
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import InternalServerError, Unauthorized

from pubgrade.errors.exceptions import (
    NameNotFound,
    RegistrationDisabled,
    UserNotFound,
)
from pubgrade.modules.endpoints.users import (
    register_user,
    get_users,
    toggle_user_status,
    delete_user,
    sanitise_text
)
from tests.mock_data import (
    MONGO_CONFIG,
    ENDPOINT_CONFIG,
    MOCK_USER_DB,
    MOCK_ADMIN_USER_1,
    MOCK_SUBSCRIPTION_INFO,
    MOCK_USER,
)


class TestUsers:
    app = Flask(__name__)

    def setup(self):
        self.app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_DB)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "admin_users"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "admin_users"
        ].client.insert_one(MOCK_ADMIN_USER_1)

    def test_register_user(self):
        self.setup()
        with self.app.app_context():
            name = "Akash Saini"
            response = register_user({"name": name})
            assert "uid" in response
            assert "user_access_token" in response
            assert "name" in response
            assert sanitise_text(name) == response["name"]

    def test_register_user_logs_no_token(self, caplog):
        """Log messages name the new user, without its token."""
        self.setup()
        caplog.set_level(logging.DEBUG)
        with self.app.app_context():
            response = register_user({"name": "Name"})
        assert response["uid"] in caplog.text
        assert response["user_access_token"] not in caplog.text

    def test_register_user_closed(self):
        """Registration can be closed by configuration."""
        self.setup()
        self.app.config.foca.endpoints["user"][
            "registration_enabled"
        ] = False
        with self.app.app_context():
            with pytest.raises(RegistrationDisabled):
                register_user({"name": "Name"})

    def test_register_user_keyerror(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(NameNotFound):
                register_user({"wrong_name_key": "Akash Saini"})

    def test_register_user_duplicate_key_error(self):
        app = Flask(__name__)
        app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG),
            endpoints=ENDPOINT_CONFIG,
        )
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client = MagicMock()
        app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one = mock_resp
        with app.app_context():
            with pytest.raises(InternalServerError):
                register_user({"name": "Akash Saini"})

    def test_delete_user(self):
        self.setup()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
        with self.app.app_context():
            response = delete_user(
                uid=MOCK_USER["uid"],
                user_access_token=MOCK_USER["user_access_token"],
            )
            assert response == "User deleted successfully."

    def test_delete_user_user_not_found(self):
        self.setup()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                delete_user(
                    uid="wrong_uid",
                    user_access_token=MOCK_USER["user_access_token"],
                )

    def test_delete_user_unauthorized(self):
        self.setup()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                delete_user(
                    uid=MOCK_USER["uid"],
                    user_access_token="wrong_access_token",
                )

    def test_delete_key_error(self):
        self.app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER)
        with self.app.app_context():
            response = delete_user(
                uid=MOCK_USER["uid"],
                user_access_token=MOCK_USER["user_access_token"],
            )
            assert response == "User deleted successfully."

    def test_get_users(self):
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            user_access_token = MOCK_ADMIN_USER_1["user_access_token"]
            response = get_users(admin_uid, user_access_token)
            assert response[0]["name"] == "Akash Saini"
            assert isinstance(response, list)

    def test_get_users_user_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                get_users("wrong_uid", "wrong_user_access_token")

    def test_get_users_unauthorized(self):
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            with pytest.raises(Unauthorized):
                get_users(admin_uid, "wrong_user_access_token")

    def test_toggle_user_status_false(self):
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            user_access_token = MOCK_ADMIN_USER_1["user_access_token"]
            response = toggle_user_status(
                admin_uid, user_access_token, MOCK_USER_DB["uid"], False
            )
            assert response == "User unverified successfully."

    def test_toggle_user_status_true(self):
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            user_access_token = MOCK_ADMIN_USER_1["user_access_token"]
            response = toggle_user_status(
                admin_uid, user_access_token, MOCK_USER_DB["uid"], True
            )
            assert response == "User verified successfully."

    def test_toggle_user_status_superuser_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                toggle_user_status(
                    "wrong_uid",
                    "wrong_user_access_token",
                    MOCK_USER_DB["uid"],
                    False,
                )

    def test_toggle_user_status_unauthorized(self):
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            with pytest.raises(Unauthorized):
                toggle_user_status(
                    admin_uid,
                    "wrong_user_access_token",
                    MOCK_USER_DB["uid"],
                    False,
                )

    def test_toggle_user_status_user_not_found(self):
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            user_access_token = MOCK_ADMIN_USER_1["user_access_token"]
            with pytest.raises(UserNotFound):
                toggle_user_status(
                    admin_uid, user_access_token, "wrong_uid", False
                )
