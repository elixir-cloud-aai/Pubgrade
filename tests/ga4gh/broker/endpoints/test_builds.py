"""Tests for /builds endpoint """
import os
import shutil
from unittest.mock import patch, MagicMock

import mongomock
import pytest
from flask import Flask
from foca.models.config import Config, MongoConfig
from typing import Any

from kubernetes.client import ApiException
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized, InternalServerError

from broker.errors.exceptions import (
    RepositoryNotFound,
    BuildNotFound,
    CreatePodError,
    DeletePodError, WrongGitCommand
)
from broker.ga4gh.broker.endpoints.builds import (
    register_builds,
    get_builds,
    get_build_info,
    git_clone_and_checkout,
    create_deployment_YAML,
    create_dockerhub_config_file,
    create_build,
    build_completed,
    remove_files,
    build_push_image_using_kaniko
)
import broker.ga4gh.broker.endpoints.builds as builds
from tests.ga4gh.mock_data import (
    ENDPOINT_CONFIG,
    MONGO_CONFIG,
    MOCK_REPOSITORIES,
    MOCK_BUILD_PAYLOAD,
    MOCK_BUILD_INFO,
    MOCK_BUILD_INFO_2,
    MOCK_REPOSITORY_2,
    MOCK_SUBSCRIPTION_INFO
)


def mocked_create_build(repo_url, branch, commit, base_dir, build_id,
                        dockerfile_location, registry_destination,
                        dockerhub_token,
                        project_access_token):
    return 'working fine'


def mocked_build_push_image_using_kaniko(deployment_file_location):
    return 0


def mocked_remove_files(dir_location: str, pod_name: str, namespace: str):
    return "removed"


def mocked_notify_subscriptions(subscription_id: str, image: str,
                                build_id: str):
    return "Notified"


def mocked_delete_pod(name, namespace):
    return "Pod deleted."


def mocked_delete_namespaced_pod(self, name: str, namespace: str,
                                 **kwargs: Any):
    return "Pod deleted."


def mocked_delete_namespaced_pod_error(self, name: str, namespace: str,
                                       **kwargs: Any):
    raise ApiException


def mocked_request_api(method, url, data, headers):
    return 'successful'


def mocked_load_cluster_config(client_configuration=None,
                               try_refresh_token=True):
    return 'Loaded successfully'


def mocked_load_incluster_config():
    return 'Loaded successfully'


def mocked_core_v1_api():
    return 'v1 API'


def mocked_create_namespaced_pod(self, namespace: str, body: Any,
                                 **kwargs: Any):
    return {"metadata": {"name": "kaniko"}}


def mocked_create_namespaced_pod_error(self, namespace: str, body: Any,
                                       **kwargs: Any):
    raise ApiException


