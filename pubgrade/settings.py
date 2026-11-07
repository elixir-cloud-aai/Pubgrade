"""Access to the database and the app's own settings.

The settings under `endpoints` are an extra section of FOCA's configuration
(`pubgrade/config.yaml`), which FOCA keeps untyped.
"""

from typing import Any

from foca import get_collection, get_config
from pymongo.collection import Collection

# The database of the app (`db.dbs` in the configuration)
DB = "pubgradeStore"


def endpoints() -> dict[str, Any]:
    """Return the section `endpoints` of the configuration.

    Returns:
        The settings of the app's endpoints, by section.

    Raises:
        KeyError: The configuration has no section `endpoints`.
    """
    settings: dict[str, Any] = (get_config().model_extra or {})["endpoints"]
    return settings


def collection(name: str) -> Collection[dict[str, Any]]:
    """Return a collection of the app's database.

    Args:
        name: Name of the collection, e.g., `repositories`.

    Returns:
        The collection.
    """
    return get_collection(DB, name)
