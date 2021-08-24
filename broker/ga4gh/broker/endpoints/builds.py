import datetime
import logging
import os
import shutil

import yaml
from flask import (current_app)
from git import Repo, GitCommandError
from kubernetes import client, config
from kubernetes.client import ApiException
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

from broker.errors.exceptions import (RepositoryNotFound,
                                      BuildNotFound, DeletePodError,
                                      CreatePodError, WrongGitCommand,
                                      InternalServerError)
from broker.ga4gh.broker.endpoints.repositories import generate_id
from broker.ga4gh.broker.endpoints.subscriptions import notify_subscriptions

logger = logging.getLogger(__name__)

template_file = '/app/broker/ga4gh/broker/endpoints/template/template.yaml'


def register_builds(repository_id: str, access_token: str, build_data: dict):
    """Register new builds for already registered repository.

    Args:
        repository_id: Identifier for repository.
        access_token: Secret used to verify source of the request to
        initiate new build.
        build_data: Request data containing build information.

    Returns:
        build_id: Identifier for new registered build.

    Raises:
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        RepositoryNotFound: Raised when repository is not found with given
        identifier.

    Description:
        - Takes request build_data (Build information).
        - Check if repository with specified identifier is available or not.
        - Verify access_token.
        - Generate a random string, add it after repository identifier and
        use it as build identifier. (Retries 3 times for generating unique
        random string.)
        - Insert build_data in mongodb.
        - Call create_build function.
        - returns build_id.
    """
    retries = 3
    base_dir = '/broker_temp_files'
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
    if data_from_db is None:
        logger.error(
                    f"Could not find repository with given identifier: " +
                    repository_id
                )
        raise RepositoryNotFound
    if data_from_db['access_token'] != access_token:
        raise Unauthorized
    for i in range(retries + 1):
        logger.debug(
            f"Trying to insert/update object: try {i}" +
            str(build_data))
        build_data['id'] = repository_id + generate_id(
            charset=id_charset,
            length=id_length,
        )
        db_collection_repositories.update_one({"id": repository_id},
                                              {"$push": {
                                               "build_list":
                                                   build_data['id']}})
        try:
            build_data['finished_at'] = "NULL"
            build_data['started_at'] = str(
                datetime.datetime.now().isoformat())
            build_data['status'] = "QUEUED"
            db_collection_builds.insert_one(build_data)
            if 'branch' in build_data['head_commit'] and 'commit_sha' in \
                    build_data['head_commit']:
                create_build(repo_url=data_from_db['url'],
                             branch=build_data['head_commit']['branch'],
                             commit=build_data['head_commit'][
                                 'commit_sha'],
                             base_dir=base_dir,
                             build_id=build_data['id'],
                             dockerfile_location=build_data['images'][0][
                                 'location'],
                             registry_destination=build_data['images'][0][
                                 'name'],
                             # data=data,
                             # db_collection_builds=db_collection_builds,
                             dockerhub_token=build_data['dockerhub_token'],
                             project_access_token=access_token)
            elif 'branch' in build_data['head_commit']:
                create_build(repo_url=data_from_db['url'],
                             branch=build_data['head_commit']['branch'],
                             commit='',
                             base_dir=base_dir,
                             build_id=build_data['id'],
                             dockerfile_location=build_data['images'][0][
                                 'location'],
                             registry_destination=build_data['images'][0][
                                 'name'],
                             # data=data,
                             # db_collection_builds=db_collection_builds,
                             dockerhub_token=build_data['dockerhub_token'],
                             project_access_token=access_token)
            elif 'tag' in build_data['head_commit']:
                create_build(repo_url=data_from_db['url'],
                             branch='',
                             commit=build_data['head_commit'][
                                 'tag'],
                             base_dir=base_dir,
                             build_id=build_data['id'],
                             dockerfile_location=build_data['images'][0][
                                 'location'],
                             registry_destination=build_data['images'][0][
                                 'name'],
                             # data=data,
                             # db_collection_builds=db_collection_builds,
                             dockerhub_token=build_data['dockerhub_token'],
                             project_access_token=access_token)
            break
        except DuplicateKeyError:
            logger.error(f"DuplicateKeyError ({build_data['id']}): Key "
                         f"generated is already present.")
            continue
    else:
        logger.error(
            f"Could not generate unique identifier."
            f" Tried {retries + 1} times."
        )
        raise InternalServerError
    return {'id': build_data['id']}


