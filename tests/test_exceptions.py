"""Tests for the problem details of exceptions (`exceptions.mapping`)."""

import inspect
from typing import Type

import pytest
from werkzeug.exceptions import HTTPException

from pubgrade.errors import exceptions as module
from pubgrade.errors.exceptions import exceptions

OWN_HTTP_EXCEPTIONS = [
    cls
    for _, cls in inspect.getmembers(module, inspect.isclass)
    if issubclass(cls, HTTPException) and cls.__module__ == module.__name__
]


def _problem(cls: Type[BaseException]) -> dict:
    """Get the problem details FOCA uses for an exception.

    Args:
        cls: Exception class.

    Returns:
        The entry of its class or of its closest listed base class.
    """
    for base in cls.__mro__:
        if base in exceptions:
            return exceptions[base]
    raise AssertionError(f"No problem details for {cls.__name__}")


def test_problem_details_complete() -> None:
    """Each entry has a title, an integer status and a detail."""
    for cls, problem in exceptions.items():
        assert set(problem) == {"title", "status", "detail"}, cls
        assert isinstance(problem["status"], int), cls
        assert problem["detail"].endswith("."), cls


@pytest.mark.parametrize(
    "cls", OWN_HTTP_EXCEPTIONS, ids=lambda cls: cls.__name__
)
def test_status_matches_exception(cls: Type[HTTPException]) -> None:
    """Responses have the status of the exception that was raised."""
    assert _problem(cls)["status"] == cls.code
