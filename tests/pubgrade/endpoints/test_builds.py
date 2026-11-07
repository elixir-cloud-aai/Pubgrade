"""Tests for /builds endpoint."""

import copy
import json
import logging
import os
from pathlib import Path
import shutil
import traceback
from types import SimpleNamespace
from typing import Any, ClassVar, NoReturn
from unittest.mock import MagicMock, patch

from git import Git, GitCommandError, Repo
from kubernetes.client import ApiException
import mongomock
from pymongo.errors import DuplicateKeyError
import pytest
import requests
from werkzeug.exceptions import BadRequest, InternalServerError, Unauthorized
import yaml

from pubgrade.errors.exceptions import (
    BuildCanceled,
    BuildNotFound,
    BuildsDisabled,
    CreatePodError,
    DeletePodError,
    GitCloningError,
    GitRefNotFound,
    InvalidImage,
    RepositoryNotFound,
    exceptions,
)
from pubgrade.modules.endpoints import builds
from pubgrade.modules.endpoints.builds import (
    IMAGE_WITH_TAG,
    build_completed,
    build_push_image_using_kaniko,
    cancel_build,
    create_build,
    create_deployment_YAML,
    create_dockerhub_config_file,
    get_build_info,
    get_builds,
    git_clone_and_checkout,
    publish_prebuilt_image,
    register_builds,
    remove_build_dir,
    remove_files,
    start_build,
    stop_builds,
    stop_canceled_build,
)
from tests.helpers import FocaApp, make_config
from tests.mock_data import (
    ENDPOINT_CONFIG,
    MOCK_BUILD_INFO,
    MOCK_BUILD_INFO_2,
    MOCK_BUILD_PAYLOAD,
    MOCK_REPOSITORIES,
    MOCK_REPOSITORY_2,
    MOCK_SUBSCRIPTION_INFO,
)


def mocked_create_build(
    repo_url: str,
    branch: str,
    commit: str,
    base_dir: str,
    build_id: str,
    dockerfile_location: str,
    intermediate_registry_path: str,
    dockerhub_token: str,
    project_access_token: str,
) -> str:
    """Mock `create_build`.

    Args:
        repo_url: URL of the repository.
        branch: Branch name.
        commit: Commit hash.
        base_dir: Base directory.
        build_id: Identifier of the build.
        dockerfile_location: Location of the Dockerfile.
        intermediate_registry_path: Intermediate registry path.
        dockerhub_token: Token for DockerHub.
        project_access_token: Access token of the project.

    Returns:
        A fixed string.
    """
    return "working fine"


def mocked_remove_files(dir_location: str, pod_name: str, namespace: str) -> str:
    """Mock `remove_files`.

    Args:
        dir_location: Location of the directory.
        pod_name: Name of the pod.
        namespace: Kubernetes namespace.

    Returns:
        A fixed string.
    """
    return "removed"


def mocked_notify_subscriptions(subscription_id: str, image: str, build_id: str) -> str:
    """Mock `notify_subscriptions`.

    Args:
        subscription_id: Identifier of the subscription.
        image: Image name with tag.
        build_id: Identifier of the build.

    Returns:
        A fixed string.
    """
    return "Notified"


def mocked_delete_pod(name: str, namespace: str) -> str:
    """Mock `delete_pod`.

    Args:
        name: Name to use.
        namespace: Kubernetes namespace.

    Returns:
        A fixed string.
    """
    return "Pod deleted."


def mocked_delete_namespaced_pod(
    self: Any, name: str, namespace: str, **kwargs: Any
) -> str:
    """Mock `CoreV1Api.delete_namespaced_pod`.

    Args:
        self: Ignored.
        name: Name to use.
        namespace: Kubernetes namespace.
        **kwargs: Ignored.

    Returns:
        A fixed string.
    """
    return "Pod deleted."


def mocked_delete_namespaced_pod_error(
    self: Any, name: str, namespace: str, **kwargs: Any
) -> NoReturn:
    """Mock `CoreV1Api.delete_namespaced_pod` raising an API error.

    Args:
        self: Ignored.
        name: Name to use.
        namespace: Kubernetes namespace.
        **kwargs: Ignored.

    Raises:
        ApiException: Always.
    """
    raise ApiException


def mocked_request_api(
    method: str, url: str, data: Any, headers: Any, **kwargs: Any
) -> MagicMock:
    """Mock `requests.request` with a successful response.

    Args:
        method: HTTP method of the request.
        url: URL of the request.
        data: Request body.
        headers: Request headers.
        **kwargs: Ignored.

    Returns:
        A response with status code 200.
    """
    return MagicMock(status_code=200)


def mocked_load_cluster_config(
    config_file: str | None = None,
    context: str | None = None,
    client_configuration: Any = None,
    persist_config: bool = True,
) -> str:
    """Mock `load_kube_config`.

    Args:
        config_file: Ignored.
        context: Ignored.
        client_configuration: Ignored.
        persist_config: Ignored.

    Returns:
        A fixed string.
    """
    return "Loaded successfully"


def mocked_load_incluster_config() -> str:
    """Mock `load_incluster_config`.

    Returns:
        A fixed string.
    """
    return "Loaded successfully"


def mocked_core_v1_api() -> str:
    """Mock `CoreV1Api`.

    Returns:
        A fixed string.
    """
    return "v1 API"


def mocked_create_namespaced_pod(
    self: Any, namespace: str, body: Any, **kwargs: Any
) -> dict[str, Any]:
    """Mock `CoreV1Api.create_namespaced_pod`.

    Args:
        self: Ignored.
        namespace: Kubernetes namespace.
        body: Body of the request.
        **kwargs: Ignored.

    Returns:
        A pod description.
    """
    return {"metadata": {"name": "kaniko"}}


def mocked_create_namespaced_pod_error(
    self: Any, namespace: str, body: Any, **kwargs: Any
) -> NoReturn:
    """Mock `CoreV1Api.create_namespaced_pod` raising an API error.

    Args:
        self: Ignored.
        namespace: Kubernetes namespace.
        body: Body of the request.
        **kwargs: Ignored.

    Raises:
        ApiException: Always.
    """
    raise ApiException


def mocked_create_namespaced_pod_echo(
    self: Any, namespace: str, body: Any, **kwargs: Any
) -> Any:
    """Return the created pod, as the Kubernetes API does."""
    return body


def _api_exception_with_body() -> ApiException:
    """Get an error of the Kubernetes API whose body has a secret."""
    exc = ApiException(status=422, reason="Unprocessable Entity")
    exc.body = '{"message": "value pod-secret is invalid"}'
    return exc


def mocked_create_namespaced_pod_error_body(
    self: Any, namespace: str, body: Any, **kwargs: Any
) -> NoReturn:
    """Fail with a response body that has a secret."""
    raise _api_exception_with_body()


def mocked_delete_namespaced_pod_error_body(
    self: Any, name: str, namespace: str, **kwargs: Any
) -> NoReturn:
    """Fail with a response body that has a secret."""
    raise _api_exception_with_body()


def mocked_load_kube_config(
    config_file: str | None = None,
    context: str | None = None,
    client_configuration: Any = None,
    persist_config: bool = True,
) -> str:
    """Mock the kube config loading function.

    Args:
        config_file: Ignored.
        context: Ignored.
        client_configuration: Ignored.
        persist_config: Ignored.

    Returns:
        A fixed string.
    """
    return "success"


def mocked_get_kube_config_loader(
    filename: str | None = None,
    config_dict: Any = None,
    persist_config: bool = False,
    **kwargs: Any,
) -> "type[MockKubeConfigLoader]":
    """Mock `_get_kube_config_loader`.

    Args:
        filename: Ignored.
        config_dict: Ignored.
        persist_config: Ignored.
        **kwargs: Ignored.

    Returns:
        The mock loader class.
    """
    return MockKubeConfigLoader


class MockKubeConfigLoader:
    """Mock KubeConfigLoader."""

    def load_and_set(self) -> str:
        """Mock loading and setting the configuration.

        Returns:
            A fixed string.
        """
        return "success"


