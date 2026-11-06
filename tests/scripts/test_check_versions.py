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

INIT = """\
\"\"\"Pubgrade.\"\"\"

# Set by the release-prep pull request
__version__ = "{version}"
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
        version: Version of the app (`__version__`).
        chart_version: `version` of the chart.
        app: `appVersion` of the chart.

    Returns:
        The root of the repository.
    """
    (tmp_path / "helm").mkdir()
    (tmp_path / "pubgrade").mkdir()
    (tmp_path / "pubgrade/__init__.py").write_text(INIT.format(version=version))
    (tmp_path / "helm/Chart.yaml").write_text(
        CHART.format(chart_version=chart_version, version=app)
    )
    return tmp_path


def test_repository_versions_are_consistent() -> None:
    """The repository's own files have one version for app and chart."""
    app = (ROOT / "pubgrade/__init__.py").read_text(encoding="utf-8")
    chart = (ROOT / "helm/Chart.yaml").read_text(encoding="utf-8")
    version = check_versions.app_version(app)
    assert version is not None
    assert check_versions.chart_value(chart, "appVersion") == version
    assert check_versions.chart_value(chart, "version") is not None


def test_app_version() -> None:
    """`__version__` of the package, with either quotes."""
    assert check_versions.app_version(INIT.format(version="1.2.3")) == "1.2.3"
    assert check_versions.app_version("__version__ = '1.2.3'\n") == "1.2.3"


@pytest.mark.parametrize(
    "text", ['version = "1.0.0"\n', '    __version__ = "1.0.0"\n', ""]
)
def test_app_version_missing(text: str) -> None:
    """Only a top-level `__version__` counts."""
    assert check_versions.app_version(text) is None


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
    assert "::error::pubgrade/__init__.py: __version__ is '1.2.2'" in err
    assert "::error::helm/Chart.yaml: appVersion is '1.2.4'" in err
    assert "Chart.yaml: version" not in err
