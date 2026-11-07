"""Build the generated notes of a first release, in GitHub's format.

GitHub's `generate-notes` API, without a previous tag, starts at an older tag
of its own choice, whether it has a release or not (e.g., the tag of a
release attempt that failed), so the release workflow
(`.github/workflows/release.yml`) builds the generated notes of a release
without a published one before it with this script instead. Ported from the
`first` command of cloud-registry's `scripts/release_notes.py`; the curated
notes of cloud-registry are not used here (see "Versioning and releases" in
`docs/development.md`).

Command:
    `first <tag> --repository <owner/repo> --pulls <file> --commits <file>`:
        print generated notes of a first release (no published release
        before it) in GitHub's format, listing all merged pull requests in
        the history of the release commit (see `first_release_notes`), from
        the closed pull requests of the API (`gh api --paginate --slurp`)
        and the commits of the release (`git rev-list`, one SHA per line).

Errors are printed as GitHub annotations to standard error. Only the stdlib
is used, so the workflow runs it without installing the app.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import sys

# Header of GitHub's generated list of changes
WHATS_CHANGED = "## What's Changed"

# Start of GitHub's generated last line
FULL_CHANGELOG = "**Full Changelog**"


@dataclass(frozen=True)
class PullRequest:
    """A merged pull request, as GitHub's generated notes list it.

    Attributes:
        number: Number of the pull request.
        title: Title of the pull request.
        author: Login of its author (`ghost` for deleted accounts).
        url: URL of the pull request on GitHub.
        merged_at: When it was merged (ISO 8601, UTC, as GitHub sends it).
        merge_commit: SHA of its merge (or squash or rebase) commit.
    """

    number: int
    title: str
    author: str
    url: str
    merged_at: str
    merge_commit: str


def _string(pull: dict[str, object], name: str) -> str:
    """Return a string field of a pull request of the API.

    Args:
        pull: Pull request, as the API returns it.
        name: Name of the field.

    Returns:
        The value of the field.

    Raises:
        ValueError: If the field is missing, empty or not a string.
    """
    value = pull.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Pull request without a valid '{name}': {pull!r:.200}")
    return value


def merged_pull_requests(pages: object) -> list[PullRequest]:
    """Return the merged pull requests of the API's pages of pull requests.

    Args:
        pages: Pages of the API's list of closed pull requests (`gh api
            --paginate --slurp "repos/<owner>/<repo>/pulls?state=closed"`), a
            list of lists.

    Returns:
        The pull requests that were merged (`merged_at` set) and have a
        merge commit (`merge_commit_sha` set), in the order of the pages,
        each once (pages fetched while pull requests are closed may repeat
        one).

    Raises:
        ValueError: If the pages are not lists of pull requests with the
            fields that the notes need.
    """
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise ValueError("Pull requests are not a list of pages (lists)")
    merged: dict[int, PullRequest] = {}
    for pull in (pull for page in pages for pull in page):
        if not isinstance(pull, dict):
            raise ValueError(f"Pull request is not an object: {pull!r:.200}")
        # Pull requests without a merge commit (not merged, or with no
        # commit left, e.g., after a force-push) can't be in the history
        if pull.get("merged_at") is None or pull.get("merge_commit_sha") is None:
            continue
        user = pull.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        number = pull.get("number")
        # `bool` is an `int`, but no number of a pull request
        if not isinstance(number, int) or isinstance(number, bool):
            raise ValueError(f"Pull request without a valid 'number': {pull!r:.200}")
        merged.setdefault(
            number,
            PullRequest(
                number=number,
                # On one line, also with line breaks or other whitespace
                title=" ".join(_string(pull, "title").split()),
                # Deleted accounts are shown as `ghost`
                author=login if isinstance(login, str) and login else "ghost",
                url=_string(pull, "html_url"),
                merged_at=_string(pull, "merged_at"),
                merge_commit=_string(pull, "merge_commit_sha"),
            ),
        )
    return list(merged.values())


def first_release_notes(
    tag: str, repository: str, pulls: Sequence[PullRequest], commits: Iterable[str]
) -> str:
    """Return generated notes of a first release, in GitHub's format.

    GitHub's `generate-notes` API, without a previous tag, starts at the
    latest older tag of its own choice, whether it has a release or not. The
    notes of a first release list all changes instead: the merged pull
    requests in the history of the release commit, in the order they were
    merged, then the "New Contributors" (authors whose first merged pull
    request is among them), then the `**Full Changelog**` line, as GitHub
    generates them without an older tag.

    Args:
        tag: Tag of the release, e.g., `v1.2.3`.
        repository: Repository on GitHub (`<owner>/<repo>`).
        pulls: Merged pull requests of the repository (all of them, so that
            first contributions are found).
        commits: SHAs of the commits in the history of the release commit
            (e.g., `git rev-list HEAD` at the release commit).

    Returns:
        The notes, as the `body` of a `generate-notes` response.
    """
    history = set(commits)
    ordered = sorted(pulls, key=lambda pull: (pull.merged_at, pull.number))
    first: dict[str, int] = {}
    for pull in ordered:
        first.setdefault(pull.author, pull.number)
    released = [pull for pull in ordered if pull.merge_commit in history]
    lines = []
    if released:
        lines.append(WHATS_CHANGED)
        lines += [
            f"* {pull.title} by @{pull.author} in {pull.url}" for pull in released
        ]
        new = [pull for pull in released if first[pull.author] == pull.number]
        if new:
            lines += ["", "## New Contributors"]
            lines += [
                f"* @{pull.author} made their first contribution in {pull.url}"
                for pull in new
            ]
        lines.append("")
    lines.append(f"{FULL_CHANGELOG}: https://github.com/{repository}/commits/{tag}")
    return "\n".join(lines) + "\n"


def _first(args: argparse.Namespace) -> int:
    """Print the generated notes of a first release (command `first`).

    Args:
        args: Parsed arguments of the command.

    Returns:
        The exit status: 0 on success, 1 if a file can't be read or the pull
        requests are invalid.
    """
    try:
        pages = json.loads(args.pulls.read_text(encoding="utf-8"))
        commits = args.commits.read_text(encoding="utf-8").split()
        pulls = merged_pull_requests(pages)
    except (OSError, ValueError) as error:
        # `json.JSONDecodeError` and `UnicodeDecodeError` are `ValueError`s
        print(f"::error::Can't list the pull requests: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(first_release_notes(args.tag, args.repository, pulls, commits))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command (see the module's docstring).

    Args:
        argv: Command-line arguments, without the program name; those of the
            process if `None`.

    Returns:
        The exit status: 0 on success, 1 if a file can't be read or the pull
        requests are invalid.
    """
    parser = argparse.ArgumentParser(
        description="Print the generated notes of a first release."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    first_parser = commands.add_parser(
        "first", help="print generated notes of a first release"
    )
    first_parser.add_argument("tag", help="release tag, e.g., v1.2.3")
    first_parser.add_argument(
        "--repository", required=True, help="repository on GitHub (owner/repo)"
    )
    first_parser.add_argument(
        "--pulls", type=Path, required=True, help="pages of closed pull requests"
    )
    first_parser.add_argument(
        "--commits", type=Path, required=True, help="commits of the release"
    )
    args = parser.parse_args(argv)
    return _first(args)


if __name__ == "__main__":
    sys.exit(main())
