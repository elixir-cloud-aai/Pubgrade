"""Tests for the server controllers (`pubgrade.modules.server`)."""

from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

from flask import Flask
from foca.models.config import MongoConfig
import mongomock
import pytest

from pubgrade.errors.exceptions import RepositoryNotFound
from pubgrade.modules.endpoints import builds
from pubgrade.modules.server import (
    deleteBuild,
    deleteRepository,
    deleteSubscription,
    deleteUser,
    getBuildInfo,
    getBuilds,
    getRepositories,
    getRepository,
    getSubscriptionInfo,
    getSubscriptions,
    getUsers,
    postBuild,
    postRepositories,
    postSubscription,
    postUser,
    putRepositories,
    unverifyUser,
    updateBuild,
    verifyUser,
)
from tests.helpers import foca_config, set_foca, unwrap
from tests.mock_data import (
    ENDPOINT_CONFIG,
    MOCK_ADMIN_USER_1,
    MOCK_BUILD_INFO,
    MOCK_BUILD_INFO_2,
    MOCK_BUILD_PAYLOAD,
    MOCK_REPOSITORIES,
    MOCK_SUBSCRIPTION_INFO,
    MOCK_USER,
    MOCK_USER_DB,
    MONGO_CONFIG,
    SUBSCRIPTION_PAYLOAD,
)

drs_url = "https://github.com/elixir-cloud-aai/drs-filer.git"
user_access_token = "c42a6d44e3d0"
uid = "9fe2c4e93f654fdbb24c02b15259716c"


def mocked_request_api(
    method: str, url: str, data: Any, headers: Any, **kwargs: Any
) -> MagicMock:
    """Answer a request with status 200, or 204 for GitHub's dispatches.

    Args:
        method: HTTP method.
        url: URL.
        data: Body.
        headers: Headers.
        **kwargs: Other arguments.

    Returns:
        A mocked response.
    """
    return MagicMock(
        status_code=204 if urlsplit(url).hostname == "api.github.com" else 200
    )


def test_getRepositories() -> None:
    """Test for getting Repositories."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG))
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    with app.test_request_context():
        res = unwrap(getRepositories)()
        assert isinstance(res, list)
        for i in range(len(MOCK_REPOSITORIES)):
            assert res[i]["url"] == MOCK_REPOSITORIES[i]["url"]
            assert res[i]["id"] == MOCK_REPOSITORIES[i]["id"]


def test_postRepositories() -> None:
    """A repository is created with an auto-generated identifier."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    with app.test_request_context(json={"url": drs_url}):
        res = unwrap(postRepositories)()
        assert isinstance(res, dict)


def test_getRepository() -> None:
    """The `getRepository` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    with app.test_request_context():
        res = unwrap(getRepository)(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, dict)
        assert res["url"] == MOCK_REPOSITORIES[1]["url"]


def test_putRepositories() -> None:
    """The `putRepositories` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    with app.test_request_context(
        json={"url": drs_url},
        headers={
            "X-Project-Access-Token": MOCK_REPOSITORIES[1]["access_token"],
            "Content-Type": "application/json",
        },
    ):
        res = unwrap(putRepositories)(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, dict)
        assert res["id"] == MOCK_REPOSITORIES[1]["id"]


def test_deleteRepository(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `deleteRepository` controller works.

    Args:
        monkeypatch: Fixture to replace the calls to Kubernetes.
    """
    monkeypatch.setattr(builds, "stop_builds", lambda build_ids: None)
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    for name in ("repositories", "builds", "subscriptions", "users"):
        foca_config(app).db.dbs["pubgradeStore"].collections[
            name
        ].client = mongomock.MongoClient().db[name]
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    with app.test_request_context(
        headers={
            "X-Project-Access-Token": MOCK_REPOSITORIES[1]["access_token"],
            "Content-Type": "application/json",
        }
    ):
        res = unwrap(deleteRepository)(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, dict)
        assert res == {"message": "Repository deleted successfully"}


def test_deleteRepository_Not_Found() -> None:
    """Deleting an unknown repository fails."""
    with pytest.raises(RepositoryNotFound):
        app = Flask(__name__)
        set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            foca_config(app).db.dbs["pubgradeStore"].collections[
                "repositories"
            ].client.insert_one(repository)
        with app.test_request_context(
            headers={
                "X-Project-Access-Token": MOCK_REPOSITORIES[1]["access_token"],
                "Content-Type": "application/json",
            }
        ):
            unwrap(deleteRepository)("repo_abcd")


def mocked_create_build(
    repo_url: Any,
    branch: Any,
    commit: Any,
    base_dir: Any,
    build_id: Any,
    dockerfile_location: Any,
    intermediate_registry_path: Any,
    dockerhub_token: Any,
    project_access_token: Any,
    repository_id: Any,
) -> str:
    """Stand in for the creation of a build, which needs Kubernetes.

    Args:
        repo_url: URL of the repository.
        branch: Branch.
        commit: Commit.
        base_dir: Base directory.
        build_id: Build identifier.
        dockerfile_location: Location of the `Dockerfile`.
        intermediate_registry_path: Path in the intermediate registry.
        dockerhub_token: Token of the registry.
        project_access_token: Access token of the repository.
        repository_id: Identifier of the repository.

    Returns:
        A fixed message.
    """
    # Need a mock for kubernetes
    return "working fine"


@patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
def test_postBuild() -> None:
    """The `postBuild` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "builds"
    ].client = mongomock.MongoClient().db.collection
    with app.test_request_context(
        json=MOCK_BUILD_PAYLOAD,
        headers={
            "X-Project-Access-Token": "g.i.ssstitrti.ccier.tgsactt.iosg",
            "Content-Type": "application/json",
        },
    ):
        res = unwrap(postBuild)(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, dict)


