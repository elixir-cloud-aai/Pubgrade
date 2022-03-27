import mongomock
import pytest

from flask import Flask

from foca.models.config import Config
from foca.models.config import MongoConfig

try:
    from unittest.mock import patch  # Python 3 @UnresolvedImport
except Exception:
    from mock import patch

from pubgrade.errors.exceptions import RepositoryNotFound
from pubgrade.modules.server import (
    getRepositories,
    postRepositories,
    getRepository,
    putRepositories,
    deleteRepository,
    postBuild,
    getBuilds,
    getBuildInfo,
    updateBuild,
    postSubscription,
    getSubscriptions,
    getSubscriptionInfo,
    deleteSubscription,
    postUser,
    getUsers,
    verifyUser,
    unverifyUser,
    deleteUser,
)

from tests.mock_data import (
    MONGO_CONFIG,
    ENDPOINT_CONFIG,
    MOCK_REPOSITORIES,
    MOCK_BUILD_PAYLOAD,
    MOCK_BUILD_INFO,
    MOCK_SUBSCRIPTION_INFO,
    MOCK_USER,
    MOCK_USER_DB,
    MOCK_BUILD_INFO_2,
    SUBSCRIPTION_PAYLOAD,
    MOCK_ADMIN_USER_1,
)

drs_url = "https://github.com/elixir-cloud-aai/drs-filer.git"
user_access_token = "c42a6d44e3d0"
uid = "9fe2c4e93f654fdbb24c02b15259716c"


def mocked_request_api(method, url, data, headers):
    return "successful"


def test_getRepositories():
    """Test for getting Repositories."""
    app = Flask(__name__)
    app.config["FOCA"] = Config(db=MongoConfig(**MONGO_CONFIG))
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    with app.test_request_context():
        res = getRepositories.__wrapped__()
        assert isinstance(res, list)
        for i in range(len(MOCK_REPOSITORIES)):
            assert res[i]["url"] == MOCK_REPOSITORIES[i]["url"]
            assert res[i]["id"] == MOCK_REPOSITORIES[i]["id"]


def test_postRepositories():
    """Test for creating a new repository with an auto-generated
    identifier."""
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    with app.test_request_context(json={"url": drs_url}):
        res = postRepositories.__wrapped__()
        assert isinstance(res, dict)


def test_getRepository():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    with app.test_request_context():
        res = getRepository.__wrapped__(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, dict)
        assert res["url"] == MOCK_REPOSITORIES[1]["url"]


def test_putRepositories():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    with app.test_request_context(
        json={"url": drs_url},
        headers={
            "X-Project-Access-Token": MOCK_REPOSITORIES[1]["access_token"],
            "Content-Type": "application/json",
        },
    ):
        res = putRepositories.__wrapped__(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, dict)
        assert res["id"] == MOCK_REPOSITORIES[1]["id"]


def test_deleteRepository():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    with app.test_request_context(
        headers={
            "X-Project-Access-Token": MOCK_REPOSITORIES[1]["access_token"],
            "Content-Type": "application/json",
        }
    ):
        res = deleteRepository.__wrapped__(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, dict)
        assert res == {"message": "Repository deleted successfully"}


def test_deleteRepository_Not_Found():
    with pytest.raises(RepositoryNotFound):
        app = Flask(__name__)
        app.config["FOCA"] = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            app.config["FOCA"].db.dbs["pubgradeStore"].collections[
                "repositories"
            ].client.insert_one(repository)
        with app.test_request_context(
            headers={
                "X-Project-Access-Token": MOCK_REPOSITORIES[1]["access_token"],
                "Content-Type": "application/json",
            }
        ):
            deleteRepository.__wrapped__("repo_abcd")


def mocked_create_build(
    repo_url,
    branch,
    commit,
    base_dir,
    build_id,
    dockerfile_location,
    registry_destination,
    dockerhub_token,
    project_access_token,
):
    # Need a mock for kubernetes
    return "working fine"


@patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
def test_postBuild():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "builds"
    ].client = mongomock.MongoClient().db.collection
    with app.test_request_context(
        json=MOCK_BUILD_PAYLOAD,
        headers={
            "X-Project-Access-Token": "g.i.ssstitrti.ccier.tgsactt.iosg",
            "Content-Type": "application/json",
        },
    ):
        res = postBuild.__wrapped__(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, dict)


def test_getBuilds():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "builds"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "builds"
    ].client.insert_one(MOCK_BUILD_INFO)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "builds"
    ].client.insert_one(MOCK_BUILD_INFO_2)
    with app.test_request_context():
        res = getBuilds.__wrapped__(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, list)
        assert isinstance(res[0], dict)


def test_getBuildInfo():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "builds"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "builds"
    ].client.insert_one(MOCK_BUILD_INFO)
    with app.test_request_context():
        res = getBuildInfo.__wrapped__(
            MOCK_REPOSITORIES[1]["id"], MOCK_BUILD_INFO["id"]
        )
        assert isinstance(res, dict)


