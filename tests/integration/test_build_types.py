"""Integration tests of build types: declared, published and subscribed to."""

from typing import Any

from flask.testing import FlaskClient
import pytest

from tests.integration.conftest import Subscriber
from tests.integration.test_api import check, register_user, results

TYPES = ["production", "testing"]


def register_repository(api: FlaskClient, **fields: Any) -> dict[str, str]:
    """Register a repository with further fields.

    Args:
        api: Client of the API.
        **fields: Further fields of the request, e.g., `build_types`.

    Returns:
        Its identifier (`id`) and access token (`access_token`).
    """
    repository: dict[str, str] = check(
        api.post(
            "/repositories",
            json={"url": "https://github.com/elixir-cloud-aai/app.git", **fields},
        )
    )
    return repository


def subscribe(
    api: FlaskClient,
    user: dict[str, str],
    repository_id: str,
    callback_url: str,
    status: int = 200,
    **fields: Any,
) -> Any:
    """Subscribe to all tags of a repository.

    Args:
        api: Client of the API.
        user: Headers that authenticate the user.
        repository_id: Identifier of the repository.
        callback_url: URL to notify.
        status: Expected status code.
        **fields: Further fields of the request, e.g., `build_types`.

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
                "value": "*",
                **fields,
            },
        ),
        status,
    )
    return body["subscription_id"] if status == 200 else body


def publish(
    api: FlaskClient,
    repository: dict[str, str],
    status: int = 200,
    **fields: Any,
) -> Any:
    """Publish a prebuilt image and get the build.

    Args:
        api: Client of the API.
        repository: Identifier and access token of the repository.
        status: Expected status code.
        **fields: Further fields of the request, e.g., `build_type`.

    Returns:
        The build, as the API returns it, or the error for other statuses
        than 200.
    """
    body = check(
        api.post(
            f"/repositories/{repository['id']}/builds",
            headers={"X-Project-Access-Token": repository["access_token"]},
            json={
                "images": [{"name": "org/image:1"}],
                "head_commit": {"tag": "1"},
                **fields,
            },
        ),
        status,
    )
    if status != 200:
        return body
    return check(api.get(f"/repositories/{repository['id']}/builds/{body['id']}"))


def test_subscriptions_filter_build_types(
    api: FlaskClient, subscriber: Subscriber
) -> None:
    """Subscriptions with build types get only builds of these types."""
    user = register_user(api)
    repository = register_repository(api, build_types=TYPES)
    listed = check(api.get(f"/repositories/{repository['id']}"))
    assert listed["build_types"] == TYPES
    production = subscribe(
        api, user, repository["id"], subscriber.url, build_types=["production"]
    )
    everything = subscribe(api, user, repository["id"], subscriber.url)
    empty = subscribe(api, user, repository["id"], subscriber.url, build_types=[])
    stored = check(api.get(f"/subscriptions/{production}", headers=user))
    assert stored["build_types"] == ["production"]

    build = publish(api, repository, build_type="production")
    assert build["build_type"] == "production"
    assert results(build) == {
        production: ("delivered", 200),
        everything: ("delivered", 200),
        empty: ("delivered", 200),
    }

    build = publish(api, repository, build_type="testing")
    assert results(build) == {
        production: ("skipped", None),
        everything: ("delivered", 200),
        empty: ("delivered", 200),
    }

    # Untyped builds don't match subscriptions with a filter
    build = publish(api, repository)
    assert "build_type" not in build
    assert results(build) == {
        production: ("skipped", None),
        everything: ("delivered", 200),
        empty: ("delivered", 200),
    }
    # All but the filtered subscription's two skips
    assert len(subscriber.received) == 3 * 3 - 2


def test_undeclared_build_types_rejected(
    api: FlaskClient, subscriber: Subscriber
) -> None:
    """Types that the repository doesn't declare get a 400."""
    user = register_user(api)
    typed = register_repository(api, build_types=TYPES)
    untyped = register_repository(api)
    for repository in (typed, untyped):
        error = subscribe(
            api,
            user,
            repository["id"],
            subscriber.url,
            status=400,
            build_types=["production", "staging"],
        )
        assert "build type" in error["detail"]
        error = publish(api, repository, status=400, build_type="staging")
        assert "build type" in error["detail"]
    assert subscriber.received == []
    # No build was kept
    check(api.get(f"/repositories/{typed['id']}/builds"), 404)


@pytest.mark.parametrize(
    "build_types",
    [["two words"], ["production", "production"], [""], ["a" * 65], "production"],
)
def test_invalid_build_types_rejected(api: FlaskClient, build_types: Any) -> None:
    """Build types are names without spaces, listed once."""
    check(
        api.post(
            "/repositories",
            json={"url": "https://example.org/app.git", "build_types": build_types},
        ),
        400,
    )


def test_modify_build_types(api: FlaskClient) -> None:
    """Changing a repository keeps its build types unless they are given."""
    repository = register_repository(api, build_types=TYPES)
    headers = {"X-Project-Access-Token": repository["access_token"]}
    url = f"/repositories/{repository['id']}"
    check(api.put(url, headers=headers, json={"url": "https://example.org/new.git"}))
    assert check(api.get(url))["build_types"] == TYPES
    check(
        api.put(
            url,
            headers=headers,
            json={"url": "https://example.org/new.git", "build_types": ["nightly"]},
        )
    )
    assert check(api.get(url))["build_types"] == ["nightly"]
    publish(api, repository, build_type="nightly")
    publish(api, repository, status=400, build_type="production")
