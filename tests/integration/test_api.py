"""Integration tests of the API: register, publish and notify."""

from typing import Any

from flask.testing import FlaskClient

from tests.integration.conftest import ADMIN, Subscriber

ADMIN_HEADERS = {
    "X-Super-User-Id": ADMIN["uid"],
    "X-Super-User-Access-Token": ADMIN["user_access_token"],
}


def register_user(api: FlaskClient) -> dict[str, str]:
    """Register a user and have the admin verify them.

    Args:
        api: Client of the API.

    Returns:
        Headers that authenticate the user.
    """
    response = api.post("/users/register", json={"name": "Deployer"})
    assert response.status_code == 200, response.json
    user = response.json
    assert user is not None
    response = api.put(f"/users/{user['uid']}/verify", headers=ADMIN_HEADERS)
    assert response.status_code == 200, response.json
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
    response = api.post(
        "/repositories", json={"url": "https://github.com/elixir-cloud-aai/app.git"}
    )
    assert response.status_code == 200, response.json
    repository: dict[str, str] = response.json or {}
    return repository


def subscribe(
    api: FlaskClient,
    user: dict[str, str],
    repository_id: str,
    callback_url: str,
    value: str = "1",
) -> str:
    """Subscribe to the tags of a repository.

    Args:
        api: Client of the API.
        user: Headers that authenticate the user.
        repository_id: Identifier of the repository.
        callback_url: URL to notify.
        value: Tag to subscribe to (`*` for all).

    Returns:
        Identifier of the subscription.
    """
    response = api.post(
        "/subscriptions",
        headers=user,
        json={
            "repository_id": repository_id,
            "callback_url": callback_url,
            "access_token": "subscriber-token",
            "type": "tag",
            "value": value,
        },
    )
    assert response.status_code == 200, response.json
    subscription_id: str = (response.json or {})["subscription_id"]
    return subscription_id


def publish(api: FlaskClient, repository: dict[str, str], tag: str) -> dict[str, Any]:
    """Publish a prebuilt image and get the build.

    Args:
        api: Client of the API.
        repository: Identifier and access token of the repository.
        tag: Tag of the image and of the commit.

    Returns:
        The build, as the API returns it.
    """
    response = api.post(
        f"/repositories/{repository['id']}/builds",
        headers={"X-Project-Access-Token": repository["access_token"]},
        json={"images": [{"name": f"org/image:{tag}"}], "head_commit": {"tag": tag}},
    )
    assert response.status_code == 200, response.json
    build_id = (response.json or {})["id"]
    response = api.get(f"/repositories/{repository['id']}/builds/{build_id}")
    assert response.status_code == 200, response.json
    build: dict[str, Any] = response.json or {}
    return build


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
            "body": {"image_name": "org/image", "tag": "1"},
        }
    ]
    assert build["status"] == "SUCCEEDED"
    results = {
        result["subscription_id"]: (result["result"], result["http_status"])
        for result in build["notifications"]
    }
    assert results == {matching: ("delivered", 200), other: ("skipped", None)}
    response = api.get(f"/subscriptions/{matching}", headers=user)
    assert response.status_code == 200, response.json
    assert (response.json or {})["state"] == "Active"
    response = api.get("/subscriptions", headers=user)
    assert response.status_code == 200, response.json
    assert sorted(item["subscription_id"] for item in response.json or []) == sorted(
        [matching, other]
    )


def test_publish_with_failed_notification(
    api: FlaskClient, subscriber: Subscriber
) -> None:
    """A subscriber that answers with an error fails the build."""
    subscriber.status = 500
    user = register_user(api)
    repository = register_repository(api)
    subscription = subscribe(api, user, repository["id"], subscriber.url, value="*")

    build = publish(api, repository, "3")

    assert len(subscriber.received) == 1
    assert build["status"] == "FAILED"
    assert [
        (result["subscription_id"], result["result"], result["http_status"])
        for result in build["notifications"]
    ] == [(subscription, "failed", 500)]
    response = api.get(f"/subscriptions/{subscription}", headers=user)
    assert (response.json or {})["state"] == "Inactive"


def test_unverified_user_cannot_subscribe(
    api: FlaskClient, subscriber: Subscriber
) -> None:
    """Users need to be verified by an admin before they can subscribe."""
    response = api.post("/users/register", json={"name": "Deployer"})
    user = response.json or {}
    repository = register_repository(api)
    response = api.post(
        "/subscriptions",
        headers={
            "X-User-Id": user["uid"],
            "X-User-Access-Token": user["user_access_token"],
        },
        json={
            "repository_id": repository["id"],
            "callback_url": subscriber.url,
            "access_token": "subscriber-token",
            "type": "tag",
            "value": "1",
        },
    )
    assert response.status_code == 403, response.json


def test_publish_needs_repository_token(api: FlaskClient) -> None:
    """Only the repository's access token allows publishing."""
    repository = register_repository(api)
    response = api.post(
        f"/repositories/{repository['id']}/builds",
        headers={"X-Project-Access-Token": "wrong"},
        json={"images": [{"name": "org/image:1"}], "head_commit": {"tag": "1"}},
    )
    assert response.status_code == 401, response.json
    response = api.get(f"/repositories/{repository['id']}/builds")
    assert response.status_code == 404, response.json


def test_repositories_hide_tokens(api: FlaskClient) -> None:
    """Listed and retrieved repositories don't show their access tokens."""
    repository = register_repository(api)
    response = api.get("/repositories")
    assert response.status_code == 200, response.json
    listed: list[dict[str, Any]] = response.json or []
    assert [item["id"] for item in listed] == [repository["id"]]
    response = api.get(f"/repositories/{repository['id']}")
    assert response.status_code == 200, response.json
    for item in [*listed, response.json or {}]:
        assert "access_token" not in item
