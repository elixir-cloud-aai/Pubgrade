"""Tests for the build-complete updater (`build-complete-updater/updater.py`)."""

import importlib.util
import json
import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

UPDATER = Path(__file__).parents[1] / "build-complete-updater" / "updater.py"


def load_updater(monkeypatch: pytest.MonkeyPatch, **env: str) -> ModuleType:
    """Import the updater with the given environment.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.
        **env: Environment variables to set; the updater's others are unset.

    Returns:
        The updater module.
    """
    for name in ("NAMESPACE", "BROKER_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("updater", UPDATER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def updater(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Get the updater, configured for a Pubgrade at `http://pubgrade`.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.

    Returns:
        The updater module.
    """
    return load_updater(monkeypatch, NAMESPACE="builds", BROKER_URL="http://pubgrade")


def make_pod(
    phase: str = "Succeeded",
    env: dict[str, str] | None = None,
    spec: bool = True,
    status: bool = True,
) -> Any:
    """Create a mock build pod.

    Args:
        phase: Phase of the pod.
        env: Environment of its container; `None` for none at all.
        spec: Whether the pod has a spec.
        status: Whether the pod has a status.

    Returns:
        The pod.
    """
    variables = (
        None
        if env is None
        else [SimpleNamespace(name=name, value=value) for name, value in env.items()]
    )
    container = SimpleNamespace(env=variables)
    return SimpleNamespace(
        spec=SimpleNamespace(containers=[container]) if spec else None,
        status=SimpleNamespace(phase=phase) if status else None,
    )


BUILD_ENV = {"BUILDNAME": "abcdefghijkl", "ACCESSTOKEN": "token"}


def test_settings_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without settings, the namespace is `broker` and there is no URL."""
    module = load_updater(monkeypatch)
    assert module.NAMESPACE == "broker"
    assert module.BROKER_URL == ""


def test_settings(updater: ModuleType) -> None:
    """The namespace and the URL of Pubgrade come from the environment."""
    assert updater.NAMESPACE == "builds"
    assert updater.BROKER_URL == "http://pubgrade/repositories/{}/builds/{}"


def test_get_env(updater: ModuleType) -> None:
    """Values of environment variables are found by name, or are `None`."""
    env = make_pod(env={"A": "1", "B": "2"}).spec.containers[0].env
    assert updater.get_env(env, "B") == "2"
    assert updater.get_env(env, "C") is None


def test_report_build(updater: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A succeeded build is reported with its access token."""
    request = MagicMock()
    monkeypatch.setattr(updater.requests, "request", request)
    updater.report_build(make_pod(env=BUILD_ENV))
    request.assert_called_once_with(
        "PUT",
        "http://pubgrade/repositories/abcdef/builds/abcdefghijkl",
        headers={
            "X-Project-Access-Token": "token",
            "Content-Type": "application/json",
        },
        data=json.dumps({"id": "abcdefghijkl"}),
        timeout=updater.REQUEST_TIMEOUT,
    )


def test_report_build_repository_id(
    updater: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repository comes from the pod, whatever the length of its ID."""
    request = MagicMock()
    monkeypatch.setattr(updater.requests, "request", request)
    env = {**BUILD_ENV, "REPOSITORYID": "abcdefgh", "BUILDNAME": "abcdefghij"}
    updater.report_build(make_pod(env=env))
    assert request.call_args.args[1] == (
        "http://pubgrade/repositories/abcdefgh/builds/abcdefghij"
    )


@pytest.mark.parametrize(
    "pod",
    [
        make_pod(env=BUILD_ENV, spec=False),
        make_pod(env=BUILD_ENV, status=False),
        make_pod(env=None),
        make_pod(phase="Running", env=BUILD_ENV),
        make_pod(env={"BUILDNAME": "abcdefghijkl"}),
        make_pod(env={"ACCESSTOKEN": "token"}),
    ],
    ids=[
        "no spec",
        "no status",
        "no env",
        "running",
        "no access token",
        "no build name",
    ],
)
def test_report_build_skipped(
    updater: ModuleType, monkeypatch: pytest.MonkeyPatch, pod: Any
) -> None:
    """Pods that aren't finished builds are skipped."""
    request = MagicMock()
    monkeypatch.setattr(updater.requests, "request", request)
    updater.report_build(pod)
    request.assert_not_called()


def test_report_build_failed(
    updater: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed report is logged with the type of the error only."""
    request = MagicMock(side_effect=requests.exceptions.ConnectionError("token"))
    monkeypatch.setattr(updater.requests, "request", request)
    with caplog.at_level(logging.ERROR):
        updater.report_build(make_pod(env=BUILD_ENV))
    assert "Reporting build abcdefghijkl failed: ConnectionError" in caplog.text
    assert "token" not in caplog.text


def test_report_build_error_response(
    updater: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An error response of Pubgrade is logged as a failed report."""
    response = MagicMock()
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    monkeypatch.setattr(updater.requests, "request", MagicMock(return_value=response))
    with caplog.at_level(logging.ERROR):
        updater.report_build(make_pod(env=BUILD_ENV))
    assert "Reporting build abcdefghijkl failed: HTTPError" in caplog.text


def test_report_builds(updater: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """All pods of the namespace are checked."""
    pods = [make_pod(env=BUILD_ENV), make_pod(phase="Running", env=BUILD_ENV)]
    api = MagicMock()
    api.list_namespaced_pod.return_value = SimpleNamespace(items=pods)
    monkeypatch.setattr(updater.client, "CoreV1Api", lambda: api)
    report_build = MagicMock()
    monkeypatch.setattr(updater, "report_build", report_build)
    updater.report_builds()
    api.list_namespaced_pod.assert_called_once_with(namespace="builds", watch=False)
    assert [call.args[0] for call in report_build.call_args_list] == pods


class Stop(Exception):
    """Ends the updater's loop in tests."""


@pytest.mark.parametrize(
    ("host", "loader"),
    [("10.0.0.1", "load_incluster_config"), (None, "load_kube_config")],
    ids=["in cluster", "kubeconfig"],
)
def test_main(
    updater: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    host: str | None,
    loader: str,
) -> None:
    """The updater loads the cluster configuration, then reports builds."""
    if host is None:
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    else:
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", host)
    load = MagicMock()
    monkeypatch.setattr(updater.config, loader, load)
    report_builds = MagicMock()
    monkeypatch.setattr(updater, "report_builds", report_builds)
    monkeypatch.setattr(updater.time, "sleep", MagicMock(side_effect=Stop))
    with pytest.raises(Stop):
        updater.main()
    load.assert_called_once_with()
    report_builds.assert_called_once_with()
