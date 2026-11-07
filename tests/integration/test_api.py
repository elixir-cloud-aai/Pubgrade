"""Integration tests of the API: register, publish and notify."""

import socket
from typing import Any

from flask.testing import FlaskClient
import pytest

from pubgrade.settings import collection
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
