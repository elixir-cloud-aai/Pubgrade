"""Tests for /builds endpoint"""

import copy
import json
import logging
import os
import shutil
import traceback
from typing import Any
from unittest.mock import MagicMock, patch

from flask import Flask
from foca.models.config import Config, MongoConfig
from kubernetes.client import ApiException
import mongomock
from pymongo.errors import DuplicateKeyError
import pytest
import requests
from werkzeug.exceptions import InternalServerError, Unauthorized
import yaml

from pubgrade.errors.exceptions import (
    BuildNotFound,
    BuildsDisabled,
    CreatePodError,
    DeletePodError,
    GitCloningError,
    InvalidImage,
    RepositoryNotFound,
)
import pubgrade.modules.endpoints.builds as builds
from pubgrade.modules.endpoints.builds import (
    IMAGE_WITH_TAG,
    build_completed,
    build_push_image_using_kaniko,
    create_build,
    create_deployment_YAML,
    create_dockerhub_config_file,
    get_build_info,
    get_builds,
    git_clone_and_checkout,
    register_builds,
    remove_files,
)
from tests.mock_data import (
    ENDPOINT_CONFIG,
    MOCK_BUILD_INFO,
    MOCK_BUILD_INFO_2,
    MOCK_BUILD_PAYLOAD,
    MOCK_REPOSITORIES,
    MOCK_REPOSITORY_2,
    MOCK_SUBSCRIPTION_INFO,
    MONGO_CONFIG,
)


def mocked_create_build(
    repo_url,
    branch,
    commit,
    base_dir,
    build_id,
    dockerfile_location,
    intermediate_registry_path,
    dockerhub_token,
    project_access_token,
):
    return "working fine"


def mocked_remove_files(dir_location: str, pod_name: str, namespace: str):
    return "removed"


def mocked_notify_subscriptions(subscription_id: str, image: str, build_id: str):
    return "Notified"


def mocked_delete_pod(name, namespace):
    return "Pod deleted."


def mocked_delete_namespaced_pod(self, name: str, namespace: str, **kwargs: Any):
    return "Pod deleted."


def mocked_delete_namespaced_pod_error(self, name: str, namespace: str, **kwargs: Any):
    raise ApiException


def mocked_request_api(method, url, data, headers, **kwargs):
    return MagicMock(status_code=200)


def mocked_load_cluster_config(
    config_file=None,
    context=None,
    client_configuration=None,
    persist_config=True,
):
    return "Loaded successfully"


def mocked_load_incluster_config():
    return "Loaded successfully"


def mocked_core_v1_api():
    return "v1 API"


def mocked_create_namespaced_pod(self, namespace: str, body: Any, **kwargs: Any):
    return {"metadata": {"name": "kaniko"}}


def mocked_create_namespaced_pod_error(self, namespace: str, body: Any, **kwargs: Any):
    raise ApiException


def mocked_create_namespaced_pod_echo(self, namespace: str, body: Any, **kwargs: Any):
    """Return the created pod, as the Kubernetes API does."""
    return body


def _api_exception_with_body() -> ApiException:
    """Get an error of the Kubernetes API whose body has a secret."""
    exc = ApiException(status=422, reason="Unprocessable Entity")
    exc.body = '{"message": "value pod-secret is invalid"}'
    return exc


def mocked_create_namespaced_pod_error_body(
    self, namespace: str, body: Any, **kwargs: Any
):
    """Fail with a response body that has a secret."""
    raise _api_exception_with_body()


def mocked_delete_namespaced_pod_error_body(
    self, name: str, namespace: str, **kwargs: Any
):
    """Fail with a response body that has a secret."""
    raise _api_exception_with_body()


def mocked_load_kube_config(
    config_file=None,
    context=None,
    client_configuration=None,
    persist_config=True,
):
    return "success"


def mocked_get_kube_config_loader(
    filename=None, config_dict=None, persist_config=False, **kwargs
):
    return MockKubeConfigLoader


class MockKubeConfigLoader:
    def load_and_set(self):
        return "success"


