"""Shared test fixtures."""

from collections.abc import Iterator
import copy
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from git import Actor, Repo
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
    originals: dict[str, dict[str, Any]] = {
        name: copy.deepcopy(value)
        for name, value in vars(mock_data).items()
        if name.isupper() and isinstance(value, dict)
    }
    yield
    for name, original in originals.items():
        current = getattr(mock_data, name)
        current.clear()
        current.update(original)


# Organization on GitHub whose repositories tests clone from a local copy
GITHUB_ORG = "https://github.com/elixir-cloud-aai/"


@pytest.fixture(scope="session")
def local_remote(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """Create a local stand-in for the repository `drs-filer` on GitHub.

    It has the branch `dev` with two commits, and the tag `v1` on the first.

    Args:
        tmp_path_factory: Pytest's factory of temporary directories.

    Returns:
        Its parent directory (`root`), the first commit (`commit`) and the
        tag (`tag`).
    """
    root = tmp_path_factory.mktemp("remote")
    repo = Repo.init(root / "drs-filer", initial_branch="dev")
    actor = Actor("Test", "test@example.org")
    dockerfile = Path(repo.working_dir) / "Dockerfile"
    commits = []
    for version in ("1", "2"):
        dockerfile.write_text(f"FROM scratch\nLABEL version={version}\n")
        repo.index.add(["Dockerfile"])
        commits.append(
            repo.index.commit(f"Version {version}", author=actor, committer=actor)
        )
    # Without the user's Git configuration, which may require tag messages
    with repo.git.custom_environment(
        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1"
    ):
        repo.create_tag("v1", ref=commits[0])
    return SimpleNamespace(root=root, commit=commits[0].hexsha[:7], tag="v1")


@pytest.fixture
def drs_filer(
    local_remote: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    """Let Git clone the repositories of GitHub's organization from local ones.

    Tests then need no network access: Git rewrites the URLs
    (`url.<base>.insteadOf`) in a global configuration of its own.

    Args:
        local_remote: The local repositories.
        tmp_path: Temporary directory for the Git configuration.
        monkeypatch: Pytest's monkeypatch fixture.

    Returns:
        The local repository, see `local_remote()`.
    """
    config = tmp_path / "gitconfig"
    config.write_text(
        f'[url "{local_remote.root.as_uri()}/"]\n\tinsteadOf = {GITHUB_ORG}\n'
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return local_remote
