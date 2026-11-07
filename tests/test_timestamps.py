"""Tests for the timestamps of stored objects."""

import datetime
from typing import Any

import mongomock

from pubgrade.timestamps import (
    now,
    repair_timestamps,
    repaired_build,
    repaired_subscription,
)


def test_now_has_time_zone() -> None:
    """Timestamps are in UTC, with the time zone, as `date-time` requires."""
    parsed = datetime.datetime.fromisoformat(now())
    assert parsed.utcoffset() == datetime.timedelta(0)


def test_repair_timestamps() -> None:
    """Stored timestamps without time zone get UTC's, and `"NULL"` is null."""
    client = mongomock.MongoClient()
    builds = client.db.builds
    subscriptions = client.db.subscriptions
    builds.insert_many(
        [
            {
                "id": "old",
                "started_at": "2026-01-02T03:04:05.123456",
                "finished_at": "NULL",
                "notifications": [
                    {"subscription_id": "s", "finished_at": "2026-01-02T03:04:06"},
                    {"subscription_id": "t"},
                ],
            },
            {
                "id": "new",
                "started_at": "2026-01-02T03:04:05+00:00",
                "finished_at": None,
            },
            {"id": "unknown", "started_at": "yesterday"},
            {
                "id": "zoned",
                "started_at": "2026-01-02T03:04:05Z",
                "finished_at": "2026-01-02T04:04:05.5+01:00",
                "status": "SUCCEEDED",
            },
        ]
    )
    subscriptions.insert_many(
        [
            {"id": "old", "updated_at": "2026-01-02T03:04:05"},
            {"id": "new", "updated_at": "2026-01-02T03:04:05+00:00"},
            {"id": "never"},
        ]
    )
    assert repair_timestamps(builds, subscriptions) == 2
    old = builds.find_one({"id": "old"})
    assert old["started_at"] == "2026-01-02T03:04:05.123456+00:00"
    assert old["finished_at"] is None
    assert old["notifications"] == [
        {"subscription_id": "s", "finished_at": "2026-01-02T03:04:06+00:00"},
        {"subscription_id": "t"},
    ]
    assert builds.find_one({"id": "new"})["started_at"].endswith("+00:00")
    assert builds.find_one({"id": "unknown"})["started_at"] == "yesterday"
    zoned = builds.find_one({"id": "zoned"}, {"_id": 0})
    assert zoned == {
        "id": "zoned",
        "started_at": "2026-01-02T03:04:05Z",
        "finished_at": "2026-01-02T04:04:05.5+01:00",
        "status": "SUCCEEDED",
    }
    assert (
        subscriptions.find_one({"id": "old"})["updated_at"]
        == "2026-01-02T03:04:05+00:00"
    )
    assert "updated_at" not in subscriptions.find_one({"id": "never"})
    # Nothing left to repair on the next start
    assert repair_timestamps(builds, subscriptions) == 0


class _WrittenMeanwhile:
    """A collection whose documents change between the repair's read and write.

    Stands in for an instance of the previous version that writes a build or
    subscription while the repair runs.
    """

    def __init__(self, collection: Any, change: dict[str, Any]) -> None:
        """Wrap a collection.

        Args:
            collection: The collection.
            change: Values set on all documents after the read.
        """
        self.collection = collection
        self.change = change

    def find(self, *args: Any) -> list[dict[str, Any]]:
        """Read documents, then let them change.

        Args:
            *args: Arguments of `find()`.

        Returns:
            The documents as read.
        """
        documents = list(self.collection.find(*args))
        self.collection.update_many({}, {"$set": self.change})
        return documents

    def update_one(self, *args: Any) -> Any:
        """Update a document.

        Args:
            *args: Arguments of `update_one()`.

        Returns:
            The result of the update.
        """
        return self.collection.update_one(*args)


def test_repair_keeps_concurrent_writes() -> None:
    """Values written after the repair read them are kept."""
    client = mongomock.MongoClient()
    builds = client.db.builds
    subscriptions = client.db.subscriptions
    builds.insert_one(
        {
            "id": "b",
            "started_at": "2026-01-02T03:04:05",
            "finished_at": "NULL",
            "notifications": [{"finished_at": "2026-01-02T03:04:06"}],
        }
    )
    subscriptions.insert_one({"id": "s", "updated_at": "2026-01-02T03:04:05"})
    finished = "2026-01-02T03:05:00+00:00"
    written = {
        "started_at": "2026-01-02T03:04:30+00:00",
        "finished_at": finished,
        "notifications": [{"finished_at": finished}, {"finished_at": finished}],
    }
    assert (
        repair_timestamps(
            _WrittenMeanwhile(builds, written),
            _WrittenMeanwhile(subscriptions, {"updated_at": finished}),
        )
        == 0
    )
    assert builds.find_one({"id": "b"}, {"_id": 0}) == {"id": "b", **written}
    assert subscriptions.find_one({"id": "s"})["updated_at"] == finished


def test_repaired_build_and_subscription() -> None:
    """Returned objects get repaired copies, without changing the stored."""
    build = {
        "started_at": "2026-01-02T03:04:05",
        "finished_at": "NULL",
        "notifications": [{"result": "delivered"}],
    }
    assert repaired_build(build) == {
        "started_at": "2026-01-02T03:04:05+00:00",
        "finished_at": None,
        "notifications": [{"result": "delivered"}],
    }
    assert build["finished_at"] == "NULL"
    assert repaired_build({"status": "RUNNING"}) == {"status": "RUNNING"}
    assert repaired_subscription({"updated_at": "2026-01-02T03:04:05"}) == {
        "updated_at": "2026-01-02T03:04:05+00:00"
    }
