import datetime
import logging
import os
import shutil
from typing import (Dict)

import yaml
from flask import (current_app)
from git import Repo
from git.exc import GitCommandError
from kubernetes import client, config
from kubernetes.client import ApiException
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

from broker.errors.exceptions import (NotFound,
                                      RepositoryNotFound,
                                      BuildNotFound, DeletePodError,
                                      CreatePodError, WrongGitCommand)
from broker.ga4gh.broker.endpoints.repositories import generate_id
from broker.ga4gh.broker.endpoints.subscriptions import notify_subscriptions

logger = logging.getLogger(__name__)

template_file = '/app/broker/ga4gh/broker/endpoints/template/template.yaml'


def register_builds(repository_id: str, access_token: str, data: Dict):
    retries = 3
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['builds'].client
    )
    db_collection_repositories = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    id_length = (
        current_app.config['FOCA'].endpoints['repository']['id_length']
    )
    id_charset: str = (
        current_app.config['FOCA'].endpoints['repository']['id_charset']
    )
    try:
        id_charset = eval(id_charset)
    except Exception:
        id_charset = ''.join(sorted(set(id_charset)))

    data_from_db = db_collection_repositories.find_one({'id': repository_id})
    if data_from_db is not None:
        if data_from_db['access_token'] == access_token:
            for i in range(retries + 1):
                logger.debug(
                    f"Trying to insert/update object: try {i}" + str(data))
                data['id'] = repository_id + generate_id(
                    charset=id_charset,
                    length=id_length,
                )
                db_collection_repositories.update({"id": repository_id},
                                                  {"$push": {
                                                      "buildList": data[
                                                          'id']}})
                try:
                    data['finished_at'] = "NULL"
                    data['started_at'] = str(
                        datetime.datetime.now().isoformat())
                    data['status'] = "QUEUED"
                    db_collection_builds.insert_one(data)
                    create_build(repo_url=data_from_db['url'],
                                 branch=data['head_commit']['branch'],
                                 commit=data['head_commit']['commit_sha'],
                                 base_dir='/broker_temp_files',
                                 build_id=data['id'],
                                 dockerfile_location=data['images'][0][
                                     'location'],
                                 registry_destination=data['images'][0][
                                     'name'],
                                 # data=data,
                                 # db_collection_builds=db_collection_builds,
                                 dockerhub_token=data['dockerhub_token'],
                                 project_access_token=access_token)
                    break
                except DuplicateKeyError:
                    logger.log('Encountered DuplicateKeyError. Retrying... '
                               + str(i) + ' times'.format(i))
                    continue
            return {'id': data['id']}
        else:
            raise Unauthorized
    else:
        raise RepositoryNotFound


def get_builds(repository_id: str):
    db_collection_repositories = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    data = []
    data_from_db = db_collection_repositories.find_one({'id': repository_id})
    if data_from_db is not None:
        for build_id in data_from_db['buildList']:
            build_data = get_build_info(build_id)
            build_data['id'] = build_id
            data.append(build_data)
        logger.info('mData   : ' + str(data))
        # get_build_info()
        return data
    else:
        raise BuildNotFound


def get_build_info(build_id: str):
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['builds'].client
    )
    try:
        data = db_collection_builds.find(
            {'id': build_id}, {'_id': False}
        ).limit(1).next()
        del data['id']
        del data['dockerhub_token']
        return data
    except StopIteration:
        raise BuildNotFound


def create_build(repo_url, branch, commit, base_dir, build_id,
                 dockerfile_location, registry_destination, dockerhub_token,
                 project_access_token):
    deployment_file_location = base_dir + '/' + build_id + '/' + build_id + \
                               '.yaml '
    config_file_location = base_dir + '/' + build_id + '/config.json'
    clone_path = git_clone_and_checkout(
        repo_url=repo_url,
        branch=branch,
        commit=commit,
        base_dir=base_dir,
        build_id=build_id
    )
    create_deployment_YAML(
        clone_path + '/' + dockerfile_location,
        registry_destination,
        clone_path,
        deployment_file_location,
        build_id + '/config.json',
        project_access_token)
    create_dockerhub_config_file(
        dockerhub_token=dockerhub_token,
        config_file_location=config_file_location
    )
    build_push_image_using_kaniko(
        deployment_file_location=deployment_file_location
    )


def git_clone_and_checkout(repo_url: str, branch: str, commit: str,
                           base_dir: str, build_id: str):
    clone_path = base_dir + '/' + build_id + '/' + \
                 repo_url.split('/')[4].split('.')[0]
    try:
        repo = Repo.clone_from(repo_url, clone_path, branch=branch)
        repo.git.checkout(commit)
        return clone_path
    except GitCommandError:
        raise WrongGitCommand


