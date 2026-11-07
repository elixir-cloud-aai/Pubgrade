"""Integration tests of the API: register, publish and notify."""

from pathlib import Path
import socket
from types import SimpleNamespace
from typing import Any

from flask.testing import FlaskClient
import pytest
import yaml

from pubgrade.app import CONFIG_FILE
from pubgrade.errors.exceptions import BuildCanceled, GitRefNotFound, exceptions
from pubgrade.modules.endpoints import builds
from pubgrade.settings import collection, endpoints
from tests.integration.conftest import ADMIN, Subscriber

ADMIN_HEADERS = {
    "X-Super-User-Id": ADMIN["uid"],
    "X-Super-User-Access-Token": ADMIN["user_access_token"],
}


def check(response: Any, status: int = 200) -> Any:
    """Check the status of a response and get its JSON body.

    Args:
        response: Response of the test client.
        status: Expected status code.

    Returns:
        The JSON body.
    """
    assert response.status_code == status, response.json
    return response.json


def register_user(api: FlaskClient, verify: bool = True) -> dict[str, str]:
    """Register a user, verified by the admin unless `verify` is false.

    Args:
        api: Client of the API.
        verify: Whether the admin verifies the user.

    Returns:
        Headers that authenticate the user.
    """
    user = check(api.post("/users/register", json={"name": "Deployer"}))
    if verify:
        check(api.put(f"/users/{user['uid']}/verify", headers=ADMIN_HEADERS))
    return {
        "X-User-Id": user["uid"],
        "X-User-Access-Token": user["user_access_token"],
    }


def register_repository(api: FlaskClient) -> dict[str, str]:
    """Register a repository.

    Args:
        api: Client of the API.

    Returns:
        Its identifier (`id`) and access token (`access_token`).
    """
    repository: dict[str, str] = check(
        api.post(
            "/repositories",
            json={"url": "https://github.com/elixir-cloud-aai/app.git"},
        )
    )
    return repository


def subscribe(
    api: FlaskClient,
    user: dict[str, str],
    repository_id: str,
    callback_url: str,
    value: str = "1",
    status: int = 200,
) -> Any:
    """Subscribe to the tags of a repository.

    Args:
        api: Client of the API.
        user: Headers that authenticate the user.
        repository_id: Identifier of the repository.
        callback_url: URL to notify.
        value: Tag to subscribe to (`*` for all).
        status: Expected status code.

    Returns:
        Identifier of the subscription, or the error for other statuses than
        200.
    """
    body = check(
        api.post(
            "/subscriptions",
            headers=user,
            json={
                "repository_id": repository_id,
                "callback_url": callback_url,
                "access_token": "subscriber-token",
                "type": "tag",
                "value": value,
            },
        ),
        status,
    )
    return body["subscription_id"] if status == 200 else body


def publish(
    api: FlaskClient,
    repository: dict[str, str],
    tag: str,
    status: int = 200,
) -> Any:
    """Publish a prebuilt image and get the build.

    Args:
        api: Client of the API.
        repository: Identifier and access token of the repository.
        tag: Tag of the image and of the commit.
        status: Expected status code.

    Returns:
        The build, as the API returns it, or the error for other statuses
        than 200.
    """
    body = check(
        api.post(
            f"/repositories/{repository['id']}/builds",
            headers={"X-Project-Access-Token": repository["access_token"]},
            json={
                "images": [{"name": f"org/image:{tag}"}],
                "head_commit": {"tag": tag},
            },
        ),
        status,
    )
    if status != 200:
        return body
    return check(api.get(f"/repositories/{repository['id']}/builds/{body['id']}"))


def subscriptions(api: FlaskClient) -> int:
    """Count the stored subscriptions.

    Args:
        api: Client of the API.

    Returns:
        Number of subscriptions in the database.
    """
    with api.application.app_context():
        return collection("subscriptions").count_documents({})


def results(build: dict[str, Any]) -> dict[str, tuple[str, int | None]]:
    """Get the results of a build's notifications.

    Args:
        build: The build, as the API returns it.

    Returns:
        Result and HTTP status, by subscription.
    """
    return {
        result["subscription_id"]: (result["result"], result["http_status"])
        for result in build["notifications"]
    }