def get_builds(repository_id: str):
    """Get build information.

    Args:
        repository_id: Repository identifier for retrieving builds information.

    Returns:
        build_object_list: List containing build information for available
        builds for the repository.

    Raises:
        BuildNotFound: Raised when object with given build identifier was
        not found.

    Description:
        - Takes repository identifier.
        - Initiate an empty list.
        - Checks if broker has repository with specified identifier.
        - Checks if repository has at least one build to show information.
        - Appends all build information in empty list.
        - Returns list containing builds information.
    """
    db_collection_repositories = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    build_object_list = []
    data_from_db = db_collection_repositories.find_one(
        {'id': repository_id})
    if data_from_db is None:
        raise RepositoryNotFound
    try:
        for build_id in data_from_db['build_list']:
            build_data = get_build_info(build_id)
            build_data['id'] = build_id
            build_object_list.append(build_data)
    except Exception:
        raise BuildNotFound
    return build_object_list


def get_build_info(build_id: str):
    """Gets builds information.

    Args:
        build_id: Build identifier. ( build_id = repository_id + random
        characters, len(build_id)=12 )

    Returns:
        build_object: Dictionary element of Build without DockerHub token.

    Raises:
        BuildNotFound: Raised when object with given build identifier was
        not found.

    Description:
        - Takes the build identifier.
        - Retrieve build information from mongodb.
        - Return build_object.
    """
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['builds'].client
    )
    try:
        build_object = db_collection_builds.find(
            {'id': build_id}, {'_id': False}
        ).limit(1).next()
        del build_object['id']
        del build_object['dockerhub_token']
        return build_object
    except StopIteration:
        raise BuildNotFound


