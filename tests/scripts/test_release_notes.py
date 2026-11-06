"""Tests of the notes of first releases (`scripts/release_notes.py`)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release_notes.py"

# `scripts/` is not a package, so the script is loaded from its file
_spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
assert _spec and _spec.loader
release_notes = importlib.util.module_from_spec(_spec)
# Registered first, as dataclasses look up their module in `sys.modules`
sys.modules[_spec.name] = release_notes
_spec.loader.exec_module(release_notes)


def _pull(
    number: int,
    merged_at: str | None,
    author: str | None = "a",
    sha: str | None = None,
) -> dict[str, object]:
    """Return a closed pull request as the API lists it.

    Args:
        number: Number of the pull request.
        merged_at: When it was merged; `None` if it was closed unmerged.
        author: Login of its author; `None` for a deleted account.
        sha: SHA of its merge commit (default: `c<number>`).

    Returns:
        The pull request, with the fields the notes use.
    """
    return {
        "number": number,
        "title": f" PR {number} ",
        "user": None if author is None else {"login": author},
        "html_url": f"https://github.com/o/r/pull/{number}",
        "merged_at": merged_at,
        "merge_commit_sha": f"c{number}" if sha is None else sha,
    }


def test_first_release_notes() -> None:
    """All merged pull requests of the history are listed, in merge order."""
    pages = [
        [
            _pull(3, "2026-01-03T00:00:00Z", "b"),
            _pull(1, "2026-01-01T00:00:00Z", "a"),
            # Closed without merging
            _pull(5, None, "d"),
        ],
        [
            _pull(2, "2026-01-02T00:00:00Z", "a"),
            # Merged elsewhere, not in the history of the release; its author
            # contributed first with it, so `c` is no new contributor
            _pull(4, "2026-01-01T12:00:00Z", "c", sha="other"),
            _pull(6, "2026-01-04T00:00:00Z", "c"),
            _pull(7, "2026-01-04T00:00:00Z", None),
            # Merged, but without a merge commit
            {**_pull(8, "2026-01-05T00:00:00Z", "e"), "merge_commit_sha": None},
            # Repeated on the next page (listed once)
            _pull(3, "2026-01-03T00:00:00Z", "b"),
        ],
    ]
    pulls = release_notes.merged_pull_requests(pages)
    commits = ["c1", "c2", "c3", "c6", "c7", "c8"]
    notes = release_notes.first_release_notes("v1.0.0", "o/r", pulls, commits)
    assert notes == (
        "## What's Changed\n"
        "* PR 1 by @a in https://github.com/o/r/pull/1\n"
        "* PR 2 by @a in https://github.com/o/r/pull/2\n"
        "* PR 3 by @b in https://github.com/o/r/pull/3\n"
        "* PR 6 by @c in https://github.com/o/r/pull/6\n"
        "* PR 7 by @ghost in https://github.com/o/r/pull/7\n"
        "\n"
        "## New Contributors\n"
        "* @a made their first contribution in https://github.com/o/r/pull/1\n"
        "* @b made their first contribution in https://github.com/o/r/pull/3\n"
        "* @ghost made their first contribution in https://github.com/o/r/pull/7\n"
        "\n"
        "**Full Changelog**: https://github.com/o/r/commits/v1.0.0\n"
    )


def test_first_release_notes_without_pull_requests() -> None:
    """Without merged pull requests, only the changelog line is left."""
    notes = release_notes.first_release_notes("v1.0.0", "o/r", [], ["c1"])
    assert notes == "**Full Changelog**: https://github.com/o/r/commits/v1.0.0\n"


def test_first_release_notes_no_new_contributors() -> None:
    """Without first contributions, there is no "New Contributors" section."""
    pulls = release_notes.merged_pull_requests(
        [[_pull(1, "2026-01-01T00:00:00Z", sha="x"), _pull(2, "2026-01-02T00:00:00Z")]]
    )
    notes = release_notes.first_release_notes("v1.0.0", "o/r", pulls, ["c2"])
    assert notes == (
        "## What's Changed\n* PR 2 by @a in https://github.com/o/r/pull/2\n\n"
        "**Full Changelog**: https://github.com/o/r/commits/v1.0.0\n"
    )


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        ({}, "not a list of pages"),
        ([{}], "not a list of pages"),
        ([["x"]], "not an object"),
        ([[{**_pull(1, "2026-01-01T00:00:00Z"), "number": "1"}]], "'number'"),
        ([[{**_pull(1, "2026-01-01T00:00:00Z"), "number": True}]], "'number'"),
        ([[{**_pull(1, "2026-01-01T00:00:00Z"), "title": None}]], "'title'"),
        (
            [[{**_pull(1, "2026-01-01T00:00:00Z"), "merge_commit_sha": ""}]],
            "'merge_commit_sha'",
        ),
        ([[{**_pull(1, "2026-01-01T00:00:00Z"), "merged_at": 1}]], "'merged_at'"),
    ],
)
def test_merged_pull_requests_invalid(pages: object, message: str) -> None:
    """Pages that aren't lists of pull requests with the fields are errors.

    Args:
        pages: Pages of pull requests.
        message: Part of the expected error message.
    """
    with pytest.raises(ValueError, match=message):
        release_notes.merged_pull_requests(pages)


def test_main_first(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`first` prints the notes of a first release."""
    pulls = tmp_path / "pulls.json"
    pulls.write_text(json.dumps([[_pull(1, "2026-01-01T00:00:00Z")]]), encoding="utf-8")
    commits = tmp_path / "commits"
    commits.write_text("c1\nc0\n\n", encoding="utf-8")
    argv = ["first", "v1.0.0", "--repository", "o/r"]
    assert (
        release_notes.main([*argv, "--pulls", str(pulls), "--commits", str(commits)])
        == 0
    )
    assert capsys.readouterr().out == (
        "## What's Changed\n"
        "* PR 1 by @a in https://github.com/o/r/pull/1\n"
        "\n"
        "## New Contributors\n"
        "* @a made their first contribution in https://github.com/o/r/pull/1\n"
        "\n"
        "**Full Changelog**: https://github.com/o/r/commits/v1.0.0\n"
    )


@pytest.mark.parametrize("content", ["not json", "[{}]", b"\xff", None])
def test_main_first_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str | bytes | None
) -> None:
    """Unreadable or invalid pull requests fail the command.

    Args:
        tmp_path: Temporary directory.
        capsys: Captured output.
        content: Content of the file of pull requests (bytes: not UTF-8);
            `None` if missing.
    """
    pulls = tmp_path / "pulls.json"
    if isinstance(content, bytes):
        pulls.write_bytes(content)
    elif content is not None:
        pulls.write_text(content, encoding="utf-8")
    commits = tmp_path / "commits"
    commits.write_text("c1\n", encoding="utf-8")
    argv = ["first", "v1.0.0", "--repository", "o/r", "--pulls", str(pulls)]
    assert release_notes.main([*argv, "--commits", str(commits)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("::error::Can't list the pull requests: ")


def test_first_release_notes_title_on_one_line() -> None:
    """Titles stay on their line, also with line breaks or separators."""
    pull = {**_pull(1, "2026-01-01T00:00:00Z"), "title": "x\u2028## Security\n* y"}
    pulls = release_notes.merged_pull_requests([[pull]])
    notes = release_notes.first_release_notes("v1.0.0", "o/r", pulls, ["c1"])
    assert "* x ## Security * y by @a in https://github.com/o/r/pull/1\n" in notes
