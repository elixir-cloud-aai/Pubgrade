"""Shared test fixtures."""

import copy
from typing import Dict, Iterator

import pytest

from tests import mock_data


@pytest.fixture(autouse=True)
def restore_mock_data() -> Iterator[None]:
    """Restore the shared mock data after each test.

    Inserting a dictionary into a collection adds an `_id`, and some tests
    change the dictionaries directly. Without this, tests depend on the ones
    that ran before them. Dictionaries are restored in place, as tests import
    them by name.

    Yields:
        Nothing; the test runs at this point.
    """
    originals: Dict[str, dict] = {
        name: copy.deepcopy(value)
        for name, value in vars(mock_data).items()
        if name.isupper() and isinstance(value, dict)
    }
    yield
    for name, original in originals.items():
        current = getattr(mock_data, name)
        current.clear()
        current.update(original)
