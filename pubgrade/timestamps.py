"""Timestamps of stored objects, in the format that the API declares.

The API declares timestamps as `date-time` (RFC 3339), which requires a time
zone; FOCA checks responses against it (`validate_responses`), so a
timestamp without one fails the whole response. Pubgrade before FOCA 0.21
stored them without a time zone (the local time of the container, i.e., UTC)
and stored `"NULL"` for builds that hadn't finished. `repair_timestamps()`
brings such stored values into the format at start; the endpoints also
return builds and subscriptions through `repaired_build()` and
`repaired_subscription()`, for objects that an instance of the old version
still writes during a rolling update.
"""

import datetime
import logging
import re
from typing import Any, Dict, List

from pymongo.collection import Collection

logger = logging.getLogger(__name__)

# A timestamp without time zone, as `datetime.isoformat()` writes it for
# naive datetimes
_NAIVE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$")
# Query for stored values that need repair
_OLD_VALUE = {"$in": ["NULL", _NAIVE]}


def now() -> str:
    """Get the current time as a timestamp of the API.

    Returns:
        The current time in UTC, in ISO 8601 format with time zone, e.g.,
        `2026-11-06T14:04:04.619000+00:00`.
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _repaired(value: Any) -> Any:
    """Bring a stored timestamp into the format of the API.

    Args:
        value: Stored value of a timestamp.

    Returns:
        A timestamp without time zone with UTC's (as the container's local
        time was UTC), `None` instead of `"NULL"`, and other values as they
        are.
    """
    if value == "NULL":
        return None
    if isinstance(value, str) and _NAIVE.match(value):
        return f"{value}+00:00"
    return value


def _repaired_fields(document: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
    """Get the repaired values of the fields that need repair.

    Args:
        document: Stored document.
        fields: Names of its timestamp fields.

    Returns:
        Repaired values, by field; empty if nothing needs repair.
    """
    repaired = {
        field: _repaired(document[field]) for field in fields if field in document
    }
    return {
        field: value
        for field, value in repaired.items()
        if value != document[field]
    }


def _repaired_notifications(
    notifications: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Bring the timestamps of the notifications of a build into the format.

    Args:
        notifications: Stored notifications of a build.

    Returns:
        The notifications, with repaired `finished_at`.
    """
    return [
        {**item, **_repaired_fields(item, ["finished_at"])} for item in notifications
    ]


def repaired_build(build: Dict[str, Any]) -> Dict[str, Any]:
    """Get a stored build with its timestamps in the format of the API.

    Args:
        build: Stored build.

    Returns:
        A copy of the build, with repaired timestamps.
    """
    repaired = {**build, **_repaired_fields(build, ["started_at", "finished_at"])}
    if build.get("notifications"):
        repaired["notifications"] = _repaired_notifications(build["notifications"])
    return repaired


def repaired_subscription(subscription: Dict[str, Any]) -> Dict[str, Any]:
    """Get a stored subscription with its timestamp in the format of the API.

    Args:
        subscription: Stored subscription.

    Returns:
        A copy of the subscription, with a repaired `updated_at`.
    """
    return {**subscription, **_repaired_fields(subscription, ["updated_at"])}


def repair_timestamps(
    builds: "Collection[Dict[str, Any]]",
    subscriptions: "Collection[Dict[str, Any]]",
) -> int:
    """Bring the stored timestamps of builds and subscriptions into the format.

    Runs at each start and reads only documents that need repair. Values
    that aren't timestamps without time zone stay as they are (their
    responses fail validation). Each update applies only while the stored
    values are still the ones read, so it doesn't overwrite a concurrent
    write, and concurrent runs are safe.

    Args:
        builds: Collection of builds (`started_at`, `finished_at` and
            `finished_at` of each notification).
        subscriptions: Collection of subscriptions (`updated_at`).

    Returns:
        Number of documents changed.
    """
    changed = 0
    fields = {"started_at": 1, "finished_at": 1, "notifications": 1}
    query = {
        "$or": [
            {"started_at": _OLD_VALUE},
            {"finished_at": _OLD_VALUE},
            {"notifications.finished_at": _OLD_VALUE},
        ]
    }
    for build in builds.find(query, fields):
        update = _repaired_fields(build, ["started_at", "finished_at"])
        notifications: List[Dict[str, Any]] = build.get("notifications") or []
        repaired = _repaired_notifications(notifications)
        if repaired != notifications:
            update["notifications"] = repaired
        stored = {field: build[field] for field in update}
        result = builds.update_one({"_id": build["_id"], **stored}, {"$set": update})
        changed += result.modified_count
    for subscription in subscriptions.find(
        {"updated_at": _OLD_VALUE}, {"updated_at": 1}
    ):
        result = subscriptions.update_one(
            {"_id": subscription["_id"], "updated_at": subscription["updated_at"]},
            {"$set": _repaired_fields(subscription, ["updated_at"])},
        )
        changed += result.modified_count
    if changed:
        logger.info(f"Timestamps of {changed} stored objects brought into format.")
    return changed