def test_publish_notifies_subscribers(api: FlaskClient, subscriber: Subscriber) -> None:
    """Publishing an image notifies the subscriptions that match it."""
    user = register_user(api)
    repository = register_repository(api)
    matching = subscribe(api, user, repository["id"], subscriber.url)
    other = subscribe(api, user, repository["id"], subscriber.url, value="2")

    build = publish(api, repository, "1")

    assert subscriber.received == [
        {
            "path": "/update",
            "token": "subscriber-token",
            "content_type": "application/json",
            "body": {"image_name": "org/image", "tag": "1"},
        }
    ]
    assert build["status"] == "SUCCEEDED"
    assert results(build) == {matching: ("delivered", 200), other: ("skipped", None)}
    subscription = check(api.get(f"/subscriptions/{matching}", headers=user))
    assert subscription["state"] == "Active"
    listed = check(api.get("/subscriptions", headers=user))
    assert sorted(item["subscription_id"] for item in listed) == sorted(
        [matching, other]
    )


def test_notification_matches_spec(api: FlaskClient, subscriber: Subscriber) -> None:
    """The notification is what the API's callback `notification` describes.

    The callback of `POST /subscriptions` documents the call for subscribers
    that write their own listener.
    """
    config = yaml.safe_load(CONFIG_FILE.read_text())
    spec = yaml.safe_load(
        (CONFIG_FILE.parent / config["api"]["specs"]["pubgrade"]["path"]).read_text()
    )
    callback = spec["paths"]["/subscriptions"]["post"]["callbacks"]["notification"][
        "{$request.body#/callback_url}"
    ]["put"]
    schema = spec["components"]["schemas"]["NotificationRequest"]
    user = register_user(api)
    repository = register_repository(api)
    subscribe(api, user, repository["id"], subscriber.url)
    publish(api, repository, "1")
    [received] = subscriber.received
    assert callback["parameters"] == [
        {
            "in": "header",
            "name": "X-Access-Token",
            "required": True,
            "schema": {"type": "string"},
            "description": callback["parameters"][0]["description"],
        }
    ]
    assert received["token"] == "subscriber-token"
    assert received["content_type"] == "application/json"
    assert callback["requestBody"]["content"] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/NotificationRequest"}
        }
    }
    assert set(received["body"]) == set(schema["properties"]) == set(schema["required"])
    assert all(isinstance(value, str) for value in received["body"].values())


def test_publish_with_error_response(api: FlaskClient, subscriber: Subscriber) -> None:
    """A subscriber that answers with an error fails the build."""
    subscriber.status = 500
    user = register_user(api)
    repository = register_repository(api)
    subscription = subscribe(api, user, repository["id"], subscriber.url, value="*")

    build = publish(api, repository, "3")

    assert len(subscriber.received) == 1
    assert build["status"] == "FAILED"
    assert results(build) == {subscription: ("failed", 500)}
    state = check(api.get(f"/subscriptions/{subscription}", headers=user))["state"]
    assert state == "Inactive"


# For its proxy bypass only
@pytest.mark.usefixtures("subscriber")
def test_publish_with_unreachable_subscriber(api: FlaskClient) -> None:
    """A subscriber that can't be reached fails the build, without a status."""
    user = register_user(api)
    repository = register_repository(api)
    # A port that is bound but not listening refuses connections, and no other
    # process can take it meanwhile
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        subscription = subscribe(
            api, user, repository["id"], f"http://127.0.0.1:{port}/update"
        )
        build = publish(api, repository, "1")

    assert build["status"] == "FAILED"
    assert results(build) == {subscription: ("failed", None)}


def test_publish_without_subscriptions(api: FlaskClient) -> None:
    """Publishing to a repository without subscriptions succeeds."""
    build = publish(api, register_repository(api), "1")
    assert build["status"] == "SUCCEEDED"
    assert build["notifications"] == []


def test_unverified_user_cannot_subscribe(
    api: FlaskClient, subscriber: Subscriber
) -> None:
    """Users need to be verified by an admin before they can subscribe."""
    user = register_user(api, verify=False)
    repository = register_repository(api)
    subscribe(api, user, repository["id"], subscriber.url, status=403)
    assert subscriptions(api) == 0


def test_subscribe_to_unknown_repository(
    api: FlaskClient, subscriber: Subscriber
) -> None:
    """Subscriptions need a registered repository."""
    subscribe(api, register_user(api), "unknown", subscriber.url, status=404)
    assert subscriptions(api) == 0


def test_publish_needs_repository_token(api: FlaskClient) -> None:
    """Only the repository's access token allows publishing."""
    repository = register_repository(api)
    publish(api, {**repository, "access_token": "wrong"}, "1", status=401)
    check(api.get(f"/repositories/{repository['id']}/builds"), 404)


