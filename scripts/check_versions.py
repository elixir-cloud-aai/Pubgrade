"""Check that the app and the chart have the version of a release.

The release workflow (`.github/workflows/release.yml`) releases the images
and the chart together, with one version: the tag `vX.Y.Z` must match
`__version__` in `pubgrade/__init__.py` and `appVersion` in `helm/Chart.yaml`,
and the chart's `version` must be the SemVer form of it (e.g., `1.2.3-rc1` for
`1.2.3rc1`). The release-prep pull request sets them (see "Versioning and
releases" in `docs/development.md`). Errors are printed as GitHub annotations
to standard error.

Usage:
    `check_versions.py <version> <chart_version>`, as `release_version.py
    outputs` derives them from the tag.

Only the stdlib is used, so the workflow runs it without installing the app.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

# `__version__ = "..."` (or with single quotes) at the start of a line
APP_VERSION = re.compile(
    r"^__version__[ \t]*=[ \t]*(?P<quote>[\"'])(?P<value>[^\"'\n]*)(?P=quote)",
    re.M,
)


def _chart_key(name: str) -> re.Pattern[str]:
    """Return the pattern of a top-level key of `Chart.yaml`.

    Args:
        name: Name of the key.

    Returns:
        The pattern of a line with the key and a plain or quoted value, and
        optionally a comment; group `value` is the value without quotes.
    """
    return re.compile(
        rf"^{re.escape(name)}:[ \t]*(?P<quote>[\"']?)(?P<value>[0-9A-Za-z._+-]+)"
        r"(?P=quote)[ \t]*(?:#.*)?$",
        re.M,
    )


def app_version(text: str) -> str | None:
    """Return the version of the app (`__version__`).

    Args:
        text: Content of `pubgrade/__init__.py`.

    Returns:
        The version, or `None` if there is none.
    """
    version = APP_VERSION.search(text)
    return version["value"] if version else None


def chart_value(text: str, name: str) -> str | None:
    """Return the value of a top-level key of `Chart.yaml`.

    Args:
        text: Content of `Chart.yaml`.
        name: Name of the key, e.g., `version`.

    Returns:
        The value, or `None` if there is none.
    """
    match = _chart_key(name).search(text)
    return match["value"] if match else None


def check(version: str, chart_version: str, root: Path = ROOT) -> list[str]:
    """Return the mismatches between the release and the repository.

    Args:
        version: Version of the release, e.g., `1.2.3rc1`.
        chart_version: SemVer form of it, e.g., `1.2.3-rc1`.
        root: Root of the repository.

    Returns:
        One error message per mismatch; empty if all versions match.
    """
    app = (root / "pubgrade/__init__.py").read_text(encoding="utf-8")
    chart = (root / "helm/Chart.yaml").read_text(encoding="utf-8")
    expected = [
        ("pubgrade/__init__.py", "__version__", app_version(app), version),
        ("helm/Chart.yaml", "version", chart_value(chart, "version"), chart_version),
        ("helm/Chart.yaml", "appVersion", chart_value(chart, "appVersion"), version),
    ]
    return [
        f"{file}: {key} is '{actual}', expected '{wanted}'"
        for file, key, actual, wanted in expected
        if actual != wanted
    ]


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """Check the versions (see the module's docstring).

    Args:
        argv: Command-line arguments, without the program name; those of the
            process if `None`.
        root: Root of the repository.

    Returns:
        The exit status: 0 if all versions match, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Check that the app and the chart have the release version."
    )
    parser.add_argument("version", help="release version, e.g., 1.2.3rc1")
    parser.add_argument("chart_version", help="chart version, e.g., 1.2.3-rc1")
    args = parser.parse_args(argv)
    errors = check(args.version, args.chart_version, root)
    for error in errors:
        print(f"::error::{error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