def create_deployment_YAML(dockerfile: str, destination: str,
                           build_context: str, deployment_file_location: str,
                           config_file_location: str,
                           project_access_token: str):
    try:
        build_id = deployment_file_location.split('/')[2]
        file_stream = open(template_file, 'r')
        data = yaml.load(file_stream)
        data['metadata']['name'] = build_id
        data['spec']['containers'][0]['args'] = [
            f"--dockerfile={dockerfile}",
            f"--destination={destination}",
            f"--context={build_context}",
            "--cleanup"]
        data['spec']['containers'][0]['volumeMounts'][1][
            'mountPath'] = '/kaniko/.docker/config.json'
        data['spec']['volumes'][0]['persistentVolumeClaim'][
            'claimName'] = os.getenv('PV_NAME')
        data['spec']['containers'][0]['volumeMounts'][1][
            'subPath'] = config_file_location
        data['spec']['containers'][0]['lifecycle']['preStop']['exec'][
            'command'] = ["/bin/sh",
                          "curl --location --request PUT 'http://{"
                          "service_url}:{service_port}/repositories/{"
                          "repo_id}/builds/{build_id}' --header "
                          "'X-Project-Access-Token: {project_access_token}' "
                          "--header 'Content-Type: application/json' "
                          "--data-raw '{{ \"id\": \"{build_id}\" }}'".format(
                              service_url='broker-service.broker',
                              service_port='5000', repo_id=build_id[0:6],
                              build_id=build_id,
                              project_access_token=project_access_token)]
        with open(deployment_file_location, 'w') as yaml_file:
            yaml_file.write(yaml.dump(data, default_flow_style=False))
        return deployment_file_location
    except IOError:
        raise IOError


def create_dockerhub_config_file(dockerhub_token, config_file_location):
    template_config_file = '''{
"auths": {
"https://index.docker.io/v1/": {
"auth": "''' + dockerhub_token + '''"
        }
    }
}'''
    f = open(config_file_location, "w")
    f.write(template_config_file)
    f.close()


def build_push_image_using_kaniko(deployment_file_location: str):
    if os.getenv('NAMESPACE'):
        namespace = os.getenv('NAMESPACE')
    else:
        namespace = 'default'
    if os.getenv('KUBERNETES_SERVICE_HOST'):
        config.load_incluster_config()
    else:
        config.load_kube_config()
    v1 = client.CoreV1Api()
    with open(deployment_file_location) as f:
        dep = yaml.safe_load(f)
        try:
            resp = v1.create_namespaced_pod(
                body=dep, namespace=namespace)
        except ApiException as e:
            logger.error("Exception when calling "
                         "AppsV1Api->create_namespaced_pod: "
                         "%s\n" % e)
            raise CreatePodError
        print("Deployment created. status='%s'" % resp.metadata.name)


def build_completed(repository_id: str, build_id: str,
                    project_access_token: str):
    db_collection_repositories = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['builds'].client
    )
    try:

        data_from_db = db_collection_repositories.find_one(
            {'id': repository_id})
        if data_from_db is not None:
            if data_from_db['access_token'] == project_access_token:
                data = db_collection_builds.find(
                    {'id': build_id}, {'_id': False}
                ).limit(1).next()
                # del data['id']
                data['status'] = "SUCCEEDED"
                data['finished_at'] = str(datetime.datetime.now().isoformat())
                db_collection_builds.update_one({"id": data['id']},
                                                {"$set": data})
                remove_files('/broker_temp_files/' + build_id, build_id,
                             'broker')
                if 'subscription_list' in data_from_db:
                    subscription_list = data_from_db['subscription_list']
                    for subscription in subscription_list:
                        # for image_name in data['images']:
                        notify_subscriptions(subscription,
                                             data['images'][0]['name'],
                                             build_id)
                return {'id': build_id}
    except RepositoryNotFound:
        raise NotFound


def remove_files(dir_location: str, pod_name: str, namespace: str):
    shutil.rmtree(dir_location)
    delete_pod(pod_name, namespace)


def delete_pod(name, namespace):
    try:
        api_instance = client.CoreV1Api()
        api_response = api_instance.delete_namespaced_pod(name, namespace)
        return api_response
    except ApiException as e:
        logger.error("Exception when calling "
                     "AppsV1Api->delete_namespaced_deployment: "
                     "%s\n" % e)
        raise DeletePodError