def test_repositories_hide_tokens(api: FlaskClient) -> None:
    """Listed and retrieved repositories don't show their access tokens."""
    repository = register_repository(api)
    listed: list[dict[str, Any]] = check(api.get("/repositories"))
    assert [item["id"] for item in listed] == [repository["id"]]
    retrieved = check(api.get(f"/repositories/{repository['id']}"))
    for item in [*listed, retrieved]:
        assert "access_token" not in item


@pytest.mark.parametrize(
    "head_commit",
    [
        {"branch": "missing"},
        {"branch": "dev", "commit_sha": "0000000"},
        {"tag": "v9"},
        {"tag": "HEAD~1"},
        {"tag": ""},
        {"branch": ""},
    ],
)
def test_build_of_unknown_ref(
    api: FlaskClient,
    drs_filer: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    head_commit: dict[str, str],
) -> None:
    """A build of a branch, tag or commit that the repository lacks gets a 400.

    Regression test for issue #28, where it got a 500. The build isn't
    recorded and leaves no files. Git clones the repository's URL on GitHub
    from the local copy (fixture `drs_filer`), so the URL must not end in
    `.git`.

    Args:
        api: Client of the API.
        drs_filer: Local copy of the repository `drs-filer`.
        tmp_path: Temporary directory for the builds' files.
        monkeypatch: Pytest's monkeypatch fixture.
        head_commit: Branch, commit or tag to build.
    """
    builds_dir = tmp_path / "builds"
    builds_dir.mkdir()
    monkeypatch.setattr(builds, "BASE_DIR", str(builds_dir))
    with api.application.app_context():
        settings = endpoints()["builds"]
    monkeypatch.setitem(settings, "enabled", True)
    monkeypatch.setitem(
        settings, "intermediate_registery_format", "registry.example.org/{}"
    )
    repository = check(
        api.post(
            "/repositories",
            json={"url": "https://github.com/elixir-cloud-aai/drs-filer"},
        )
    )
    error = check(
        api.post(
            f"/repositories/{repository['id']}/builds",
            headers={"X-Project-Access-Token": repository["access_token"]},
            json={
                "images": [{"name": "org/image:1", "location": "Dockerfile"}],
                "head_commit": head_commit,
                "dockerhub_token": "dXNlcjpwYXNzd2Q=",  # user:passwd  gitleaks:allow
            },
        ),
        400,
    )
    assert error == {
        "title": "Bad Request",
        "status": 400,
        "detail": exceptions[GitRefNotFound]["detail"],
    }
    assert list(builds_dir.iterdir()) == []
    with api.application.app_context():
        assert collection("builds").count_documents({}) == 0
        stored = collection("repositories").find_one({"id": repository["id"]})
    assert stored is not None
    assert not stored.get("build_list")


def test_modify_repository_keeps_builds_and_subscriptions(
    api: FlaskClient, subscriber: Subscriber
) -> None:
    """Modifying a repository changes its URL, nothing else.

    Regression test: the repository lost its builds and subscriptions, so
    they were neither listed nor notified any more.
    """
    user = register_user(api)
    repository = register_repository(api)
    subscribe(api, user, repository["id"], subscriber.url, value="*")
    publish(api, repository, "1")
    url = "https://github.com/elixir-cloud-aai/other.git"
    path = f"/repositories/{repository['id']}"
    check(
        api.put(path, json={"url": url}, headers={"X-Project-Access-Token": "x"}), 401
    )
    modified = check(
        api.put(
            path,
            json={"url": url},
            headers={"X-Project-Access-Token": repository["access_token"]},
        )
    )
    assert modified == repository
    stored = check(api.get(path))
    assert stored["url"] == url
    assert len(stored["build_list"]) == 1
    assert len(check(api.get(f"{path}/builds"))) == 1
    second = publish(api, repository, "2")
    assert [result for result, _ in results(second).values()] == ["delivered"]
    assert len(subscriber.received) == 2


def test_modify_unknown_repository(api: FlaskClient) -> None:
    """Modifying an unknown repository gets a 404."""
    check(
        api.put(
            "/repositories/unknown",
            json={"url": "https://github.com/elixir-cloud-aai/app.git"},
            headers={"X-Project-Access-Token": "x"},
        ),
        404,
    )


