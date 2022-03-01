"""Tests for /users endpoint """
from unittest.mock import MagicMock

import mongomock
import pytest
from flask import Flask
from foca.models.config import MongoConfig, Config
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import InternalServerError, Unauthorized

from pubgrade.errors.exceptions import UserNotFound, NameNotFound
from pubgrade.modules.endpoints.users import (
    register_user,
    get_users,
    toggle_user_status,
)
from tests.mock_data import (
    MONGO_CONFIG,
    ENDPOINT_CONFIG,
    MOCK_USER_DB,
    MOCK_ADMIN_USER_1,
)


class TestUsers:
    app = Flask(__name__)

    def setup(self):
        self.app.config["FOCA"] = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client = mongomock.MongoClient().db.collection
        # for repository in MOCK_REPOSITORIES:
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_DB)
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "admin_users"
        ].client = mongomock.MongoClient().db.collection
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
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
            assert name == response["name"]

    def test_register_user_keyerror(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(NameNotFound):
                register_user({"wrong_name_key": "Akash Saini"})

    def test_register_user_duplicate_key_error(self):
        app = Flask(__name__)
        app.config["FOCA"] = Config(
            db=MongoConfig(**MONGO_CONFIG),
            endpoints=ENDPOINT_CONFIG,
        )
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client = MagicMock()
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one = mock_resp
        with app.app_context():
            with pytest.raises(InternalServerError):
                register_user({"name": "Akash Saini"})

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