def test_getBuilds() -> None:
    """The `getBuilds` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "builds"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["builds"].client.insert_one(
        MOCK_BUILD_INFO
    )
    foca_config(app).db.dbs["pubgradeStore"].collections["builds"].client.insert_one(
        MOCK_BUILD_INFO_2
    )
    with app.test_request_context():
        res = unwrap(getBuilds)(MOCK_REPOSITORIES[1]["id"])
        assert isinstance(res, list)
        assert isinstance(res[0], dict)


def test_getBuildInfo() -> None:
    """The `getBuildInfo` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "builds"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["builds"].client.insert_one(
        MOCK_BUILD_INFO
    )
    with app.test_request_context():
        res = unwrap(getBuildInfo)(MOCK_REPOSITORIES[1]["id"], MOCK_BUILD_INFO["id"])
        assert isinstance(res, dict)


def mock_remove_files(dir_location: str, pod_name: str, namespace: str) -> str:
    """Stand in for the removal of files.

    Args:
        dir_location: Directory.
        pod_name: Name of the pod.
        namespace: Namespace.

    Returns:
        A fixed message.
    """
    return "remove files successful"


def mock_notify_subscriptions() -> str:
    """Stand in for the notification of subscriptions.

    Returns:
        A fixed message.
    """
    return "notify successful"


@patch("pubgrade.modules.endpoints.builds.remove_files", mock_remove_files)
@patch("requests.request", mocked_request_api)
def test_updateBuild() -> None:
    """The `updateBuild` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(repository)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "builds"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["builds"].client.insert_one(
        MOCK_BUILD_INFO
    )
    with app.test_request_context(
        json=MOCK_BUILD_PAYLOAD,
        headers={
            "X-Project-Access-Token": "g.i.ssstitrti.ccier.tgsactt.iosg",
            "Content-Type": "application/json",
        },
    ):
        res = unwrap(updateBuild)(MOCK_REPOSITORIES[1]["id"], MOCK_BUILD_INFO["id"])
        assert isinstance(res, dict)


def test_deleteBuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `deleteBuild` controller withdraws a build.

    Args:
        monkeypatch: Fixture to replace the calls to Kubernetes.
    """
    monkeypatch.setattr(builds, "stop_builds", lambda build_ids, force=False: None)
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    for name in ("repositories", "builds"):
        foca_config(app).db.dbs["pubgradeStore"].collections[
            name
        ].client = mongomock.MongoClient().db[name]
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one(dict(repository))
    foca_config(app).db.dbs["pubgradeStore"].collections["builds"].client.insert_one(
        dict(MOCK_BUILD_INFO)
    )
    with app.test_request_context(
        headers={"X-Project-Access-Token": MOCK_REPOSITORIES[1]["access_token"]}
    ):
        res = unwrap(deleteBuild)(MOCK_REPOSITORIES[1]["id"], MOCK_BUILD_INFO["id"])
    assert res == {"id": MOCK_BUILD_INFO["id"]}
    stored = (
        foca_config(app)
        .db.dbs["pubgradeStore"]
        .collections["builds"]
        .client.find_one({"id": MOCK_BUILD_INFO["id"]})
    )
    assert stored["status"] == "CANCELED"


def test_postSubscription() -> None:
    """The `postSubscription` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["users"].client.insert_one(
        MOCK_USER
    )
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    for repository in MOCK_REPOSITORIES:
        foca_config(app).db.dbs["pubgradeStore"].collections[
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
        res = unwrap(postSubscription)()
        assert isinstance(res, dict)


def test_getSubscriptions() -> None:
    """The `getSubscriptions` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["users"].client.insert_one(
        MOCK_USER_DB
    )
    with app.test_request_context(
        headers={
            "X-User-Access-Token": user_access_token,
            "X-User-Id": uid,
            "Content-Type": "application/json",
        }
    ):
        res = unwrap(getSubscriptions)()
        assert isinstance(res, list)