def test_delete_repository_removes_builds_and_subscriptions(
    api: FlaskClient, subscriber: Subscriber
) -> None:
    """Deleting a repository removes its builds and subscriptions.

    Only the repository's own access token allows it; other repositories
    keep theirs.
    """
    user = register_user(api)
    repository = register_repository(api)
    other = register_repository(api)
    subscription = subscribe(api, user, repository["id"], subscriber.url, value="*")
    kept = subscribe(api, user, other["id"], subscriber.url, value="*")
    publish(api, repository, "1")
    publish(api, other, "1")
    path = f"/repositories/{repository['id']}"
    check(api.delete(path, headers={"X-Project-Access-Token": "wrong"}), 401)
    check(
        api.delete(path, headers={"X-Project-Access-Token": other["access_token"]}), 401
    )
    headers = {"X-Project-Access-Token": repository["access_token"]}
    assert check(api.delete(path, headers=headers)) == {
        "message": "Repository deleted successfully"
    }
    check(api.get(path), 404)
    check(api.get(f"{path}/builds"), 404)
    check(api.get(f"/subscriptions/{subscription}", headers=user), 404)
    assert check(api.get("/subscriptions", headers=user)) == [{"subscription_id": kept}]
    assert [item["id"] for item in check(api.get("/repositories"))] == [other["id"]]
    assert len(check(api.get(f"/repositories/{other['id']}/builds"))) == 1
    with api.application.app_context():
        assert collection("builds").count_documents({}) == 1
    assert subscriptions(api) == 1
    check(api.delete(path, headers=headers), 404)


