"""Tests of the version check of releases (`scripts/check_versions.py`)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_versions.py"

# `scripts/` is not a package, so the script is loaded from its file
_spec = importlib.util.spec_from_file_location("check_versions", SCRIPT)
assert _spec and _spec.loader
check_versions = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check_versions
_spec.loader.exec_module(check_versions)

PYPROJECT = """\
[project]
name = "pubgrade"
# Set by the release-prep pull request
version = "{version}"

[tool.uv]
package = false
"""

CHART = """\
apiVersion: v2
name: pubgrade
# Set by the release-prep pull request
version: {chart_version}
appVersion: "{version}"  # the default image tag
"""


def _repo(tmp_path: Path, version: str, chart_version: str, app: str) -> Path:
    """Return a repository with the given versions.

    Args:
        tmp_path: Directory to write the files to.
        version: Version of the app (`[project]` of `pyproject.toml`).
        chart_version: `version` of the chart.
        app: `appVersion` of the chart.

    Returns:
        The root of the repository.
    """
    (tmp_path / "helm").mkdir()
    (tmp_path / "pyproject.toml").write_text(PYPROJECT.format(version=version))
    (tmp_path / "helm/Chart.yaml").write_text(
        CHART.format(chart_version=chart_version, version=app)
    )
    return tmp_path


def test_repository_has_versions() -> None:
    """The repository's own files have the versions the release checks.

    The chart's `version` matches only after the release-prep pull request
    (see "Versioning and releases" in `docs/development.md`).
    """
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    chart = (ROOT / "helm/Chart.yaml").read_text(encoding="utf-8")
    version = check_versions.project_version(pyproject)
    assert version is not None
    assert check_versions.chart_value(chart, "appVersion") == version
    assert check_versions.chart_value(chart, "version") is not None


def test_project_version() -> None:
    """`version` in `[project]`, not in other tables."""
    text = PYPROJECT.format(version="1.2.3")
    assert check_versions.project_version(text) == "1.2.3"
    assert check_versions.project_version('[tool.x]\nversion = "9"\n') is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[project]\nname = 'x'\n",
        "[project]\nversion = 1\n",
        "project = 1\n",
        "[project\n",
    ],
)
def test_project_version_missing(text: str) -> None:
    """Only a string `version` in `[project]` counts.

    Args:
        text: Content of `pyproject.toml`.
    """
    assert check_versions.project_version(text) is None


def test_chart_value() -> None:
    """Plain and quoted values, with comments."""
    text = CHART.format(chart_version="1.2.3-rc1", version="1.2.3rc1")
    assert check_versions.chart_value(text, "version") == "1.2.3-rc1"
    assert check_versions.chart_value(text, "appVersion") == "1.2.3rc1"
    assert check_versions.chart_value(text, "kubeVersion") is None


def test_main_match(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Matching versions pass."""
    root = _repo(tmp_path, "1.2.3rc1", "1.2.3-rc1", "1.2.3rc1")
    assert check_versions.main(["1.2.3rc1", "1.2.3-rc1"], root) == 0
    assert capsys.readouterr().err == ""


def test_main_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Each mismatch is reported as an error annotation."""
    root = _repo(tmp_path, "1.2.2", "1.2.3", "1.2.4")
    assert check_versions.main(["1.2.3", "1.2.3"], root) == 1
    err = capsys.readouterr().err
    assert "::error::pyproject.toml: [project] version is '1.2.2'" in err
    assert "::error::helm/Chart.yaml: appVersion is '1.2.4'" in err
    assert "Chart.yaml: version" not in err