def test_getSubscriptionInfo() -> None:
    """The `getSubscriptionInfo` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["users"].client.insert_one(
        MOCK_USER_DB
    )
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
    with app.test_request_context(
        headers={
            "X-User-Access-Token": user_access_token,
            "X-User-Id": uid,
            "Content-Type": "application/json",
        }
    ):
        res = unwrap(getSubscriptionInfo)(MOCK_SUBSCRIPTION_INFO["id"])
        assert isinstance(res, dict)


def test_deleteSubscription() -> None:
    """The `deleteSubscription` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["users"].client.insert_one(
        MOCK_USER_DB
    )
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "repositories"
    ].client = mongomock.MongoClient().db.collection
    with app.test_request_context(
        headers={
            "X-User-Access-Token": user_access_token,
            "X-User-Id": uid,
            "Content-Type": "application/json",
        }
    ):
        res = unwrap(deleteSubscription)(MOCK_SUBSCRIPTION_INFO["id"])
        assert isinstance(res, dict)


@pytest.mark.parametrize(
    ("controller", "function"),
    [
        (deleteSubscription, "delete_subscription"),
    ],
)
def test_delete_nothing_deleted(
    monkeypatch: pytest.MonkeyPatch, controller: Any, function: str
) -> None:
    """The delete controllers return nothing if nothing was deleted."""
    monkeypatch.setattr(f"pubgrade.modules.server.{function}", lambda *args: 0)
    app = Flask(__name__)
    with app.test_request_context(
        headers={
            "X-Project-Access-Token": "token",
            "X-User-Access-Token": "token",
            "X-User-Id": "uid",
        }
    ):
        assert unwrap(controller)("id") is None


def test_post_user() -> None:
    """The `postUser` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection

    with app.test_request_context(
        json={"name": "Akash Saini"},
        headers={"Content-Type": "application/json"},
    ):
        res = unwrap(postUser)()
        assert isinstance(res, dict)
        assert "uid" in res
        assert "user_access_token" in res
        assert "name" in res


def test_deleteUser() -> None:
    """The `deleteUser` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["users"].client.insert_one(
        MOCK_USER_DB
    )
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "subscriptions"
    ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
    with app.test_request_context(
        headers={
            "X-User-Access-Token": user_access_token,
            "X-User-Id": uid,
            "Content-Type": "application/json",
        },
    ):
        res = unwrap(deleteUser)()
        assert res == "User deleted successfully."


def test_get_user() -> None:
    """The `getUsers` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)

    foca_config(app).db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["users"].client.insert_one(
        MOCK_USER_DB
    )

    foca_config(app).db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client.insert_one(MOCK_ADMIN_USER_1)

    with app.test_request_context(
        json={},
        headers={
            "X-Super-User-Id": MOCK_ADMIN_USER_1["uid"],
            "X-Super-User-Access-Token": MOCK_ADMIN_USER_1["user_access_token"],
            "Content-Type": "application/json",
        },
    ):
        res = unwrap(getUsers)()
        assert res[0]["name"] == "Akash Saini"
        assert isinstance(res, list)


def test_verify_user() -> None:
    """The `verifyUser` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["users"].client.insert_one(
        MOCK_USER_DB
    )
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client.insert_one(MOCK_ADMIN_USER_1)

    with app.test_request_context(
        json={},
        headers={
            "X-Super-User-Id": MOCK_ADMIN_USER_1["uid"],
            "X-Super-User-Access-Token": MOCK_ADMIN_USER_1["user_access_token"],
            "Content-Type": "application/json",
        },
    ):
        response = unwrap(verifyUser)(MOCK_USER_DB["uid"])
        assert response == "User verified successfully."


def test_unverify_user() -> None:
    """The `unverifyUser` controller works."""
    app = Flask(__name__)
    set_foca(app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections["users"].client.insert_one(
        MOCK_USER_DB
    )
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client = mongomock.MongoClient().db.collection
    foca_config(app).db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client.insert_one(MOCK_ADMIN_USER_1)

    with app.test_request_context(
        json={},
        headers={
            "X-Super-User-Id": MOCK_ADMIN_USER_1["uid"],
            "X-Super-User-Access-Token": MOCK_ADMIN_USER_1["user_access_token"],
            "Content-Type": "application/json",
        },
    ):
        response = unwrap(unverifyUser)(MOCK_USER_DB["uid"])
        assert response == "User unverified successfully."
