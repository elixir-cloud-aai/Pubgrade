"""Timestamps of stored objects, in the format that the API declares.

The API declares timestamps as `date-time` (RFC 3339), which requires a time
zone; FOCA checks responses against it (`validate_responses`), so a
timestamp without one fails the whole response. Pubgrade before FOCA 0.21
stored them without a time zone (the local time of the container, i.e., UTC)
and stored `"NULL"` for builds that hadn't finished; `repair_timestamps()`
brings such stored values into the format.
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


def repair_timestamps(
    builds: "Collection[Dict[str, Any]]",
    subscriptions: "Collection[Dict[str, Any]]",
) -> int:
    """Bring the stored timestamps of builds and subscriptions into the format.

    Runs at each start; documents already in the format are left alone.

    Args:
        builds: Collection of builds (`started_at`, `finished_at` and
            `finished_at` of each notification).
        subscriptions: Collection of subscriptions (`updated_at`).

    Returns:
        Number of documents changed.
    """
    changed = 0
    fields = {"started_at": 1, "finished_at": 1, "notifications": 1}
    for build in builds.find({}, fields):
        update: Dict[str, Any] = {}
        for field in ("started_at", "finished_at"):
            if field in build and _repaired(build[field]) != build[field]:
                update[field] = _repaired(build[field])
        notifications: List[Dict[str, Any]] = build.get("notifications") or []
        repaired = [
            {**item, "finished_at": _repaired(item["finished_at"])}
            if "finished_at" in item
            else item
            for item in notifications
        ]
        if repaired != notifications:
            update["notifications"] = repaired
        if update:
            builds.update_one({"_id": build["_id"]}, {"$set": update})
            changed += 1
    for subscription in subscriptions.find({}, {"updated_at": 1}):
        value = subscription.get("updated_at")
        if _repaired(value) != value:
            subscriptions.update_one(
                {"_id": subscription["_id"]},
                {"$set": {"updated_at": _repaired(value)}},
            )
            changed += 1
    if changed:
        logger.info(f"Timestamps of {changed} stored objects brought into format.")
    return changed
