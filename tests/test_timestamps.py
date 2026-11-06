"""Tests for the timestamps of stored objects."""

import datetime

import mongomock

from pubgrade.timestamps import now, repair_timestamps


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