def create_build(repo_url, branch, commit, base_dir, build_id,
                 dockerfile_location, registry_destination, dockerhub_token,
                 project_access_token):
    """
    Create build and push to DockerHub.

    Args:
        repo_url: URL of git repository to be cloned.
        branch: Branch of git repository used for checkout to build image.
        commit: Commit used for checkout to build image.
        base_dir: Location of base directory to clone git repository.
        build_id: Build Identifier.
        dockerfile_location: Location of dockerfile used for docker build
        taking git repository as base.
        registry_destination: Path of repository to push build image.
        dockerhub_token: Base 64 encoded USER:PASSWORD to access dockerhub to
        push image `echo -n USER:PASSWD | base64`
        project_access_token: Secret used to verify source, will be used
        by callback_url to inform broker for build completion.

    Description:
        - Clones git repository.
        - Creates kaniko deployment file.
        - Create dockerhub config file.
        - Create kaniko deployment to build and push image.
    """
    deployment_file_location = "%s/%s/%s.yaml" % (base_dir, build_id, build_id)
    config_file_location = "%s/%s/config.json" % (base_dir, build_id)
    clone_path = git_clone_and_checkout(
        repo_url=repo_url,
        branch=branch,
        commit=commit,
        base_dir=base_dir,
        build_id=build_id
    )
    # get_commit_list_from_repo_and_verify_commits(
    # clone_path=clone_path, latest_commit_sha=commit, build_id=build_id)

    create_deployment_YAML(
        "%s/%s" % (clone_path, dockerfile_location),
        registry_destination,
        clone_path,
        deployment_file_location,
        '%s/config.json' % (build_id),
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
    """Clone git repository and checkout to specified branch/commit/tag.

    Args:
        repo_url: URL of git repository to be cloned.
        branch: Branch of git repository used for checkout to build image.
        commit: Commit used for checkout to build image.
        base_dir: Location of base directory to clone git repository.
        build_id: Build Identifier.

    Returns:
        clone_path: Path of the directory where git repository is cloned.

    Raises:
        WrongGitCommand: Raised when there is problem while cloning repository.
    """
    clone_path = "%s/%s/%s" % (base_dir, build_id,
                               repo_url.split('/')[4].split('.')[0])
    try:
        if branch != '':
            repo = Repo.clone_from(repo_url, clone_path, branch=branch)
        else:
            repo = Repo.clone_from(repo_url, clone_path)
        if commit != '':
            repo.git.checkout(commit)
        return clone_path
    except GitCommandError:
        raise WrongGitCommand


def create_deployment_YAML(dockerfile_location: str, registry_destination: str,
                           build_context: str, deployment_file_location: str,
                           config_file_location: str,
                           project_access_token: str):
    """Create kaniko deployment file.

    Args:
        dockerfile_location: Location of dockerfile used for docker build
        taking git repository as base.
        registry_destination: Path of repository to push build image.
        build_context: Location of build context.
        deployment_file_location: Location to create deployment file.
        config_file_location: Dockerhub config file location, contains
        dockerhub access token.
        project_access_token: Secret used to verify source, will be used
        by callback_url to inform broker for build completion.

    Returns:
        deployment_file_location: Location of kaniko deployment file created.

    Raises:
        IOError: Raised when Input/Output operation failed while creating
        deployment file.

    Description:
        - Use template deployment file and create a new deployment file with
        modified values.
    """
    try:
        build_id = deployment_file_location.split('/')[2]
        file_stream = open(template_file, 'r')
        data = yaml.load(file_stream, Loader=yaml.FullLoader)
        data['metadata']['name'] = build_id
        data['spec']['containers'][0]['args'] = [
            f"--dockerfile={dockerfile_location}",
            f"--destination={registry_destination}",
            f"--context={build_context}",
            "--cleanup"]
        data['spec']['containers'][0]['volumeMounts'][1][
            'mountPath'] = '/kaniko/.docker/config.json'
        data['spec']['volumes'][0]['persistentVolumeClaim'][
            'claimName'] = os.getenv('PV_NAME')
        data['spec']['containers'][0]['volumeMounts'][1][
            'subPath'] = config_file_location
        data['spec']['containers'][0]['env'][0]['value'] = \
            build_id  # BUILDNAME
        data['spec']['containers'][0]['env'][1]['value'] = \
            project_access_token  # ACCESSTOKEN
        if os.getenv('NAMESPACE'):
            data['spec']['containers'][0]['env'][2]['value'] = os.getenv(
                'NAMESPACE')  # NAMESPACE
        else:
            data['spec']['containers'][0]['env'][2]['value'] = 'default'
        data['spec']['containers'][0]['env'][3]['value'] = \
            'http://broker-service.broker'  # BROKER_URL
        data['spec']['containers'][0]['env'][4]['value'] = '8080'  # PORT
        with open(deployment_file_location, 'w') as yaml_file:
            yaml_file.write(yaml.dump(data, default_flow_style=False))
        return deployment_file_location
    except OSError:
        raise OSError


def create_dockerhub_config_file(dockerhub_token, config_file_location):
    """Create dockerhub config file.

    Args:
        dockerhub_token: Base 64 encoded USER:PASSWORD to access dockerhub to
        push image `echo -n USER:PASSWD | base64`
        config_file_location: Location to create Dockerhub config file,
        it contains dockerhub access token.

    Description:
        - Uses template to create dockerhub config file.
    """
    template_config_file = '''{
"auths": {
"https://index.docker.io/v1/": {
"auth": "%s"
        }
    }
}''' % (dockerhub_token)
    f = open(config_file_location, "w")
    f.write(template_config_file)
    f.close()


def build_push_image_using_kaniko(deployment_file_location: str):
    """Create kaniko deployment. Build and push image.

    Args:
        deployment_file_location: Location of kaniko deployment file.

    Raises:
        CreatePodError: Raised when unable to create deployment.

    Description:
        - Retrieve values of NAMESPACE and KUBERNETES_SERVICE_HOST from
        environment variables.
        - Create namespace pod using kubernetes CoreV1Api from kaniko
        deployment file.
    """
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
        logger.info("Deployment created. status='%s'" % resp)


def build_completed(repository_id: str, build_id: str,
                    project_access_token: str):
    """Update build completion.

    Args:
        repository_id: Repository identifier.
        build_id: Build identifier.
        project_access_token: Secret to verify source of the request.

    Returns:
        build_id: Build identifier of completed build.

    Raises:
        RepositoryNotFound: Raised when object with given repository
        identifier is not found.
        BuildNotFound: Raised when object with given build identifier was
        not found.

    Description:
        - Checks if repository is registered with broker.
        - Verifies project_access_token is valid or not.
        - Checks if build is registered in the repository.
        - Updates values to the mongodb.
        - Notifies all subscriptions registered with the build.
        - Returns build identifier.
    """
    db_collection_repositories = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['builds'].client
    )

    data_from_db = db_collection_repositories.find_one(
        {'id': repository_id})
    if data_from_db is None:
        raise RepositoryNotFound
    if data_from_db['access_token'] != project_access_token:
        raise Unauthorized
    try:
        data = db_collection_builds.find(
            {'id': build_id}, {'_id': False}
        ).limit(1).next()
        # del data['id']
        data['status'] = "SUCCEEDED"
        data['finished_at'] = str(
            datetime.datetime.now().isoformat())
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
    except StopIteration:
        raise BuildNotFound