class TestBuild:
    """Tests for TestBuild."""

    app = FocaApp(__name__)

    repository_url = "https://github.com/elixir-cloud-aai/drs-filer"
    id_length = 0

    def setup(self) -> None:
        """Set up the app with mock data."""
        self.app.config.foca = make_config(ENDPOINT_CONFIG)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        self.id_length = self.app.config.foca.endpoints["repository"]["id_length"]
        for repository in MOCK_REPOSITORIES:
            self.app.config.foca.db.dbs["pubgradeStore"].collections[
                "repositories"
            ].client.insert_one(repository)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client = mongomock.MongoClient().db.collection

    def setup_with_build(self) -> None:
        """Set up the app with mock repositories and builds."""
        self.setup()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO_2)

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds(self) -> None:
        """Test register builds."""
        self.setup()
        with self.app.app_context():
            res = register_builds(
                MOCK_REPOSITORIES[1]["id"],
                MOCK_REPOSITORIES[1]["access_token"],
                MOCK_BUILD_PAYLOAD,
            )
            assert isinstance(res, dict)
            # The build ID starts with the repository ID, followed by random
            # characters.
            assert (
                "id" in res
                and res["id"][: self.id_length] == MOCK_REPOSITORIES[1]["id"]
            )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_logs_no_token(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Log messages don't contain the token for DockerHub."""
        self.setup()
        caplog.set_level(logging.DEBUG)
        with self.app.app_context():
            res = register_builds(
                MOCK_REPOSITORIES[1]["id"],
                MOCK_REPOSITORIES[1]["access_token"],
                {**MOCK_BUILD_PAYLOAD, "dockerhub_token": "dockerhub-secret"},
            )
        assert f"Added build {res['id']}." in caplog.messages
        assert "dockerhub-secret" not in caplog.text

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_branch_only(self) -> None:
        """Test register builds branch only."""
        self.setup()
        del MOCK_BUILD_PAYLOAD["head_commit"]
        MOCK_BUILD_PAYLOAD["head_commit"] = {"branch": "sample_branch"}
        with self.app.app_context():
            res = register_builds(
                MOCK_REPOSITORIES[1]["id"],
                MOCK_REPOSITORIES[1]["access_token"],
                MOCK_BUILD_PAYLOAD,
            )
            assert isinstance(res, dict)
            # The build ID starts with the repository ID, followed by random
            # characters.
            assert (
                "id" in res
                and res["id"][: self.id_length] == MOCK_REPOSITORIES[1]["id"]
            )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_tag(self) -> None:
        """Test register builds tag."""
        self.setup()
        del MOCK_BUILD_PAYLOAD["head_commit"]
        MOCK_BUILD_PAYLOAD["head_commit"] = {"tag": "12345"}
        with self.app.app_context():
            res = register_builds(
                MOCK_REPOSITORIES[1]["id"],
                MOCK_REPOSITORIES[1]["access_token"],
                MOCK_BUILD_PAYLOAD,
            )
            assert isinstance(res, dict)
            # The build ID starts with the repository ID, followed by random
            # characters.
            assert (
                "id" in res
                and res["id"][: self.id_length] == MOCK_REPOSITORIES[1]["id"]
            )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_duplicate_key_error(self) -> None:
        """Test register builds duplicate key error."""
        self.setup()
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one = mock_resp
        with self.app.app_context(), pytest.raises(InternalServerError):
            register_builds(
                MOCK_REPOSITORIES[1]["id"],
                MOCK_REPOSITORIES[1]["access_token"],
                MOCK_BUILD_PAYLOAD,
            )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_unauthorized(self) -> None:
        """Test register builds unauthorized."""
        self.setup()
        with self.app.app_context(), pytest.raises(Unauthorized):
            register_builds(
                MOCK_REPOSITORIES[1]["id"],
                "access_token",
                MOCK_BUILD_PAYLOAD,
            )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_repository_not_found(self) -> None:
        """Test register builds repository not found."""
        self.setup()
        with self.app.app_context(), pytest.raises(RepositoryNotFound):
            register_builds(
                "id",
                MOCK_REPOSITORIES[1]["access_token"],
                MOCK_BUILD_PAYLOAD,
            )

    @pytest.mark.parametrize("error", [GitRefNotFound, GitCloningError, RuntimeError])
    def test_register_builds_failed_build_not_recorded(
        self, error: type[Exception]
    ) -> None:
        """A build that can't start isn't recorded, for the repository either.

        Args:
            error: Error of starting the build.
        """
        self.setup()
        repository_id = MOCK_REPOSITORY_2["id"]
        with (
            patch.object(builds, "create_build", side_effect=error),
            self.app.app_context(),
        ):
            assert builds.builds_enabled()
            with pytest.raises(error):
                register_builds(
                    repository_id,
                    MOCK_REPOSITORY_2["access_token"],
                    copy.deepcopy(MOCK_BUILD_PAYLOAD),
                )
            repository = builds.collection("repositories").find_one(
                {"id": repository_id}
            )
            assert builds.collection("builds").count_documents({}) == 0
        assert repository is not None
        assert repository["build_list"] == MOCK_REPOSITORY_2["build_list"]

    def test_register_builds_pod_error_keeps_build(self) -> None:
        """A build whose pod may have been created is kept."""
        self.setup()
        repository_id = MOCK_REPOSITORY_2["id"]
        with (
            patch.object(builds, "create_build", side_effect=CreatePodError),
            self.app.app_context(),
        ):
            with pytest.raises(CreatePodError):
                register_builds(
                    repository_id,
                    MOCK_REPOSITORY_2["access_token"],
                    copy.deepcopy(MOCK_BUILD_PAYLOAD),
                )
            repository = builds.collection("repositories").find_one(
                {"id": repository_id}
            )
            assert builds.collection("builds").count_documents({}) == 1
        assert repository is not None
        assert len(repository["build_list"]) == len(MOCK_REPOSITORY_2["build_list"]) + 1

    @pytest.mark.parametrize(
        ("head_commit", "branch", "commit"),
        [
            ({"branch": "dev"}, "dev", ""),
            ({"branch": "dev", "commit_sha": "abc1234"}, "dev", "abc1234"),
            ({"tag": "v1"}, "", "v1"),
        ],
    )
    def test_start_build(
        self, head_commit: dict[str, str], branch: str, commit: str
    ) -> None:
        """A build checks out the branch (and commit) or the tag.

        Args:
            head_commit: Branch, commit or tag of the request.
            branch: Expected branch to check out.
            commit: Expected commit or tag to check out.
        """
        self.setup()
        build = {**copy.deepcopy(MOCK_BUILD_PAYLOAD), "id": "build123"}
        build["head_commit"] = head_commit
        with (
            patch.object(builds, "create_build") as create,
            self.app.app_context(),
        ):
            start_build(build, self.repository_url, "access_token")
        create.assert_called_once()
        assert create.call_args.kwargs["branch"] == branch
        assert create.call_args.kwargs["commit"] == commit
        assert (
            create.call_args.kwargs["intermediate_registry_path"]
            == "ttl.sh/test-updater:1h"
        )

    @pytest.mark.parametrize(
        "head_commit",
        [
            {"tag": ""},
            {"branch": ""},
            {"branch": "", "commit_sha": "abcd"},
            {"branch": "dev", "commit_sha": ""},
        ],
    )
    def test_start_build_empty_name(self, head_commit: dict[str, str]) -> None:
        """An empty branch or tag is rejected, instead of the default branch.

        Args:
            head_commit: Branch, commit or tag of the request.
        """
        self.setup()
        build = {**copy.deepcopy(MOCK_BUILD_PAYLOAD), "id": "build123"}
        build["head_commit"] = head_commit
        with (
            patch.object(builds, "create_build") as create,
            self.app.app_context(),
            pytest.raises(GitRefNotFound),
        ):
            start_build(build, self.repository_url, "access_token")
        create.assert_not_called()

    def test_register_builds_failed_removal(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If a build that can't start can't be removed, its error is kept.

        Args:
            caplog: Pytest's fixture of log messages.
        """
        self.setup()
        builds_client = (
            self.app.config.foca.db.dbs["pubgradeStore"].collections["builds"].client
        )
        builds_client.delete_one = MagicMock(side_effect=RuntimeError)
        with (
            patch.object(builds, "create_build", side_effect=GitRefNotFound),
            self.app.app_context(),
            pytest.raises(GitRefNotFound),
        ):
            register_builds(
                MOCK_REPOSITORY_2["id"],
                MOCK_REPOSITORY_2["access_token"],
                copy.deepcopy(MOCK_BUILD_PAYLOAD),
            )
        assert any(
            "could not start, failed: RuntimeError" in message
            for message in caplog.messages
        )

    def test_get_builds(self) -> None:
        """Test get builds."""
        self.setup_with_build()
        with self.app.app_context():
            res = get_builds(MOCK_REPOSITORIES[1]["id"])
            assert isinstance(res, list)
            assert len(res) == 2

    def test_get_builds_build_not_found(self) -> None:
        """Test get builds build not found."""
        self.setup()
        with self.app.app_context(), pytest.raises(BuildNotFound):
            get_builds(MOCK_REPOSITORIES[1]["id"])

    def test_get_builds_repository_not_found(self) -> None:
        """Test get builds repository not found."""
        self.setup()
        with self.app.app_context(), pytest.raises(RepositoryNotFound):
            get_builds("abcd")

    def test_get_build_info(self) -> None:
        """Test get build info."""
        self.setup_with_build()
        with self.app.app_context():
            res = get_build_info(MOCK_BUILD_INFO["id"])
            assert isinstance(res, dict)
            assert "finished_at" in res
            assert "head_commit" in res
            assert "started_at" in res
            assert "branch" in res["head_commit"]

    def test_get_build_info_old_format(self) -> None:
        """Builds written by the previous version get timestamps with zone."""
        self.setup()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(
            {
                **MOCK_BUILD_INFO,
                "started_at": "2026-01-02T03:04:05",
                "finished_at": "NULL",
                "notifications": [{"finished_at": "2026-01-02T03:04:06"}],
            }
        )
        with self.app.app_context():
            res = get_build_info(MOCK_BUILD_INFO["id"])
        assert res["started_at"] == "2026-01-02T03:04:05+00:00"
        assert res["finished_at"] is None
        assert res["notifications"] == [{"finished_at": "2026-01-02T03:04:06+00:00"}]

    def test_get_build_info_build_not_found(self) -> None:
        """Test get build info build not found."""
        self.setup_with_build()
        with self.app.app_context(), pytest.raises(BuildNotFound):
            get_build_info("abcd")

    def test_git_clone_and_checkout(self, drs_filer: SimpleNamespace) -> None:
        """Test git clone and checkout.

        Args:
            drs_filer: Local copy of the repository.
        """
        clone_path = git_clone_and_checkout(
            repo_url=self.repository_url,
            branch="dev",
            commit=drs_filer.commit,
            base_dir=".",
            build_id="build123",
        )
        assert clone_path == "./build123/drs-filer"
        assert Repo(clone_path).head.commit.hexsha.startswith(drs_filer.commit)
        shutil.rmtree("./build123")

    def test_git_clone_and_checkout_without_branch(
        self, drs_filer: SimpleNamespace
    ) -> None:
        """Test git clone and checkout of a tag, without branch.

        Args:
            drs_filer: Local copy of the repository.
        """
        clone_path = git_clone_and_checkout(
            repo_url=self.repository_url,
            branch="",
            commit=drs_filer.tag,
            base_dir=".",
            build_id="build123",
        )
        assert clone_path == "./build123/drs-filer"
        assert Repo(clone_path).head.commit.hexsha.startswith(drs_filer.commit)
        shutil.rmtree("./build123")

    def test_git_clone_and_checkout_branch_only(
        self, drs_filer: SimpleNamespace, tmp_path: Path
    ) -> None:
        """Without a tag or commit, the head of the branch is checked out.

        Args:
            drs_filer: Local copy of the repository.
            tmp_path: Temporary directory, holding the base directory.
        """
        clone_path = git_clone_and_checkout(
            repo_url=self.repository_url,
            branch="dev",
            commit="",
            base_dir=str(tmp_path),
            build_id="build123",
        )
        clone = Repo(clone_path)
        remote = Repo(drs_filer.root / "drs-filer")
        assert clone.active_branch.name == "dev"
        assert clone.head.commit == remote.heads.dev.commit

    def test_git_clone_and_checkout_full_hash(
        self, drs_filer: SimpleNamespace, tmp_path: Path
    ) -> None:
        """A full commit hash is checked out, also without a branch.

        Args:
            drs_filer: Local copy of the repository.
            tmp_path: Temporary directory, holding the base directory.
        """
        remote = Repo(drs_filer.root / "drs-filer")
        commit = remote.commit(drs_filer.commit).hexsha
        clone_path = git_clone_and_checkout(
            repo_url=self.repository_url,
            branch="",
            commit=commit,
            base_dir=str(tmp_path),
            build_id="build123",
        )
        assert Repo(clone_path).head.commit.hexsha == commit

    @pytest.mark.parametrize(
        ("branch", "commit"),
        [
            ("missing", ""),
            ("missing", "v1"),
            ("dev", "0000000"),
            ("", "v9"),
            ("", "--detach"),
            ("--detach", ""),
            ("HEAD", ""),
            ("", "HEAD~1"),
            ("", "origin/dev"),
            ("dev", "HEAD~1"),
            ("dev", "v1~0"),
            ("dev", "v1"),
        ],
    )
    def test_git_clone_and_checkout_unknown_ref(
        self, drs_filer: SimpleNamespace, tmp_path: Path, branch: str, commit: str
    ) -> None:
        """A branch, tag or commit that isn't in the repository is rejected.

        Args:
            drs_filer: Local copy of the repository.
            tmp_path: Temporary directory, holding the base directory.
            branch: Branch to check out.
            commit: Commit or tag to check out.
        """
        with pytest.raises(GitRefNotFound):
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch=branch,
                commit=commit,
                base_dir=str(tmp_path),
                build_id="build123",
            )

    def test_git_clone_and_checkout_checkout_error(
        self, drs_filer: SimpleNamespace, tmp_path: Path
    ) -> None:
        """A checkout of a known branch that fails is a server error.

        Args:
            drs_filer: Local copy of the repository.
            tmp_path: Temporary directory, holding the base directory.
        """
        with (
            patch.object(
                Git,
                "checkout",
                side_effect=GitCommandError("checkout", 128),
                create=True,
            ),
            pytest.raises(GitCloningError),
        ):
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch="dev",
                commit=drs_filer.commit,
                base_dir=str(tmp_path),
                build_id="build123",
            )

    @pytest.mark.parametrize(("branch", "commit"), [("dev", ""), ("", "v1")])
    def test_git_clone_and_checkout_lookup_error(
        self, drs_filer: SimpleNamespace, tmp_path: Path, branch: str, commit: str
    ) -> None:
        """A lookup that fails for another reason than an unknown name is a 500.

        Args:
            drs_filer: Local copy of the repository.
            tmp_path: Temporary directory, holding the base directory.
            branch: Branch to check out.
            commit: Tag to check out.
        """
        with (
            patch.object(
                Git,
                "show_ref",
                side_effect=GitCommandError("show-ref", 128),
                create=True,
            ),
            pytest.raises(GitCloningError),
        ):
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch=branch,
                commit=commit,
                base_dir=str(tmp_path),
                build_id="build123",
            )

    def test_git_ref_not_found_is_bad_request(self) -> None:
        """An unknown branch, tag or commit is the client's error (400)."""
        assert issubclass(GitRefNotFound, BadRequest)
        assert exceptions[GitRefNotFound]["status"] == 400

    def test_git_clone_and_checkout_git_command_error(
        self, drs_filer: SimpleNamespace
    ) -> None:
        """Cloning into a directory that already has the clone fails.

        Args:
            drs_filer: Local copy of the repository.
        """
        git_clone_and_checkout(
            repo_url=self.repository_url,
            branch="dev",
            commit=drs_filer.commit,
            base_dir=".",
            build_id="build123",
        )
        with pytest.raises(GitCloningError):
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch="dev",
                commit=drs_filer.commit,
                base_dir=".",
                build_id="build123",
            )
        shutil.rmtree("./build123")

    def test_create_deployment_yaml(self) -> None:
        """Test create deployment yaml."""
        builds.template_file = "pubgrade/modules/endpoints/kaniko/template.yaml"
        os.mkdir("build123")
        os.mkdir("build123/drs-filer")
        deployment_file_location = create_deployment_YAML(
            "./build123/drs-filer/dockerfile_location",
            "registry_destination",
            "clone_path",
            "./build123/drs-filer/deployment_file",
            "build_id/config.json",
            "project_access_token",
        )
        assert deployment_file_location == "./build123/drs-filer/deployment_file"
        assert os.path.isfile(deployment_file_location)
        shutil.rmtree("./build123")

    def test_create_deployment_yaml_if_env_present(self) -> None:
        """Test create deployment yaml if env present."""
        os.environ["NAMESPACE"] = "pubgrade"
        builds.template_file = "pubgrade/modules/endpoints/kaniko/template.yaml"
        os.mkdir("build123")
        os.mkdir("build123/drs-filer")
        deployment_file_location = create_deployment_YAML(
            "./build123/drs-filer/dockerfile_location",
            "registry_destination",
            "clone_path",
            "./build123/drs-filer/deployment_file",
            "build_id/config.json",
            "project_access_token",
        )
        assert deployment_file_location == "./build123/drs-filer/deployment_file"
        assert os.path.isfile(deployment_file_location)
        shutil.rmtree("./build123")
        del os.environ["NAMESPACE"]

    def test_create_deployment_yaml_os_error(self) -> None:
        """Test create deployment yaml os error."""
        with pytest.raises(OSError):
            builds.template_file = "pubgrade/modules/endpoints/kaniko/template.yaml"
            deployment_file_location = create_deployment_YAML(
                "./build123/drs-filer/dockerfile_location",
                "registry_destination",
                "clone_path",
                "./build123/drs-filer/deployment_file",
                "build_id" + "/config.json",
                "project_access_token",
            )
            assert deployment_file_location == "./build123/drs-filer/deployment_file"
            assert os.path.isfile(deployment_file_location)
            shutil.rmtree("./build123")

    def test_create_dockerhub_config_file(self) -> None:
        """Test create dockerhub config file."""
        self.setup()
        with self.app.app_context():
            create_dockerhub_config_file("token", "config.json")
        assert os.path.isfile("config.json")
        os.remove("config.json")

    @pytest.mark.parametrize("build_id", ["../escape", "/abs", "a/../../escape"])
    @patch("pubgrade.modules.endpoints.builds.git_clone_and_checkout")
    def test_create_build_outside_base_dir(
        self, clone: MagicMock, build_id: str, tmp_path: Path
    ) -> None:
        """Builds can't write outside the base directory.

        Args:
            clone: Mock of the function that clones the repository.
            build_id: Identifier of the build.
            tmp_path: Temporary directory, holding the base directory.
        """
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        with pytest.raises(InternalServerError):
            create_build(
                repo_url=self.repository_url,
                branch="dev",
                commit="",
                base_dir=str(base_dir),
                build_id=build_id,
                dockerfile_location="Dockerfile",
                intermediate_registry_path="registry/image",
                dockerhub_token="token",
                project_access_token="access_token",
            )
        clone.assert_not_called()
        assert list(tmp_path.iterdir()) == [base_dir]

    @pytest.mark.parametrize(
        ("base_dir", "config_file"),
        [
            (".", os.path.abspath("build123/config.json")),
            ("/", "/build123/config.json"),
            ("/base/", "/base/build123/config.json"),
        ],
    )
    @patch("pubgrade.modules.endpoints.builds.build_push_image_using_kaniko")
    @patch("pubgrade.modules.endpoints.builds.create_dockerhub_config_file")
    @patch("pubgrade.modules.endpoints.builds.create_deployment_YAML")
    @patch("pubgrade.modules.endpoints.builds.git_clone_and_checkout")
    def test_create_build_base_dir(
        self,
        clone: MagicMock,
        deployment: MagicMock,
        config_file_writer: MagicMock,
        push_image: MagicMock,
        base_dir: str,
        config_file: str,
    ) -> None:
        """Builds are accepted in any base directory, including `.` and `/`.

        Args:
            clone: Mock of the function that clones the repository.
            deployment: Mock of the function that writes the deployment file.
            config_file_writer: Mock of the function that writes the config file.
            push_image: Mock of the function that pushes the image.
            base_dir: Base directory of the builds.
            config_file: Expected location of the config file.
        """
        create_build(
            repo_url=self.repository_url,
            branch="dev",
            commit="",
            base_dir=base_dir,
            build_id="build123",
            dockerfile_location="Dockerfile",
            intermediate_registry_path="registry/image",
            dockerhub_token="token",
            project_access_token="access_token",
        )
        clone.assert_called_once()
        config_file_writer.assert_called_once_with(
            dockerhub_token="token", config_file_location=config_file
        )
        push_image.assert_called_once()

    @patch("pubgrade.modules.endpoints.builds.build_push_image_using_kaniko")
    def test_create_build(
        self, push_image: MagicMock, drs_filer: SimpleNamespace
    ) -> None:
        """Test create build.

        Args:
            push_image: Mock of the function that pushes the image.
            drs_filer: Local copy of the repository.
        """
        builds.template_file = "pubgrade/modules/endpoints/kaniko/template.yaml"
        os.mkdir("basedir")
        os.mkdir("basedir/drs-filer")
        with open("basedir/drs-filer/Dockerfile", "w") as f:
            f.write("test dockerfile")
        self.setup()
        with self.app.app_context():
            create_build(
                repo_url=self.repository_url,
                branch="dev",
                commit=drs_filer.commit,
                base_dir="basedir",
                build_id="build123",
                dockerfile_location="basedir/drs-filer/Dockerfile",
                intermediate_registry_path="test_intermediate_registry_path",
                dockerhub_token="dockerhub_token",
                project_access_token="access_token",
            )
        deployment_file = "basedir/build123/build123.yaml"
        assert os.path.isfile(deployment_file)
        assert os.path.isfile("basedir/build123/config.json")
        assert os.path.isdir("basedir/build123/drs-filer/.git")
        push_image.assert_called_once_with(deployment_file_location=deployment_file)
        shutil.rmtree("basedir")

    @pytest.mark.parametrize("error", [CreatePodError, RuntimeError])
    @patch("pubgrade.modules.endpoints.builds.create_dockerhub_config_file")
    @patch("pubgrade.modules.endpoints.builds.create_deployment_YAML")
    @patch("pubgrade.modules.endpoints.builds.git_clone_and_checkout")
    def test_create_build_pod_error(
        self,
        clone: MagicMock,
        deployment: MagicMock,
        config_file_writer: MagicMock,
        error: type[Exception],
        tmp_path: Path,
    ) -> None:
        """If creating the pod fails, the build's files are kept.

        The pod may have been created nonetheless.

        Args:
            clone: Mock of the function that clones the repository.
            deployment: Mock of the function that writes the deployment file.
            config_file_writer: Mock of the function that writes the config file.
            error: Error of creating the pod.
            tmp_path: Temporary directory, holding the base directory.
        """
        build_dir = tmp_path / "build123"
        build_dir.mkdir()
        with (
            patch.object(builds, "build_push_image_using_kaniko", side_effect=error),
            pytest.raises(CreatePodError),
        ):
            create_build(
                repo_url=self.repository_url,
                branch="dev",
                commit="",
                base_dir=str(tmp_path),
                build_id="build123",
                dockerfile_location="Dockerfile",
                intermediate_registry_path="registry/image",
                dockerhub_token="token",
                project_access_token="access_token",
            )
        assert build_dir.is_dir()

    def test_remove_build_dir_missing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A build without files is fine.

        Args:
            tmp_path: Temporary directory, without the build's directory.
            caplog: Pytest's fixture of log messages.
        """
        remove_build_dir(str(tmp_path / "build123"), "build123")
        assert not caplog.messages

    def test_remove_build_dir_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Files of a build that can't be removed are logged.

        Args:
            tmp_path: Temporary directory, holding the build's directory.
            caplog: Pytest's fixture of log messages.
        """
        with patch.object(shutil, "rmtree", side_effect=PermissionError):
            remove_build_dir(str(tmp_path), "build123")
        assert "Removing the files of build build123 failed: PermissionError" in (
            caplog.messages
        )

    @patch("pubgrade.modules.endpoints.builds.build_push_image_using_kaniko")
    def test_create_build_unknown_ref(
        self, push_image: MagicMock, drs_filer: SimpleNamespace, tmp_path: Path
    ) -> None:
        """A build of an unknown branch leaves no files and starts no pod.

        Args:
            push_image: Mock of the function that pushes the image.
            drs_filer: Local copy of the repository.
            tmp_path: Temporary directory, holding the base directory.
        """
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        with pytest.raises(GitRefNotFound):
            create_build(
                repo_url=self.repository_url,
                branch="missing",
                commit="",
                base_dir=str(base_dir),
                build_id="build123",
                dockerfile_location="Dockerfile",
                intermediate_registry_path="registry/image",
                dockerhub_token="token",
                project_access_token="access_token",
            )
        push_image.assert_not_called()
        assert list(base_dir.iterdir()) == []

    @patch("pubgrade.modules.endpoints.builds.remove_files", mocked_remove_files)
    @patch("requests.request", mocked_request_api)
    def test_build_completed(self) -> None:
        """Test build completed."""
        self.setup_with_build()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
        with self.app.app_context():
            res = build_completed(
                MOCK_REPOSITORY_2["id"],
                MOCK_REPOSITORY_2["build_list"][0],
                MOCK_REPOSITORY_2["access_token"],
            )
            data = (
                self.app.config.foca.db.dbs["pubgradeStore"]
                .collections["builds"]
                .client.find_one(res)
            )
            assert data["status"] == "SUCCEEDED"
            assert res["id"] == MOCK_REPOSITORY_2["build_list"][0]

    @patch("pubgrade.modules.endpoints.builds.remove_files")
    @patch("requests.request", mocked_request_api)
    def test_build_completed_removes_pod_in_own_namespace(
        self, remove_files: MagicMock
    ) -> None:
        """The build pod is removed from Pubgrade's namespace."""
        self.setup_with_build()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        os.environ["NAMESPACE"] = "any"
        try:
            with self.app.app_context():
                build_completed(
                    MOCK_REPOSITORY_2["id"],
                    MOCK_REPOSITORY_2["build_list"][0],
                    MOCK_REPOSITORY_2["access_token"],
                )
        finally:
            del os.environ["NAMESPACE"]
        assert remove_files.call_args[0][2] == "any"

    def test_build_completed_build_of_other_repository(self) -> None:
        """A repository's token only completes that repository's builds."""
        self.setup_with_build()
        builds_collection = (
            self.app.config.foca.db.dbs["pubgradeStore"].collections["builds"].client
        )
        builds_collection.insert_one({"id": "other", "status": "QUEUED"})
        with self.app.app_context(), pytest.raises(BuildNotFound):
            build_completed(
                MOCK_REPOSITORY_2["id"],
                "other",
                MOCK_REPOSITORY_2["access_token"],
            )
        assert builds_collection.find_one({"id": "other"})["status"] == "QUEUED"

    def test_build_completed_listed_build_is_gone(self) -> None:
        """A build listed at the repository, but no longer stored, isn't found."""
        self.setup()
        with self.app.app_context(), pytest.raises(BuildNotFound):
            build_completed(
                MOCK_REPOSITORY_2["id"],
                MOCK_REPOSITORY_2["build_list"][0],
                MOCK_REPOSITORY_2["access_token"],
            )

    def test_build_completed_build_not_found(self) -> None:
        """Test build completed build not found."""
        self.setup_with_build()
        with self.app.app_context(), pytest.raises(BuildNotFound):
            build_completed(
                MOCK_REPOSITORY_2["id"],
                "build12",
                MOCK_REPOSITORY_2["access_token"],
            )

    def test_build_completed_unauthorized(self) -> None:
        """Test build completed unauthorized."""
        self.setup_with_build()
        with self.app.app_context(), pytest.raises(Unauthorized):
            build_completed(
                MOCK_REPOSITORY_2["id"],
                MOCK_REPOSITORY_2["build_list"][0],
                "123",
            )

    def test_build_completed_repository_not_found(self) -> None:
        """Test build completed repository not found."""
        self.setup_with_build()
        with self.app.app_context(), pytest.raises(RepositoryNotFound):
            build_completed(
                "repo125",
                MOCK_REPOSITORY_2["build_list"][0],
                MOCK_REPOSITORY_2["access_token"],
            )

    @patch("pubgrade.modules.endpoints.builds.delete_pod", mocked_delete_pod)
    def test_remove_files(self) -> None:
        """Test remove files."""
        os.mkdir("build123")
        remove_files("build123", "pod_name", "namespace")
        assert not os.path.isdir("build123")

    @patch("kubernetes.config.load_kube_config", mocked_load_cluster_config)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod",
        mocked_create_namespaced_pod,
    )
    def test_build_push_image_using_kaniko(self) -> None:
        """Test build push image using kaniko."""
        builds.template_file = "pubgrade/modules/endpoints/kaniko/template.yaml"
        with self.app.app_context():
            build_push_image_using_kaniko(builds.template_file)
        os.environ["NAMESPACE"] = "pubgrade"
        with self.app.app_context():
            build_push_image_using_kaniko(builds.template_file)
        del os.environ["NAMESPACE"]

    @patch(
        "kubernetes.config.kube_config.load_kube_config",
        mocked_load_kube_config,
    )
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod",
        mocked_create_namespaced_pod_error,
    )
    @patch(
        "kubernetes.config.kube_config._get_kube_config_loader",
        mocked_get_kube_config_loader,
    )
    @patch("kubernetes.config.kube_config.KubeConfigLoader", MockKubeConfigLoader)
    def test_build_push_image_using_kaniko_create_pod_error(self) -> None:
        """Test build push image using kaniko create pod error."""
        builds.template_file = "pubgrade/modules/endpoints/kaniko/template.yaml"
        with self.app.app_context(), pytest.raises(CreatePodError):
            build_push_image_using_kaniko(builds.template_file)

    @patch("kubernetes.client.api.core_v1_api.CoreV1Api", mocked_core_v1_api)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.delete_namespaced_pod",
        mocked_delete_namespaced_pod,
    )
    def test_delete_pod(self) -> None:
        """Test delete pod."""
        with self.app.app_context():
            builds.delete_pod("name", "namespace")

    @patch("kubernetes.client.api.core_v1_api.CoreV1Api", mocked_core_v1_api)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.delete_namespaced_pod",
        mocked_delete_namespaced_pod_error,
    )
    def test_delete_pod_api_error(self) -> None:
        """Test delete pod api error."""
        with self.app.app_context(), pytest.raises(DeletePodError):
            builds.delete_pod("name", "namespace")

    def test_ignore_missing(self) -> None:
        """Removing a directory ignores files that are gone, nothing else."""
        builds._ignore_missing(os.unlink, "gone", FileNotFoundError())
        with pytest.raises(PermissionError):
            builds._ignore_missing(os.unlink, "locked", PermissionError())

    def test_delete_pod_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Deleting a pod waits for the Kubernetes API for a limited time.

        Args:
            monkeypatch: Fixture to replace the Kubernetes API.
        """
        api = MagicMock()
        monkeypatch.setattr(builds.client, "CoreV1Api", lambda: api)
        builds.delete_pod("name", "namespace")
        api.delete_namespaced_pod.assert_called_once_with(
            "name", "namespace", _request_timeout=builds.KUBERNETES_TIMEOUT
        )

    @pytest.mark.parametrize("missing_ok", [True, False])
    def test_delete_pod_missing(
        self, monkeypatch: pytest.MonkeyPatch, missing_ok: bool
    ) -> None:
        """A missing pod counts as deleted only with `missing_ok`.

        Args:
            monkeypatch: Fixture to replace the Kubernetes API.
            missing_ok: Whether a missing pod counts as deleted.
        """
        api = MagicMock()
        api.delete_namespaced_pod.side_effect = ApiException(status=404)
        monkeypatch.setattr(builds.client, "CoreV1Api", lambda: api)
        if missing_ok:
            assert builds.delete_pod("name", "namespace", missing_ok=True) is None
        else:
            with pytest.raises(DeletePodError):
                builds.delete_pod("name", "namespace")

    @patch("kubernetes.config.load_incluster_config", mocked_load_incluster_config)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod",
        mocked_create_namespaced_pod,
    )
    def test_build_push_image_using_kaniko_incluster(self) -> None:
        """Test build push image using kaniko incluster."""
        os.environ["KUBERNETES_SERVICE_HOST"] = "Incluster"
        builds.template_file = "pubgrade/modules/endpoints/kaniko/template.yaml"
        with self.app.app_context():
            build_push_image_using_kaniko(builds.template_file)
        os.environ["NAMESPACE"] = "pubgrade"
        with self.app.app_context():
            build_push_image_using_kaniko(builds.template_file)
        del os.environ["NAMESPACE"]
        del os.environ["KUBERNETES_SERVICE_HOST"]

    @patch("kubernetes.config.load_kube_config", mocked_load_cluster_config)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod",
        mocked_create_namespaced_pod_echo,
    )
    def test_build_push_image_using_kaniko_logs_no_token(
        self,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Log messages name the created pod, without its environment."""
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        monkeypatch.setattr(
            builds,
            "template_file",
            "pubgrade/modules/endpoints/kaniko/template.yaml",
        )
        deployment_file = tmp_path / "build.yaml"
        create_deployment_YAML(
            dockerfile_location="Dockerfile",
            intermediate_registry_path="registry/image",
            build_context="context",
            deployment_file_location=str(deployment_file),
            config_file_location="config.json",
            project_access_token="project-secret",
        )
        assert "project-secret" in deployment_file.read_text()
        caplog.set_level(logging.DEBUG)
        with self.app.app_context():
            build_push_image_using_kaniko(str(deployment_file))
        name = yaml.safe_load(deployment_file.read_text())["metadata"]["name"]
        assert f"Pod {name} created." in caplog.messages
        assert "project-secret" not in caplog.text

    @patch("kubernetes.config.load_kube_config", mocked_load_cluster_config)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod",
        mocked_create_namespaced_pod_error_body,
    )
    def test_build_push_image_using_kaniko_error_logs_no_body(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Errors of the Kubernetes API are logged by status and reason."""
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        with self.app.app_context(), pytest.raises(CreatePodError) as raised:
            build_push_image_using_kaniko(
                "pubgrade/modules/endpoints/kaniko/template.yaml"
            )
        assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
            (
                logging.ERROR,
                "Creating pod kaniko failed: 422 Unprocessable Entity",
            )
        ]
        # FOCA logs the exception with its context
        assert "pod-secret" not in "".join(traceback.format_exception(raised.value))

    @patch("kubernetes.config.load_kube_config", mocked_load_cluster_config)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod",
        mocked_create_namespaced_pod_error_body,
    )
    def test_build_push_image_using_kaniko_error_without_name(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A manifest without name still gets its error, without context."""
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        deployment_file = tmp_path / "pod.yaml"
        deployment_file.write_text("kind: Pod\nmetadata: {}\n")
        with self.app.app_context(), pytest.raises(CreatePodError) as raised:
            build_push_image_using_kaniko(str(deployment_file))
        assert caplog.messages == ["Creating pod None failed: 422 Unprocessable Entity"]
        assert raised.value.__suppress_context__

    @patch("kubernetes.client.api.core_v1_api.CoreV1Api", mocked_core_v1_api)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.delete_namespaced_pod",
        mocked_delete_namespaced_pod_error_body,
    )
    def test_delete_pod_error_logs_no_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Errors of the Kubernetes API are logged by status and reason."""
        with self.app.app_context(), pytest.raises(DeletePodError) as raised:
            builds.delete_pod("name", "namespace")
        assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
            (
                logging.ERROR,
                "Deleting pod name failed: 422 Unprocessable Entity",
            )
        ]
        assert "pod-secret" not in "".join(traceback.format_exception(raised.value))

    @patch("requests.request")
    def test_trigger_signing_image_error_logs_no_header(
        self,
        request: MagicMock,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Failed requests are logged by type: messages can quote headers."""
        request.side_effect = requests.exceptions.InvalidHeader(
            "Invalid header value: 'Bearer gh-secret'"
        )
        monkeypatch.setenv("GH_ACCESS_TOKEN", " gh-secret\n")
        self.setup()
        with self.app.app_context(), pytest.raises(InternalServerError) as raised:
            builds.trigger_signing_image(
                dockerhub_token="dXNlcjpwYXNzd2Q=",  # user:passwd  gitleaks:allow
                image_path="image",
                pull_tag="registry/image:1",
                push_tag="image:1",
            )
        assert request.call_args.kwargs["headers"]["Authorization"] == (
            "Bearer gh-secret"
        )
        assert caplog.messages == [
            "Triggering the signing of image:1 failed: InvalidHeader"
        ]
        assert "gh-secret" not in "".join(traceback.format_exception(raised.value))