def mock_remove_files(dir_location: str, pod_name: str, namespace: str):
    return "remove files successful"


def mock_notify_subscriptions():
    return "notify successful"


@patch("pubgrade.modules.endpoints.builds.remove_files", mock_remove_files)
@patch("requests.request", mocked_request_api)
def test_updateBuild():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
    for repository in MOCK_REPOSITORIES:
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "builds"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "builds"
    ].client.insert_one(MOCK_BUILD_INFO)
    with app.test_request_context(
        json=MOCK_BUILD_PAYLOAD,
        headers={
            "X-Project-Access-Token": "g.i.ssstitrti.ccier.tgsactt.iosg",
            "Content-Type": "application/json",
        },
    ):
        res = updateBuild.__wrapped__(
            MOCK_REPOSITORIES[1]["id"], MOCK_BUILD_INFO["id"]
        )
        assert isinstance(res, dict)


def test_postSubscription():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client.insert_one(MOCK_USER)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    with app.test_request_context(
        json=SUBSCRIPTION_PAYLOAD,
        headers={
            "X-User-Access-Token": user_access_token,
            "X-User-Id": uid,
            "Content-Type": "application/json",
        },
    ):
        res = postSubscription.__wrapped__()
        assert isinstance(res, dict)


def test_getSubscriptions():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client.insert_one(MOCK_USER_DB)
    with app.test_request_context(
        headers={
            "X-User-Access-Token": user_access_token,
            "X-User-Id": uid,
            "Content-Type": "application/json",
        }
    ):
        res = getSubscriptions.__wrapped__()
        assert isinstance(res, list)


def test_getSubscriptionInfo():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client.insert_one(MOCK_USER_DB)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
    with app.test_request_context(
        headers={
            "X-User-Access-Token": user_access_token,
            "X-User-Id": uid,
            "Content-Type": "application/json",
        }
    ):
        res = getSubscriptionInfo.__wrapped__(MOCK_SUBSCRIPTION_INFO["id"])
        assert isinstance(res, dict)


def test_deleteSubscription():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client.insert_one(MOCK_USER_DB)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
    with app.test_request_context(
        headers={
            "X-User-Access-Token": user_access_token,
            "X-User-Id": uid,
            "Content-Type": "application/json",
        }
    ):
        res = deleteSubscription.__wrapped__(MOCK_SUBSCRIPTION_INFO["id"])
        assert isinstance(res, dict)


def test_post_user():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection

    with app.test_request_context(
        json={"name": "Akash Saini"},
        headers={"Content-Type": "application/json"},
    ):
        res = postUser.__wrapped__()
        assert isinstance(res, dict)
        assert "uid" in res
        assert "user_access_token" in res
        assert "name" in res


def test_deleteUser():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client.insert_one(MOCK_USER_DB)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
    with app.test_request_context(
        headers={
            "X-User-Access-Token": user_access_token,
            "X-User-Id": uid,
            "Content-Type": "application/json",
        },
    ):
        res = deleteUser.__wrapped__()
        assert res == "User deleted successfully."


def test_get_user():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )

    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client.insert_one(MOCK_USER_DB)

    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client.insert_one(MOCK_ADMIN_USER_1)

    with app.test_request_context(
        json={},
        headers={
            "X-Super-User-Id": MOCK_ADMIN_USER_1["uid"],
            "X-Super-User-Access-Token": MOCK_ADMIN_USER_1[
                "user_access_token"
            ],
            "Content-Type": "application/json",
        },
    ):
        res = getUsers.__wrapped__()
        assert res[0]["name"] == "Akash Saini"
        assert isinstance(res, list)


def test_verify_user():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client.insert_one(MOCK_USER_DB)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client.insert_one(MOCK_ADMIN_USER_1)

    with app.test_request_context(
        json={},
        headers={
            "X-Super-User-Id": MOCK_ADMIN_USER_1["uid"],
            "X-Super-User-Access-Token": MOCK_ADMIN_USER_1[
                "user_access_token"
            ],
            "Content-Type": "application/json",
        },
    ):
        response = verifyUser.__wrapped__(MOCK_USER_DB["uid"])
        assert response == "User verified successfully."


def test_unverify_user():
    app = Flask(__name__)
    app.config["FOCA"] = Config(
        db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
    )
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "users"
    ].client.insert_one(MOCK_USER_DB)
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client = mongomock.MongoClient().db.collection
    app.config["FOCA"].db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client.insert_one(MOCK_ADMIN_USER_1)

    with app.test_request_context(
        json={},
        headers={
            "X-Super-User-Id": MOCK_ADMIN_USER_1["uid"],
            "X-Super-User-Access-Token": MOCK_ADMIN_USER_1[
                "user_access_token"
            ],
            "Content-Type": "application/json",
        },
    ):
        response = unverifyUser.__wrapped__(MOCK_USER_DB["uid"])
        assert response == "User unverified successfully."