class TestBuild:
    app = Flask(__name__)

    repository_url = "https://github.com/akash2237778/Broker-test"

    def setup(self):
        self.app.config['FOCA'] = \
            Config(db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['repositories'].client = mongomock.MongoClient(
        ).db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config['FOCA'].db.dbs['brokerStore']. \
                collections['repositories'].client.insert_one(
                repository).inserted_id
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['builds'].client = mongomock.MongoClient(
        ).db.collection

    def setup_with_build(self):
        self.setup()
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['builds'].client.insert_one(
            MOCK_BUILD_INFO).inserted_id
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['builds'].client.insert_one(
            MOCK_BUILD_INFO_2).inserted_id

    @patch('broker.ga4gh.broker.endpoints.builds.create_build',
           mocked_create_build)
    def test_register_builds(self):
        self.setup()
        with self.app.app_context():
            res = register_builds(MOCK_REPOSITORIES[1]['id'],
                                  MOCK_REPOSITORIES[1]['access_token'],
                                  MOCK_BUILD_PAYLOAD)
            assert isinstance(res, dict)
            assert 'id' in res and res['id'][:6] == MOCK_REPOSITORIES[1]['id']

    @patch('broker.ga4gh.broker.endpoints.builds.create_build',
           mocked_create_build)
    def test_register_builds_duplicate_key_error(self):
        self.setup()
        mock_resp = MagicMock(side_effect=DuplicateKeyError(''))
        self.app.config['FOCA'].db.dbs['brokerStore'].collections['builds']. \
            client.insert_one = mock_resp
        with self.app.app_context():
            with pytest.raises(InternalServerError):
                register_builds(MOCK_REPOSITORIES[1]['id'],
                                MOCK_REPOSITORIES[1]['access_token'],
                                MOCK_BUILD_PAYLOAD)

    @patch('broker.ga4gh.broker.endpoints.builds.create_build',
           mocked_create_build)
    def test_register_builds_unauthorized(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                register_builds(MOCK_REPOSITORIES[1]['id'],
                                'access_token',
                                MOCK_BUILD_PAYLOAD)

    @patch('broker.ga4gh.broker.endpoints.builds.create_build',
           mocked_create_build)
    def test_register_builds_repository_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                register_builds('id',
                                MOCK_REPOSITORIES[1]['access_token'],
                                MOCK_BUILD_PAYLOAD)

    def test_get_builds(self):
        self.setup_with_build()
        with self.app.app_context():
            res = get_builds(MOCK_REPOSITORIES[1]['id'])
            assert isinstance(res, list)
            assert len(res) == 2

    def test_get_builds_build_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(BuildNotFound):
                get_builds(MOCK_REPOSITORIES[1]['id'])

    def test_get_builds_repository_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                get_builds('abcd')

    def test_get_build_info(self):
        self.setup_with_build()
        with self.app.app_context():
            res = get_build_info(MOCK_BUILD_INFO['id'])
            assert isinstance(res, dict)
            assert 'finished_at' in res
            assert 'head_commit' in res
            assert 'started_at' in res
            assert 'branch' in res['head_commit']

    def test_get_build_info_build_not_found(self):
        self.setup_with_build()
        with self.app.app_context():
            with pytest.raises(BuildNotFound):
                get_build_info('abcd')

    def test_git_clone_and_checkout(self):
        clone_path = git_clone_and_checkout(
            repo_url=self.repository_url,
            branch="main",
            commit="8cd58eb",
            base_dir=".",
            build_id="build123")
        assert clone_path == './build123/Broker-test'
        shutil.rmtree('./build123')

    def test_git_clone_and_checkout_type_error(self):
        with pytest.raises(WrongGitCommand):
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch="master",
                commit="8cd58b",
                base_dir=".",
                build_id="build123")
        shutil.rmtree('./build123')

    def test_git_clone_and_checkout_git_command_error(self):
        with pytest.raises(WrongGitCommand):
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch="main",
                commit="8cd58eb",
                base_dir=".",
                build_id="build123")
            git_clone_and_checkout(
                repo_url=self.repository_url,
                branch="main",
                commit="8cd58eb",
                base_dir=".",
                build_id="build123")
        shutil.rmtree('./build123')

    def test_create_deployment_yaml(self):
        builds.template_file = os.getcwd().split('Broker')[0] + \
                               'Broker/broker/ga4gh/broker/endpoints/' \
                               'template/template.yaml'
        os.mkdir('build123')
        os.mkdir('build123/Broker-test')
        deployment_file_location = create_deployment_YAML(
            './build123/Broker-test/dockerfile_location',
            'registry_destination',
            'clone_path',
            './build123/Broker-test/deployment_file',
            'build_id/config.json',
            'project_access_token')
        assert deployment_file_location == './build123/Broker-test/' \
                                           'deployment_file'
        assert os.path.isfile(deployment_file_location)
        shutil.rmtree('./build123')

    def test_create_deployment_yaml_if_env_present(self):
        os.environ['NAMESPACE'] = 'broker'
        builds.template_file = os.getcwd(
        ).split('Broker')[0] + 'Broker/broker/ga4gh/' \
                               'broker/endpoints/template/template.yaml'
        os.mkdir('build123')
        os.mkdir('build123/Broker-test')
        deployment_file_location = create_deployment_YAML(
            './build123/Broker-test/dockerfile_location',
            'registry_destination',
            'clone_path',
            './build123/Broker-test/deployment_file',
            'build_id/config.json',
            'project_access_token')
        assert deployment_file_location == './build123/Broker-test/' \
                                           'deployment_file'
        assert os.path.isfile(deployment_file_location)
        shutil.rmtree('./build123')
        del os.environ['NAMESPACE']

    def test_create_deployment_yaml_os_error(self):
        with pytest.raises(OSError):
            builds.template_file = os.getcwd().split('Broker')[0] + \
                                   'Broker/broker/ga4gh/broker/endpoints' \
                                   '/template/template.yaml'
            deployment_file_location = create_deployment_YAML(
                './build123/Broker-test/dockerfile_location',
                'registry_destination',
                'clone_path',
                './build123/Broker-test/deployment_file',
                'build_id' + '/config.json',
                'project_access_token')
            assert deployment_file_location == './build123/Broker-test/' \
                                               'deployment_file'
            assert os.path.isfile(deployment_file_location)
            shutil.rmtree('./build123')

    def test_create_dockerhub_config_file(self):
        create_dockerhub_config_file('token', 'config.json')
        assert os.path.isfile('config.json')
        os.remove('config.json')

    @patch(
        "broker.ga4gh.broker.endpoints.builds.build_push_image_using_kaniko",
        mocked_build_push_image_using_kaniko)
    def test_create_build(self):
        builds.template_file = os.getcwd().split('Broker')[0] + \
                               'Broker/broker/ga4gh/broker/endpoints/' \
                               'template/template.yaml'
        os.mkdir('basedir')
        os.mkdir('basedir/Broker-test')
        f = open('basedir/Broker-test/Dockerfile', "w")
        f.write("test dockerfile")
        f.close()
        create_build(
            repo_url=self.repository_url,
            branch="main",
            commit="8cd58eb",
            base_dir="basedir",
            build_id="build123",
            dockerfile_location="basedir/Broker-test/Dockerfile",
            registry_destination='registry_destination',
            dockerhub_token='dockerhub_token',
            project_access_token='access_token')
        shutil.rmtree('basedir')

    @patch("broker.ga4gh.broker.endpoints.builds.remove_files",
           mocked_remove_files)
    @patch('requests.request', mocked_request_api)
    def test_build_completed(self):
        self.setup_with_build()
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['subscriptions'].client = mongomock.MongoClient(
        ).db.collection
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['subscriptions'].client.insert_one(
            MOCK_SUBSCRIPTION_INFO).inserted_id
        with self.app.app_context():
            res = build_completed(MOCK_REPOSITORY_2['id'], MOCK_REPOSITORY_2[
                'build_list'][0], MOCK_REPOSITORY_2['access_token'])
            data = self.app.config['FOCA'].db.dbs['brokerStore']. \
                collections['builds'].client.find_one(res)
            assert data['status'] == 'SUCCEEDED'
            assert res['id'] == MOCK_REPOSITORY_2['build_list'][0]

    def test_build_completed_build_not_found(self):
        self.setup_with_build()
        with self.app.app_context():
            with pytest.raises(BuildNotFound):
                build_completed(MOCK_REPOSITORY_2['id'], 'build12',
                                MOCK_REPOSITORY_2['access_token'])

    def test_build_completed_unauthorized(self):
        self.setup_with_build()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                build_completed(MOCK_REPOSITORY_2['id'],
                                MOCK_REPOSITORY_2['build_list'][0],
                                '123')

    def test_build_completed_repository_not_found(self):
        self.setup_with_build()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                build_completed('repo125', MOCK_REPOSITORY_2['build_list'][0],
                                MOCK_REPOSITORY_2['access_token'])

    @patch("broker.ga4gh.broker.endpoints.builds.delete_pod",
           mocked_delete_pod)
    def test_remove_files(self):
        os.mkdir('build123')
        remove_files('build123', 'pod_name', 'namespace')
        assert not os.path.isdir('build123')

    @patch('kubernetes.config.load_kube_config', mocked_load_cluster_config)
    @patch('kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod',
           mocked_create_namespaced_pod)
    def test_build_push_image_using_kaniko(self):
        builds.template_file = os.getcwd().split('Broker')[0] + \
                               'Broker/broker/ga4gh/broker/endpoints/' \
                               'template/template.yaml'
        with self.app.app_context():
            build_push_image_using_kaniko(builds.template_file)
        os.environ['NAMESPACE'] = 'broker'
        with self.app.app_context():
            build_push_image_using_kaniko(builds.template_file)
        del os.environ['NAMESPACE']

    @patch('kubernetes.config.kube_config', mocked_load_cluster_config)
    @patch('kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod',
           mocked_create_namespaced_pod_error)
    def test_build_push_image_using_kaniko_create_pod_error(self):
        builds.template_file = os.getcwd().split('Broker')[0] + \
                               'Broker/broker/ga4gh/broker/endpoints/' \
                               'template/template.yaml'
        with self.app.app_context():
            with pytest.raises(CreatePodError):
                build_push_image_using_kaniko(builds.template_file)

    @patch('kubernetes.client.api.core_v1_api.CoreV1Api', mocked_core_v1_api)
    @patch('kubernetes.client.api.core_v1_api.CoreV1Api'
           '.delete_namespaced_pod', mocked_delete_namespaced_pod)
    def test_delete_pod(self):
        with self.app.app_context():
            builds.delete_pod('name', 'namespace')

    @patch('kubernetes.client.api.core_v1_api.CoreV1Api', mocked_core_v1_api)
    @patch('kubernetes.client.api.core_v1_api.CoreV1Api'
           '.delete_namespaced_pod', mocked_delete_namespaced_pod_error)
    def test_delete_pod_api_error(self):
        with self.app.app_context():
            with pytest.raises(DeletePodError):
                builds.delete_pod('name', 'namespace')

    @patch('kubernetes.config.load_incluster_config',
           mocked_load_incluster_config)
    @patch('kubernetes.client.api.core_v1_api.CoreV1Api.create_namespaced_pod',
           mocked_create_namespaced_pod)
    def test_build_push_image_using_kaniko_incluster(self):
        os.environ['KUBERNETES_SERVICE_HOST'] = 'Incluster'
        builds.template_file = os.getcwd().split('Broker')[0] + \
            'Broker/broker/ga4gh/broker/endpoints/template/template.yaml'
        with self.app.app_context():
            build_push_image_using_kaniko(builds.template_file)
        os.environ['NAMESPACE'] = 'broker'
        with self.app.app_context():
            build_push_image_using_kaniko(builds.template_file)
        del os.environ['NAMESPACE']
        del os.environ['KUBERNETES_SERVICE_HOST']