class TestPublish:
    """Tests for publishing prebuilt images, with builds switched off."""

    app = FocaApp(__name__)
    repository = MOCK_REPOSITORY_2
    payload: ClassVar[dict[str, Any]] = {
        "images": [{"name": "elixircloud/tesk-api:v1.2.0"}],
        "head_commit": {"tag": "v1.2.0"},
    }

    def setup_method(self) -> None:
        """Set up the app with a repository and a matching subscription."""
        self.app.config.foca = make_config(
            copy.deepcopy(ENDPOINT_CONFIG),
        )
        self.app.config.foca.endpoints["builds"]["enabled"] = False
        for name in ("repositories", "builds", "subscriptions"):
            self.collection(name).client = mongomock.MongoClient().db.collection
        self.collection("repositories").client.insert_one(
            copy.deepcopy(self.repository)
        )
        self.collection("subscriptions").client.insert_one(
            {**MOCK_SUBSCRIPTION_INFO, "type": "tag", "value": "*"}
        )

    def collection(self, name: str) -> Any:
        """Get the configuration of a collection.

        Args:
            name: Name of the collection.

        Returns:
            The collection's configuration, with its client.
        """
        return self.app.config.foca.db.dbs["pubgradeStore"].collections[name]

    def publish(self, payload: dict[str, Any]) -> Any:
        """Publish an image.

        Args:
            payload: Request data.

        Returns:
            The response, which is the build's identifier.
        """
        with self.app.app_context():
            return register_builds(
                self.repository["id"],
                self.repository["access_token"],
                copy.deepcopy(payload),
            )

    @patch("pubgrade.modules.endpoints.builds.create_build")
    @patch("requests.request")
    def test_publish(self, request: MagicMock, create_build: MagicMock) -> None:
        """Subscribers get the image, and nothing gets built."""
        request.return_value = MagicMock(status_code=200)
        res = self.publish(self.payload)
        create_build.assert_not_called()
        assert json.loads(request.call_args[1]["data"]) == {
            "image_name": "elixircloud/tesk-api",
            "tag": "v1.2.0",
        }
        with self.app.app_context():
            build = get_build_info(res["id"])
        assert build["status"] == "SUCCEEDED"
        assert build["finished_at"] is not None
        assert build["notifications"][0]["result"] == "delivered"

    @patch("requests.request")
    def test_publish_failed_notification(self, request: MagicMock) -> None:
        """A failed notification shows in the build's status."""
        request.return_value = MagicMock(status_code=500)
        res = self.publish(self.payload)
        with self.app.app_context():
            assert get_build_info(res["id"])["status"] == "FAILED"

    def test_publish_without_subscriptions(self) -> None:
        """A repository without subscriptions has nothing to notify."""
        self.collection("repositories").client.update_one(
            {"id": self.repository["id"]},
            {"$unset": {"subscription_list": ""}},
        )
        res = self.publish(self.payload)
        with self.app.app_context():
            build = get_build_info(res["id"])
        assert build["status"] == "SUCCEEDED"
        assert build["notifications"] == []

    @pytest.mark.parametrize(
        "extra",
        [
            {"dockerhub_token": "token"},
            {"images": [{"name": "org/image:1", "location": "./Dockerfile"}]},
        ],
    )
    def test_publish_rejects_build_requests(self, extra: dict[str, Any]) -> None:
        """Requests that ask for a build are rejected."""
        with pytest.raises(BuildsDisabled):
            self.publish({**self.payload, **extra})

    @pytest.mark.parametrize(
        "images",
        [
            [],
            [{"name": "org/image:1"}, {"name": "org/other:1"}],
            [{"name": "org/image"}],
            [{"name": "registry.example.org:5000/image"}],
            [{"name": "org/image@sha256:abc"}],
            [{"name": "org/image:1 --flag"}],
        ],
    )
    def test_publish_rejects_invalid_images(self, images: list[dict[str, str]]) -> None:
        """Exactly one image with a tag is required."""
        with pytest.raises(InvalidImage):
            self.publish({**self.payload, "images": images})

    @patch("requests.request")
    def test_publish_registry_with_port(self, request: MagicMock) -> None:
        """A registry's port isn't mistaken for a tag."""
        request.return_value = MagicMock(status_code=200)
        self.publish(
            {
                **self.payload,
                "images": [{"name": "registry.example.org:5000/image:1"}],
            }
        )
        assert json.loads(request.call_args[1]["data"]) == {
            "image_name": "registry.example.org:5000/image",
            "tag": "1",
        }

    def test_publish_unauthorized_before_validation(self) -> None:
        """A wrong token gets a 401, whatever the request is."""
        with self.app.app_context(), pytest.raises(Unauthorized):
            register_builds(self.repository["id"], "wrong", {"images": []})

    @patch("pubgrade.modules.endpoints.builds.create_build")
    def test_build_rejects_image_without_tag(self, create_build: MagicMock) -> None:
        """Also with builds on, images need a tag."""
        self.app.config.foca.endpoints["builds"]["enabled"] = True
        with pytest.raises(InvalidImage):
            self.publish(
                {
                    **self.payload,
                    "images": [{"name": "org/image", "location": "./Dockerfile"}],
                }
            )
        create_build.assert_not_called()

    @pytest.mark.parametrize(
        "images",
        [
            [],
            [{"location": "./Dockerfile"}],
            [{"name": "Org/image:1"}],
            [{"name": "org/image:1:2"}],
            [{"name": "registry.example.org/Org/image:1"}],
        ],
    )
    def test_build_rejects_invalid_images(self, images: list[dict[str, str]]) -> None:
        """Requests without valid image references are rejected."""
        self.app.config.foca.endpoints["builds"]["enabled"] = True
        with pytest.raises(InvalidImage):
            self.publish({**self.payload, "images": images})

    @pytest.mark.parametrize(
        "name",
        [
            "image:1",
            "org/image:1.0-rc_1",
            "registry.example.org/org/image:1",
            "registry.example.org:5000/org/image:1",
            "registry:5000/org/image:1",
            "localhost/org/image:1",
        ],
    )
    def test_image_with_tag_accepts_references(self, name: str) -> None:
        """Valid references pass, with or without a registry."""
        assert IMAGE_WITH_TAG.fullmatch(name)

    def test_build_completed_rejected(self) -> None:
        """`PUT` on a build is rejected."""
        with self.app.app_context(), pytest.raises(BuildsDisabled):
            build_completed(
                self.repository["id"],
                "build",
                self.repository["access_token"],
            )


