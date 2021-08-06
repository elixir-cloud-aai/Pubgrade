"""Tests for /builds endpoint """
import os
import shutil
from pprint import pprint
from unittest.mock import patch

import mongomock
import pytest
from flask import Flask
from foca.models.config import Config, MongoConfig
from git import GitCommandError
from werkzeug.exceptions import Unauthorized

from broker.errors.exceptions import RepositoryNotFound, BuildNotFound, \
    WrongGitCommand
from broker.ga4gh.broker.endpoints.builds import register_builds, get_builds, \
    get_build_info, git_clone_and_checkout, create_deployment_YAML, \
    create_dockerhub_config_file
import broker.ga4gh.broker.endpoints.builds as builds
from tests.ga4gh.mock_data import ENDPOINT_CONFIG, MONGO_CONFIG, \
    MOCK_REPOSITORIES, MOCK_BUILD_PAYLOAD, MOCK_BUILD_INFO, MOCK_BUILD_INFO_2


def mocked_create_build(repo_url, branch, commit, base_dir, build_id,
                        dockerfile_location, registry_destination,
                        dockerhub_token,
                        project_access_token):
    # Need a mock for kubernetes
    return 'working fine'


class TestBuild:
    app = Flask(__name__)

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
            with pytest.raises(BuildNotFound):
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
            repo_url="https://github.com/akash2237778/Broker-test",
            branch="main",
            commit="8cd58eb",
            base_dir=".",
            build_id="build123")
        pprint(clone_path)
        assert clone_path == './build123/Broker-test'
        shutil.rmtree('./build123')

    def test_git_clone_and_checkout_type_error(self):
        with pytest.raises(GitCommandError):
            git_clone_and_checkout(
                repo_url="https://github.com/akash2237778/unknownrepo",
                branch="main",
                commit="8cd58eb",
                base_dir=".",
                build_id="build123")
        shutil.rmtree('./build123')

    def test_git_clone_and_checkout_git_command_error(self):
        with pytest.raises(GitCommandError):
            git_clone_and_checkout(
                repo_url="https://github.com/akash2237778/Broker-test",
                branch="main",
                commit="8cd58eb",
                base_dir=".",
                build_id="build123")
            git_clone_and_checkout(
                repo_url="https://github.com/akash2237778/Broker-test",
                branch="main",
                commit="8cd58eb",
                base_dir=".",
                build_id="build123")
        shutil.rmtree('./build123')

    def test_create_deployment_yaml(self):
        builds.template_file = os.getcwd().split('Broker')[0] + \
               'Broker/broker/ga4gh/broker/endpoints/template/template.yaml'
        os.mkdir('build123')
        os.mkdir('build123/Broker-test')
        deployment_file_location = create_deployment_YAML(
            './build123/Broker-test' + '/' + 'dockerfile_location',
            'registry_destination',
            'clone_path',
            './build123/Broker-test' + '/' + 'deployment_file',
            'build_id' + '/config.json',
            'project_access_token')
        assert deployment_file_location ==\
               './build123/Broker-test/deployment_file'
        assert os.path.isfile(deployment_file_location)
        shutil.rmtree('./build123')

    def test_create_deployment_yaml_os_error(self):
        with pytest.raises(OSError):
            builds.template_file = os.getcwd().split('Broker')[0] + \
                   'Broker/broker/ga4gh/broker/endpoints/template/template.yaml'
            deployment_file_location = create_deployment_YAML(
                './build123/Broker-test' + '/' + 'dockerfile_location',
                'registry_destination',
                'clone_path',
                './build123/Broker-test' + '/' + 'deployment_file',
                'build_id' + '/config.json',
                'project_access_token')
            assert deployment_file_location ==\
                   './build123/Broker-test/deployment_file'
            assert os.path.isfile(deployment_file_location)
            shutil.rmtree('./build123')

    def test_create_dockerhub_config_file(self):
        create_dockerhub_config_file('token', 'config.json')
        assert os.path.isfile('config.json')
        # f = open('config.json', "r")
        # pprint(f.readlines())
        os.remove('config.json')