def test_delete_repository_stops_running_build(
    api: FlaskClient,
    drs_filer: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With builds switched on, deleting a repository stops its running builds.

    The build's pod is deleted and its files are removed; the report of the
    finished pod then finds no repository. Kubernetes is replaced by mocks;
    Git clones from a local copy (fixture `drs_filer`).

    Args:
        api: Client of the API.
        drs_filer: Local copy of the repository `drs-filer`.
        tmp_path: Temporary directory for the builds' files.
        monkeypatch: Pytest's monkeypatch fixture.
    """
    builds_dir = tmp_path / "builds"
    builds_dir.mkdir()
    monkeypatch.setattr(builds, "BASE_DIR", str(builds_dir))
    monkeypatch.setattr(
        builds,
        "template_file",
        str(Path(builds.__file__).parent / "kaniko" / "template.yaml"),
    )
    pods: list[str] = []
    monkeypatch.setattr(builds, "load_cluster_config", lambda: None)
    monkeypatch.setattr(
        builds, "build_push_image_using_kaniko", lambda deployment_file_location: None
    )
    monkeypatch.setattr(
        builds,
        "delete_pod",
        lambda name, namespace, missing_ok=False: pods.append(name),
    )
    with api.application.app_context():
        settings = endpoints()["builds"]
    monkeypatch.setitem(settings, "enabled", True)
    monkeypatch.setitem(
        settings, "intermediate_registery_format", "registry.example.org/{}"
    )
    repository = check(
        api.post(
            "/repositories",
            json={"url": "https://github.com/elixir-cloud-aai/drs-filer"},
        )
    )
    headers = {"X-Project-Access-Token": repository["access_token"]}
    build = check(
        api.post(
            f"/repositories/{repository['id']}/builds",
            headers=headers,
            json={
                "images": [{"name": "org/image:1", "location": "Dockerfile"}],
                "head_commit": {"tag": drs_filer.tag},
                "dockerhub_token": "dXNlcjpwYXNzd2Q=",  # user:passwd  gitleaks:allow
            },
        )
    )
    assert [path.name for path in builds_dir.iterdir()] == [build["id"]]
    check(api.delete(f"/repositories/{repository['id']}", headers=headers))
    assert pods == [build["id"]]
    assert list(builds_dir.iterdir()) == []
    check(
        api.put(
            f"/repositories/{repository['id']}/builds/{build['id']}",
            headers=headers,
            json={"id": build["id"]},
        ),
        404,
    )


def test_cancel_build(api: FlaskClient, subscriber: Subscriber) -> None:
    """Withdrawing a build marks it as canceled and keeps it listed.

    Only the repository's own access token allows it. A repeated request
    gets a 409, an unknown build a 404; deployments are not notified again.
    """
    user = register_user(api)
    repository = register_repository(api)
    other = register_repository(api)
    subscribe(api, user, repository["id"], subscriber.url, value="*")
    publish(api, repository, "1")
    path = f"/repositories/{repository['id']}/builds"
    headers = {"X-Project-Access-Token": repository["access_token"]}
    [build] = check(api.get(path))
    assert build["status"] == "SUCCEEDED"
    check(
        api.delete(f"{path}/{build['id']}", headers={"X-Project-Access-Token": "x"}),
        401,
    )
    check(
        api.delete(
            f"{path}/{build['id']}",
            headers={"X-Project-Access-Token": other["access_token"]},
        ),
        401,
    )
    assert check(api.delete(f"{path}/{build['id']}", headers=headers)) == {
        "id": build["id"]
    }
    listed = check(api.get(path))
    assert listed == [{**build, "status": "CANCELED"}]
    canceled = check(api.get(f"{path}/{build['id']}"))
    assert canceled["status"] == "CANCELED"
    error = check(api.delete(f"{path}/{build['id']}", headers=headers), 409)
    assert error == {
        "title": "Conflict",
        "status": 409,
        "detail": exceptions[BuildCanceled]["detail"],
    }
    check(api.delete(f"{path}/unknown", headers=headers), 404)
    check(
        api.delete(f"/repositories/unknown/builds/{build['id']}", headers=headers),
        404,
    )
    assert len(subscriber.received) == 1


def test_cancel_running_build(
    api: FlaskClient,
    drs_filer: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With builds switched on, withdrawing a running build stops it.

    The build's pod is deleted and its files are removed; the report of the
    finished pod then gets a 409, and the build stays canceled. Kubernetes
    is replaced by mocks; Git clones from a local copy (fixture
    `drs_filer`).

    Args:
        api: Client of the API.
        drs_filer: Local copy of the repository `drs-filer`.
        tmp_path: Temporary directory for the builds' files.
        monkeypatch: Pytest's monkeypatch fixture.
    """
    builds_dir = tmp_path / "builds"
    builds_dir.mkdir()
    monkeypatch.setattr(builds, "BASE_DIR", str(builds_dir))
    monkeypatch.setattr(
        builds,
        "template_file",
        str(Path(builds.__file__).parent / "kaniko" / "template.yaml"),
    )
    pods: list[str] = []
    monkeypatch.setattr(builds, "load_cluster_config", lambda: None)
    monkeypatch.setattr(
        builds, "build_push_image_using_kaniko", lambda deployment_file_location: None
    )
    monkeypatch.setattr(
        builds,
        "delete_pod",
        lambda name, namespace, missing_ok=False: pods.append(name),
    )
    signed: list[str] = []
    monkeypatch.setattr(
        builds, "trigger_signing_image", lambda **kwargs: signed.append("signed")
    )
    with api.application.app_context():
        settings = endpoints()["builds"]
    monkeypatch.setitem(settings, "enabled", True)
    monkeypatch.setitem(
        settings, "intermediate_registery_format", "registry.example.org/{}"
    )
    repository = check(
        api.post(
            "/repositories",
            json={"url": "https://github.com/elixir-cloud-aai/drs-filer"},
        )
    )
    headers = {"X-Project-Access-Token": repository["access_token"]}
    path = f"/repositories/{repository['id']}/builds"
    build = check(
        api.post(
            path,
            headers=headers,
            json={
                "images": [{"name": "org/image:1", "location": "Dockerfile"}],
                "head_commit": {"tag": drs_filer.tag},
                "dockerhub_token": "dXNlcjpwYXNzd2Q=",  # user:passwd  gitleaks:allow
            },
        )
    )
    assert [path.name for path in builds_dir.iterdir()] == [build["id"]]
    check(api.delete(f"{path}/{build['id']}", headers=headers))
    assert pods == [build["id"]]
    assert list(builds_dir.iterdir()) == []
    check(
        api.put(f"{path}/{build['id']}", headers=headers, json={"id": build["id"]}),
        409,
    )
    assert signed == []
    stored = check(api.get(f"{path}/{build['id']}"))
    assert stored["status"] == "CANCELED"
    assert stored["finished_at"] is not None
    assert [item["id"] for item in check(api.get(path))] == [build["id"]]


@pytest.mark.parametrize(
    "image_name",
    [
        "harbor.example.org/project/image",
        "registry.example.org:8443/group/sub/image",
        "localhost:5000/image",
    ],
)
def test_publish_image_of_any_registry(
    api: FlaskClient, subscriber: Subscriber, image_name: str
) -> None:
    """Prebuilt images of any registry are published with their host."""
    user = register_user(api)
    repository = register_repository(api)
    subscribe(api, user, repository["id"], subscriber.url)
    check(
        api.post(
            f"/repositories/{repository['id']}/builds",
            headers={"X-Project-Access-Token": repository["access_token"]},
            json={
                "images": [{"name": f"{image_name}:1"}],
                "head_commit": {"tag": "1"},
            },
        )
    )
    assert [item["body"] for item in subscriber.received] == [
        {"image_name": image_name, "tag": "1"}
    ]