class TestCancelBuild:
    """Tests for withdrawing builds (`cancel_build`)."""

    app = FocaApp(__name__)
    repository = MOCK_REPOSITORY_2
    build_id = MOCK_BUILD_INFO["id"]

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Set up the app with a repository and its builds; builds are on.

        Calls to Kubernetes are replaced by mocks, and the builds' files are
        in a temporary directory.

        Args:
            monkeypatch: Fixture to replace the calls to Kubernetes.
            tmp_path: Temporary directory for the builds' files.
        """
        self.app.config.foca = make_config(copy.deepcopy(ENDPOINT_CONFIG))
        for name in ("repositories", "builds", "subscriptions"):
            self.collection(name).client = mongomock.MongoClient().db[name]
        self.collection("repositories").client.insert_one(
            copy.deepcopy(self.repository)
        )
        for build in (MOCK_BUILD_INFO, MOCK_BUILD_INFO_2):
            self.collection("builds").client.insert_one(copy.deepcopy(build))
        self.base_dir = tmp_path
        monkeypatch.setattr(builds, "BASE_DIR", str(tmp_path))
        self.load = MagicMock()
        monkeypatch.setattr(builds, "load_cluster_config", self.load)
        self.delete_pod = MagicMock()
        monkeypatch.setattr(builds, "delete_pod", self.delete_pod)
        monkeypatch.delenv("NAMESPACE", raising=False)

    def collection(self, name: str) -> Any:
        """Get the configuration of a collection.

        Args:
            name: Name of the collection.

        Returns:
            The collection's configuration, with its client.
        """
        return self.app.config.foca.db.dbs["pubgradeStore"].collections[name]

    def stored(self, build_id: str | None = None) -> dict[str, Any]:
        """Get a stored build.

        Args:
            build_id: Identifier of the build; by default, `build_id`.

        Returns:
            The build, as stored.
        """
        build: dict[str, Any] = self.collection("builds").client.find_one(
            {"id": build_id or self.build_id}, {"_id": False}
        )
        return build

    def cancel(
        self, build_id: str | None = None, access_token: str | None = None
    ) -> Any:
        """Withdraw a build of the repository.

        Args:
            build_id: Identifier of the build; by default, `build_id`.
            access_token: Access token; by default, the repository's.

        Returns:
            The response.
        """
        with self.app.app_context():
            return cancel_build(
                self.repository["id"],
                build_id or self.build_id,
                access_token or self.repository["access_token"],
            )

    def test_cancel_running_build(self) -> None:
        """A running build is stopped and marked; its record stays listed."""
        (self.base_dir / self.build_id).mkdir()
        assert self.cancel() == {"id": self.build_id}
        build = self.stored()
        assert build["status"] == "CANCELED"
        assert build["finished_at"] is not None
        self.delete_pod.assert_called_once_with(
            self.build_id, "default", missing_ok=True
        )
        assert list(self.base_dir.iterdir()) == []
        with self.app.app_context():
            listed = get_builds(self.repository["id"])
        assert [item["id"] for item in listed] == self.repository["build_list"]
        assert listed[0]["status"] == "CANCELED"

    def test_cancel_finished_build(self) -> None:
        """A finished build is only marked, and keeps its end."""
        finished_at = "2021-08-04T18:00:00+00:00"
        self.collection("builds").client.update_one(
            {"id": self.build_id},
            {"$set": {"status": "SUCCEEDED", "finished_at": finished_at}},
        )
        self.cancel()
        build = self.stored()
        assert build["status"] == "CANCELED"
        assert build["finished_at"] == finished_at
        self.load.assert_not_called()
        self.delete_pod.assert_not_called()

    def test_cancel_with_builds_off(self) -> None:
        """With builds switched off, no pods are touched."""
        self.app.config.foca.endpoints["builds"]["enabled"] = False
        self.cancel()
        assert self.stored()["status"] == "CANCELED"
        self.load.assert_not_called()
        self.delete_pod.assert_not_called()

    def test_cancel_other_builds_unchanged(self) -> None:
        """Other builds of the repository stay as they are."""
        self.cancel()
        assert self.stored(MOCK_BUILD_INFO_2["id"])["status"] == "QUEUED"

    def test_cancel_twice(self) -> None:
        """A build that is canceled already gets a 409."""
        self.cancel()
        self.delete_pod.reset_mock()
        with pytest.raises(BuildCanceled):
            self.cancel()
        self.delete_pod.assert_not_called()

    @pytest.mark.parametrize("build_id", ["unknown", "repo12abcdef"])
    def test_cancel_unknown_build(self, build_id: str) -> None:
        """Unknown builds, and builds of other repositories, get a 404.

        Args:
            build_id: Identifier of the build.
        """
        self.collection("builds").client.insert_one(
            {**MOCK_BUILD_INFO, "id": "repo12abcdef"}
        )
        with pytest.raises(BuildNotFound):
            self.cancel(build_id)
        assert self.stored("repo12abcdef")["status"] == "QUEUED"

    def test_cancel_listed_build_is_gone(self) -> None:
        """A build listed at the repository, but no longer stored, gets a 404."""
        self.collection("builds").client.delete_one({"id": self.build_id})
        with pytest.raises(BuildNotFound):
            self.cancel()

    def test_cancel_unknown_repository(self) -> None:
        """A build of an unknown repository gets a 404."""
        with self.app.app_context(), pytest.raises(RepositoryNotFound):
            cancel_build("unknown", self.build_id, self.repository["access_token"])

    def test_cancel_unauthorized(self) -> None:
        """Only the repository's access token withdraws its builds."""
        with pytest.raises(Unauthorized):
            self.cancel(access_token="wrong")
        assert self.stored()["status"] == "QUEUED"

    def test_cancel_stop_fails(self) -> None:
        """If the build can't be stopped, it stays canceled, marked for a retry.

        A repeated request stops it again instead of getting a 409, and the
        mark isn't part of responses.
        """
        self.delete_pod.side_effect = DeletePodError
        with pytest.raises(DeletePodError):
            self.cancel()
        build = self.stored()
        assert build["status"] == "CANCELED"
        assert build["finished_at"] is not None
        assert build["stopping"] is True
        with self.app.app_context():
            assert "stopping" not in get_build_info(self.build_id)
        self.delete_pod.side_effect = None
        self.delete_pod.reset_mock()
        assert self.cancel() == {"id": self.build_id}
        self.delete_pod.assert_called_once_with(
            self.build_id, "default", missing_ok=True
        )
        assert "stopping" not in self.stored()
        with pytest.raises(BuildCanceled):
            self.cancel()

    @patch("pubgrade.modules.endpoints.builds.notify_all_subscriptions")
    @patch("pubgrade.modules.endpoints.builds.trigger_signing_image")
    def test_completion_of_canceled_build(
        self, trigger: MagicMock, notify: MagicMock
    ) -> None:
        """The completion of a canceled build gets a 409, and notifies no one.

        A pod that is left (e.g., that started after the cancellation) is
        removed, so that it isn't reported again.

        Args:
            trigger: Mock of the signing of the image.
            notify: Mock of the notification of the subscriptions.
        """
        self.cancel()
        self.delete_pod.reset_mock()
        with self.app.app_context(), pytest.raises(BuildCanceled):
            build_completed(
                self.repository["id"],
                self.build_id,
                self.repository["access_token"],
            )
        assert self.stored()["status"] == "CANCELED"
        trigger.assert_not_called()
        notify.assert_not_called()
        self.delete_pod.assert_called_once_with(
            self.build_id, "default", missing_ok=True
        )

    @patch("pubgrade.modules.endpoints.builds.remove_files")
    @patch("pubgrade.modules.endpoints.builds.notify_all_subscriptions")
    def test_completion_canceled_meanwhile(
        self, notify: MagicMock, remove_files: MagicMock
    ) -> None:
        """A build canceled while its image is signed counts as finished.

        Its completion was recorded before the signing, so the cancellation
        only marks it, without stopping it; no one is notified.

        Args:
            notify: Mock of the notification of the subscriptions.
            remove_files: Mock of the removal of the build's pod and files.
        """
        finished_at: list[Any] = []

        def cancel_meanwhile(**kwargs: Any) -> None:
            """Cancel the build while its image is signed.

            Args:
                **kwargs: Arguments of the signing.
            """
            finished_at.append(self.stored()["finished_at"])
            self.cancel()

        with (
            patch(
                "pubgrade.modules.endpoints.builds.trigger_signing_image",
                side_effect=cancel_meanwhile,
            ) as trigger,
            self.app.app_context(),
        ):
            res = build_completed(
                self.repository["id"],
                self.build_id,
                self.repository["access_token"],
            )
        assert res == {"id": self.build_id}
        trigger.assert_called_once()
        build = self.stored()
        assert build["status"] == "CANCELED"
        assert build["finished_at"] == finished_at[0] is not None
        self.delete_pod.assert_not_called()
        remove_files.assert_called_once()
        notify.assert_not_called()

    @patch("pubgrade.modules.endpoints.builds.notify_all_subscriptions")
    @patch(
        "pubgrade.modules.endpoints.builds.trigger_signing_image",
        side_effect=InternalServerError,
    )
    def test_completion_signing_fails(
        self, trigger: MagicMock, notify: MagicMock
    ) -> None:
        """If the signing can't be triggered, the build is as before.

        The pod reports it again, and it can be canceled as a running build.

        Args:
            trigger: Mock of the signing of the image.
            notify: Mock of the notification of the subscriptions.
        """
        with self.app.app_context(), pytest.raises(InternalServerError):
            build_completed(
                self.repository["id"],
                self.build_id,
                self.repository["access_token"],
            )
        build = self.stored()
        assert build["status"] == "QUEUED"
        assert build["finished_at"] is None
        notify.assert_not_called()

    @patch("pubgrade.modules.endpoints.builds.create_build")
    def test_cancel_while_starting(self, create_build: MagicMock) -> None:
        """A build canceled before its pod exists is stopped once it does.

        Args:
            create_build: Mock of the start of the build, which cancels it.
        """
        build_ids: list[str] = []

        def cancel_meanwhile(**kwargs: Any) -> None:
            """Cancel the build while it starts.

            Args:
                **kwargs: Arguments of the start.
            """
            build_ids.append(kwargs["build_id"])
            self.cancel(kwargs["build_id"])

        create_build.side_effect = cancel_meanwhile
        with self.app.app_context():
            res = register_builds(
                self.repository["id"],
                self.repository["access_token"],
                copy.deepcopy(MOCK_BUILD_PAYLOAD),
            )
        assert res == {"id": build_ids[0]}
        assert self.stored(build_ids[0])["status"] == "CANCELED"
        # By the cancellation and again after the start
        assert self.delete_pod.call_count == 2

    @patch("pubgrade.modules.endpoints.builds.create_build")
    def test_cancel_while_starting_start_fails(self, create_build: MagicMock) -> None:
        """A build canceled while it starts is kept even if the start fails.

        Args:
            create_build: Mock of the start of the build, which cancels it.
        """
        build_ids: list[str] = []

        def cancel_meanwhile(**kwargs: Any) -> None:
            """Cancel the build while it starts, then fail.

            Args:
                **kwargs: Arguments of the start.

            Raises:
                GitCloningError: Always, as cloning failed.
            """
            build_ids.append(kwargs["build_id"])
            self.cancel(kwargs["build_id"])
            raise GitCloningError

        create_build.side_effect = cancel_meanwhile
        with self.app.app_context(), pytest.raises(GitCloningError):
            register_builds(
                self.repository["id"],
                self.repository["access_token"],
                copy.deepcopy(MOCK_BUILD_PAYLOAD),
            )
        assert self.stored(build_ids[0])["status"] == "CANCELED"
        repository = self.collection("repositories").client.find_one(
            {"id": self.repository["id"]}
        )
        assert build_ids[0] in repository["build_list"]

    def test_stop_canceled_build_logs_errors(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Errors stopping a canceled build are logged, not raised.

        Args:
            caplog: Fixture to capture the logs.
        """
        self.collection("builds").client.update_one(
            {"id": self.build_id}, {"$set": {"status": "CANCELED"}}
        )
        self.delete_pod.side_effect = DeletePodError
        with self.app.app_context(), caplog.at_level(logging.ERROR):
            stop_canceled_build(self.build_id)
        assert "could not be stopped: DeletePodError" in caplog.text

    def test_cancel_files_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the build's files can't be removed, it stays marked for a retry.

        Args:
            monkeypatch: Fixture to make the removal fail.
        """
        (self.base_dir / self.build_id).mkdir()
        rmtree = shutil.rmtree

        def fail(path: str, **kwargs: Any) -> NoReturn:
            """Fail to remove a directory.

            Args:
                path: The directory.
                **kwargs: Other arguments.

            Raises:
                PermissionError: Always.
            """
            raise PermissionError(path)

        monkeypatch.setattr(builds.shutil, "rmtree", fail)
        with pytest.raises(PermissionError):
            self.cancel()
        assert self.stored()["stopping"] is True
        monkeypatch.setattr(builds.shutil, "rmtree", rmtree)
        assert self.cancel() == {"id": self.build_id}
        assert list(self.base_dir.iterdir()) == []
        assert "stopping" not in self.stored()

    @patch("pubgrade.modules.endpoints.builds.notify_all_subscriptions")
    def test_publish_canceled_meanwhile(self, notify: MagicMock) -> None:
        """A prebuilt image canceled while subscribers are notified stays so.

        Args:
            notify: Mock of the notification of the subscriptions.
        """

        def cancel_meanwhile(*args: Any) -> list[dict[str, Any]]:
            """Cancel the build while its subscribers are notified.

            Args:
                *args: Arguments of the notification.

            Returns:
                No results.
            """
            self.cancel()
            return []

        notify.side_effect = cancel_meanwhile
        self.app.config.foca.endpoints["builds"]["enabled"] = False
        with self.app.app_context():
            publish_prebuilt_image(self.build_id, "org/image:1", [])
        assert self.stored()["status"] == "CANCELED"

    def test_stop_builds_skips_canceled(self) -> None:
        """Canceled builds without files need no calls to Kubernetes.

        They were stopped when they were canceled, e.g., before their
        repository is deleted.
        """
        self.collection("builds").client.update_many(
            {}, {"$set": {"status": "CANCELED"}}
        )
        with self.app.app_context():
            stop_builds(self.repository["build_list"])
        self.load.assert_not_called()