def remove_files(dir_location: str, pod_name: str, namespace: str):
    """Removes build directory and kaniko pod.

    Args:
        dir_location: Path of directory containing build files.
        pod_name: Name of kaniko pod which is completed and needs to be
        deleted.
        namespace: Namespace of pod.
    """
    shutil.rmtree(dir_location)
    delete_pod(pod_name, namespace)


def delete_pod(name, namespace):
    """Delete pod.

    Args:
        name: Name of kaniko pod which is completed and needs to be
        deleted.
        namespace: Namespace of pod.

    Returns:
        Response of CoreV1Api on deleting pod.

    Raises:
        DeletePodError: Raised when encountered an error while deleting pod.
    """
    try:
        api_instance = client.CoreV1Api()
        api_response = api_instance.delete_namespaced_pod(name, namespace)
        return api_response
    except ApiException as e:
        logger.error("Exception when calling "
                     "AppsV1Api->delete_namespaced_deployment: "
                     "%s\n" % e)
        raise DeletePodError


# Needs gpg setup and public key at microservice.
# def get_commit_list_from_repo_and_verify_commits(clone_path: str,
#                                                  latest_commit_sha: str,
#                                                  build_id: str,
#                                                  previous_commit_sha=None):
#     current_path = os.getcwd()
#     os.chdir(clone_path)
#     are_all_verified = False
#     p, q = sb.getstatusoutput("git log --oneline")
#     if p == 0:
#         commit_list = q.split("\n")
#         commit_sha_list = []
#         for i in reversed(commit_list):
#             if i.split(" ")[0] == latest_commit_sha:
#                 break
#             commit_sha_list.append(i.split(" ")[0])
#         if previous_commit_sha is None:
#             are_all_verified = verified_commits(commit_sha_list[0],
#                                                 commit_sha_list)
#         else:
#             are_all_verified = verified_commits(previous_commit_sha,
#                                                 commit_sha_list)
#         db_collection_builds = (
#             current_app.config['FOCA'].db.dbs['brokerStore'].
#             collections['builds'].client
#         )
#         data = db_collection_builds.find(
#             {'id': build_id}, {'_id': False}
#         ).limit(1).next()
#         data['commits_verified'] = are_all_verified
#         db_collection_builds.update_one({"id": data['id']},
#                                         {"$set": data})
#     else:
#         print('unable to fetch commit list')
#     os.chdir(current_path)
#     return are_all_verified
#
#
# def verified_commits(previous_commit_sha: str, commit_list: list):
#     verified_commits_list = []
#     previous_commit_found = False
#     for i in commit_list:
#         if previous_commit_sha == i:
#             previous_commit_found = True
#             continue
#         if not previous_commit_found:
#             continue
#         # if to_commit == i:
#         #     break
#         p, q = sb.getstatusoutput("git verify-commit " + i)
#         if p == 0:
#             verified_commits_list.append(i)
#     if len(verified_commits_list) == 0:
#         return False
#     else:
#         return True