class TestBuild:
    app = Flask(__name__)

    repository_url = "https://github.com/elixir-cloud-aai/drs-filer"
    id_length = 0

    def setup(self):
        self.app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
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

    def setup_with_build(self):
        self.setup()
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO)
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one(MOCK_BUILD_INFO_2)

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds(self):
        self.setup()
        with self.app.app_context():
            res = register_builds(
                MOCK_REPOSITORIES[1]["id"],
                MOCK_REPOSITORIES[1]["access_token"],
                MOCK_BUILD_PAYLOAD,
            )
            assert isinstance(res, dict)
            # assert if build_id's 0 to `id_length` characters are same as repository id. (build = repo_id + random characters)
            assert (
                "id" in res
                and res["id"][: self.id_length] == MOCK_REPOSITORIES[1]["id"]
            )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_logs_no_token(self, caplog):
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
    def test_register_builds_branch_only(self):
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
            # assert if build_id's 0 to `id_length` characters are same as repository id. (build = repo_id + random characters)
            assert (
                "id" in res
                and res["id"][: self.id_length] == MOCK_REPOSITORIES[1]["id"]
            )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_tag(self):
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
            # assert if build_id's 0 to `id_length` characters are same as repository id. (build = repo_id + random characters)
            assert (
                "id" in res
                and res["id"][: self.id_length] == MOCK_REPOSITORIES[1]["id"]
            )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_duplicate_key_error(self):
        self.setup()
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "builds"
        ].client.insert_one = mock_resp
        with self.app.app_context():
            with pytest.raises(InternalServerError):
                register_builds(
                    MOCK_REPOSITORIES[1]["id"],
                    MOCK_REPOSITORIES[1]["access_token"],
                    MOCK_BUILD_PAYLOAD,
                )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_unauthorized(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                register_builds(
                    MOCK_REPOSITORIES[1]["id"],
                    "access_token",
                    MOCK_BUILD_PAYLOAD,
                )

    @patch("pubgrade.modules.endpoints.builds.create_build", mocked_create_build)
    def test_register_builds_repository_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                register_builds(
                    "id",
                    MOCK_REPOSITORIES[1]["access_token"],
                    MOCK_BUILD_PAYLOAD,
                )

    def test_get_builds(self):
        self.setup_with_build()
        with self.app.app_context():
            res = get_builds(MOCK_REPOSITORIES[1]["id"])
            assert isinstance(res, list)
            assert len(res) == 2

    def test_get_builds_build_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(BuildNotFound):
                get_builds(MOCK_REPOSITORIES[1]["id"])

    def test_get_builds_repository_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                get_builds("abcd")

    def test_get_build_info(self):
        self.setup_with_build()
        with self.app.app_context():
            res = get_build_info(MOCK_BUILD_INFO["id"])
            assert isinstance(res, dict)
            assert "finished_at" in res
            assert "head_commit" in res
            assert "started_at" in res
            assert "branch" in res["head_commit"]

    def test_get_build_info_old_format(self):
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

    def test_get_build_info_build_not_found(self):
        self.setup_with_build()
        with self.app.app_context():
            with pytest.raises(BuildNotFound):
                get_build_info("abcd")

    def test_git_clone_and_checkout(self):
        clone_path = git_clone_and_checkout(
            repo_url=self.repository_url,
            branch="dev",
            commit="122c34d",
            base_dir=".",
            build_id="build123",
        )
        assert clone_path == "./build123/drs-filer"
        shutil.rmtree("./build123")

    def test_git_clone_and_checkout_without_branch(self):
        clone_path = git_clone_and_checkout(
            repo_url=self.repository_url,
            branch="",
            commit="122c34d",
            base_dir=".",
            build_id="build123",
        )
        assert clone_path == "./build123/drs-filer"
        shutil.rmtree("./build123")

    def test_git_clone_and_checkout_type_error(self):
        with pytest.raises(GitCloningError):
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch="master",
                commit="8cd58b",
                base_dir=".",
                build_id="build123",
            )
        shutil.rmtree("./build123")

    def test_git_clone_and_checkout_git_command_error(self):
        with pytest.raises(GitCloningError):
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch="dev",
                commit="122c34d",
                base_dir=".",
                build_id="build123",
            )
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch="dev",
                commit="122c34d",
                base_dir=".",
                build_id="build123",
            )
        shutil.rmtree("./build123")

    def test_create_deployment_yaml(self):
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

    def test_create_deployment_yaml_if_env_present(self):
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

    def test_create_deployment_yaml_os_error(self):
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

    def test_create_dockerhub_config_file(self):
        self.setup()
        with self.app.app_context():
            create_dockerhub_config_file("token", "config.json")
        assert os.path.isfile("config.json")
        os.remove("config.json")

    @patch("pubgrade.modules.endpoints.builds.build_push_image_using_kaniko")
    def test_create_build(self, push_image):
        builds.template_file = "pubgrade/modules/endpoints/kaniko/template.yaml"
        os.mkdir("basedir")
        os.mkdir("basedir/drs-filer")
        f = open("basedir/drs-filer/Dockerfile", "w")
        f.write("test dockerfile")
        f.close()
        self.setup()
        with self.app.app_context():
            create_build(
                repo_url=self.repository_url,
                branch="dev",
                commit="122c34d",
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

    @patch("pubgrade.modules.endpoints.builds.remove_files", mocked_remove_files)
    @patch("requests.request", mocked_request_api)
    def test_build_completed(self):
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
    def test_build_completed_removes_pod_in_own_namespace(self, remove_files):
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

    def test_build_completed_build_of_other_repository(self):
        """A repository's token only completes that repository's builds."""
        self.setup_with_build()
        builds_collection = (
            self.app.config.foca.db.dbs["pubgradeStore"].collections["builds"].client
        )
        builds_collection.insert_one({"id": "other", "status": "QUEUED"})
        with self.app.app_context():
            with pytest.raises(BuildNotFound):
                build_completed(
                    MOCK_REPOSITORY_2["id"],
                    "other",
                    MOCK_REPOSITORY_2["access_token"],
                )
        assert builds_collection.find_one({"id": "other"})["status"] == "QUEUED"

    def test_build_completed_listed_build_is_gone(self):
        """A build listed at the repository, but no longer stored, isn't found."""
        self.setup()
        with self.app.app_context():
            with pytest.raises(BuildNotFound):
                build_completed(
                    MOCK_REPOSITORY_2["id"],
                    MOCK_REPOSITORY_2["build_list"][0],
                    MOCK_REPOSITORY_2["access_token"],
                )

    def test_build_completed_build_not_found(self):
        self.setup_with_build()
        with self.app.app_context():
            with pytest.raises(BuildNotFound):
                build_completed(
                    MOCK_REPOSITORY_2["id"],
                    "build12",
                    MOCK_REPOSITORY_2["access_token"],
                )

    def test_build_completed_unauthorized(self):
        self.setup_with_build()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                build_completed(
                    MOCK_REPOSITORY_2["id"],
                    MOCK_REPOSITORY_2["build_list"][0],
                    "123",
                )

    def test_build_completed_repository_not_found(self):
        self.setup_with_build()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                build_completed(
                    "repo125",
                    MOCK_REPOSITORY_2["build_list"][0],
                    MOCK_REPOSITORY_2["access_token"],
                )

    @patch("pubgrade.modules.endpoints.builds.delete_pod", mocked_delete_pod)
    def test_remove_files(self):
        os.mkdir("build123")
        remove_files("build123", "pod_name", "namespace")
        assert not os.path.isdir("build123")

    @patch("kubernetes.config.load_kube_config", mocked_load_cluster_config)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod",
        mocked_create_namespaced_pod,
    )
    def test_build_push_image_using_kaniko(self):
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
    def test_build_push_image_using_kaniko_create_pod_error(self):
        builds.template_file = "pubgrade/modules/endpoints/kaniko/template.yaml"
        with self.app.app_context():
            with pytest.raises(CreatePodError):
                build_push_image_using_kaniko(builds.template_file)

    @patch("kubernetes.client.api.core_v1_api.CoreV1Api", mocked_core_v1_api)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.delete_namespaced_pod",
        mocked_delete_namespaced_pod,
    )
    def test_delete_pod(self):
        with self.app.app_context():
            builds.delete_pod("name", "namespace")

    @patch("kubernetes.client.api.core_v1_api.CoreV1Api", mocked_core_v1_api)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.delete_namespaced_pod",
        mocked_delete_namespaced_pod_error,
    )
    def test_delete_pod_api_error(self):
        with self.app.app_context():
            with pytest.raises(DeletePodError):
                builds.delete_pod("name", "namespace")

    @patch("kubernetes.config.load_incluster_config", mocked_load_incluster_config)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod",
        mocked_create_namespaced_pod,
    )
    def test_build_push_image_using_kaniko_incluster(self):
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
        self, caplog, tmp_path, monkeypatch
    ):
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
        self, caplog, monkeypatch
    ):
        """Errors of the Kubernetes API are logged by status and reason."""
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        with self.app.app_context():
            with pytest.raises(CreatePodError) as raised:
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
        self, caplog, monkeypatch, tmp_path
    ):
        """A manifest without name still gets its error, without context."""
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        deployment_file = tmp_path / "pod.yaml"
        deployment_file.write_text("kind: Pod\nmetadata: {}\n")
        with self.app.app_context():
            with pytest.raises(CreatePodError) as raised:
                build_push_image_using_kaniko(str(deployment_file))
        assert caplog.messages == ["Creating pod None failed: 422 Unprocessable Entity"]
        assert raised.value.__suppress_context__

    @patch("kubernetes.client.api.core_v1_api.CoreV1Api", mocked_core_v1_api)
    @patch(
        "kubernetes.client.api.core_v1_api.CoreV1Api.delete_namespaced_pod",
        mocked_delete_namespaced_pod_error_body,
    )
    def test_delete_pod_error_logs_no_body(self, caplog):
        """Errors of the Kubernetes API are logged by status and reason."""
        with self.app.app_context():
            with pytest.raises(DeletePodError) as raised:
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
        self, request, caplog, monkeypatch
    ):
        """Failed requests are logged by type: messages can quote headers."""
        request.side_effect = requests.exceptions.InvalidHeader(
            "Invalid header value: 'Bearer gh-secret'"
        )
        monkeypatch.setenv("GH_ACCESS_TOKEN", " gh-secret\n")
        self.setup()
        with self.app.app_context():
            with pytest.raises(InternalServerError) as raised:
                builds.trigger_signing_image(
                    dockerhub_token="dXNlcjpwYXNzd2Q=",
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

    app = Flask(__name__)
    repository = MOCK_REPOSITORY_2
    payload = {
        "images": [{"name": "elixircloud/tesk-api:v1.2.0"}],
        "head_commit": {"tag": "v1.2.0"},
    }

    def setup_method(self):
        """Set up the app with a repository and a matching subscription."""
        self.app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG),
            endpoints=copy.deepcopy(ENDPOINT_CONFIG),
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

    def collection(self, name):
        """Get the configuration of a collection.

        Args:
            name: Name of the collection.

        Returns:
            The collection's configuration, with its client.
        """
        return self.app.config.foca.db.dbs["pubgradeStore"].collections[name]

    def publish(self, payload):
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
    def test_publish(self, request, create_build):
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
    def test_publish_failed_notification(self, request):
        """A failed notification shows in the build's status."""
        request.return_value = MagicMock(status_code=500)
        res = self.publish(self.payload)
        with self.app.app_context():
            assert get_build_info(res["id"])["status"] == "FAILED"

    def test_publish_without_subscriptions(self):
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
    def test_publish_rejects_build_requests(self, extra):
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
    def test_publish_rejects_invalid_images(self, images):
        """Exactly one image with a tag is required."""
        with pytest.raises(InvalidImage):
            self.publish({**self.payload, "images": images})

    @patch("requests.request")
    def test_publish_registry_with_port(self, request):
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

    def test_publish_unauthorized_before_validation(self):
        """A wrong token gets a 401, whatever the request is."""
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                register_builds(self.repository["id"], "wrong", {"images": []})

    @patch("pubgrade.modules.endpoints.builds.create_build")
    def test_build_rejects_image_without_tag(self, create_build):
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
    def test_build_rejects_invalid_images(self, images):
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
    def test_image_with_tag_accepts_references(self, name):
        """Valid references pass, with or without a registry."""
        assert IMAGE_WITH_TAG.fullmatch(name)

    def test_build_completed_rejected(self):
        """`PUT` on a build is rejected."""
        with self.app.app_context():
            with pytest.raises(BuildsDisabled):
                build_completed(
                    self.repository["id"],
                    "build",
                    self.repository["access_token"],
                )
