import datetime
import logging
import os
import shutil
import requests
import base64
import json

import yaml
from flask import current_app
from git import Repo, GitCommandError
from kubernetes import client, config
from kubernetes.client import ApiException
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

from pubgrade.errors.exceptions import (
    RepositoryNotFound,
    BuildNotFound,
    DeletePodError,
    CreatePodError,
    GitCloningError,
    InternalServerError,
)
from pubgrade.modules.endpoints.repositories import generate_id
from pubgrade.modules.endpoints.subscriptions import notify_subscriptions
from pubgrade.secrets import gh_access_token, cosign_password, cosign_private_key

logger = logging.getLogger(__name__)

template_file = '/app/pubgrade/modules/endpoints/kaniko/template.yaml'
BASE_DIR = os.getenv("BASE_DIR")
if BASE_DIR is None:
    BASE_DIR = '/pubgrade_temp_files'


def register_builds(repository_id: str, access_token: str, build_data: dict):
    """Register new builds for already registered repository.

    Args:
        repository_id (str): Identifier for repository.
        access_token (str): Secret used to verify source of the request to
        initiate new build.
        build_data (dict): Request data containing build information.

    Returns:
        build_id (str): Identifier for new registered build.

    Raises:
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        RepositoryNotFound: Raised when repository is not found with given
        identifier.
    """
    db_collection_builds = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["builds"]
        .client
    )
    db_collection_repositories = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["repositories"]
        .client
    )
    retries = current_app.config["FOCA"].endpoints["repository"]["retries"]
    id_length: int = current_app.config["FOCA"].endpoints["repository"][
        "id_length"
    ]
    id_charset: str = current_app.config["FOCA"].endpoints["repository"][
        "id_charset"
    ]
    try:
        id_charset = eval(id_charset)
    except Exception:
        id_charset = "".join(sorted(set(id_charset)))

    data_from_db = db_collection_repositories.find_one({"id": repository_id})

    if data_from_db is None:
        logger.error(
            "Could not find repository with given identifier: " + repository_id
        )
        raise RepositoryNotFound
    if data_from_db["access_token"] != access_token:
        raise Unauthorized
    for i in range(retries):
        logger.debug(
            f"Trying to insert/update object: try {i}" + str(build_data)
        )
        build_data["id"] = repository_id + generate_id(
            charset=id_charset,
            length=id_length,
        )
        db_collection_repositories.update_one(
            {"id": repository_id}, {"$push": {"build_list": build_data["id"]}}
        )
        try:
            build_data["finished_at"] = "NULL"
            build_data["started_at"] = str(datetime.datetime.now().isoformat())
            build_data["status"] = "QUEUED"
            db_collection_builds.insert_one(build_data)
            branch = ""
            commit_sha = ""
            try:
                branch = build_data["head_commit"]["branch"]
                try:
                    commit_sha = build_data["head_commit"]["commit_sha"]
                except KeyError:
                    commit_sha = ""
            except KeyError:
                commit_sha = build_data["head_commit"]["tag"]
            intermediate_registry_format = current_app.config["FOCA"].endpoints["builds"][
                "intermediate_registery_format"]
            intermediate_registry_path = intermediate_registry_format.format(
                build_data["images"][0]["name"].split("/")[1].split(":")[0])
            create_build(
                repo_url=data_from_db["url"],
                branch=branch,
                commit=commit_sha,
                base_dir=BASE_DIR,
                build_id=build_data["id"],
                dockerfile_location=build_data["images"][0]["location"],
                intermediate_registry_path=intermediate_registry_path,
                dockerhub_token=build_data["dockerhub_token"],
                project_access_token=access_token,
            )
            break
        except DuplicateKeyError:
            logger.error(
                f"DuplicateKeyError ({build_data['id']}): Key "
                f"generated is already present."
            )
            continue
    else:
        logger.error(
            f"Could not generate unique identifier."
            f" Tried {retries + 1} times."
        )
        raise InternalServerError
    return {"id": build_data["id"]}


def get_builds(repository_id: str):
    """Retrieve build information.

    Args:
        repository_id (str): Repository identifier for retrieving builds
        information.

    Returns:
        build_object_list (list): List containing build information for
        available builds for the repository.

    Raises:
        BuildNotFound: Raised when object with given build identifier was
        not found.
    """
    db_collection_repositories = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["repositories"]
        .client
    )
    build_object_list = []
    data_from_db = db_collection_repositories.find_one({"id": repository_id})
    if data_from_db is None:
        raise RepositoryNotFound
    try:
        for build_id in data_from_db["build_list"]:
            build_data = get_build_info(build_id)
            build_data["id"] = build_id
            build_object_list.append(build_data)
    except Exception:
        logger.error(
            "No build found for given repository identifier. {repository_id}"
        )
        raise BuildNotFound
    return build_object_list


def get_build_info(build_id: str):
    """Retrieve build information.

    Args:
        build_id (str): Build identifier. ( build_id = repository_id + random
        characters, len(build_id)=12 )

    Returns:
        build_object (dict): Dictionary element of Build without DockerHub
        token.

    Raises:
        BuildNotFound: Raised when object with given build identifier was
        not found.
    """
    db_collection_builds = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["builds"]
        .client
    )
    try:
        build_object = (
            db_collection_builds.find({"id": build_id}, {"_id": False})
            .limit(1)
            .next()
        )
        del build_object["id"]
        del build_object["dockerhub_token"]
        return build_object
    except StopIteration:
        raise BuildNotFound


def create_build(
        repo_url: str,
        branch: str,
        commit: str,
        base_dir: str,
        build_id: str,
        dockerfile_location: str,
        intermediate_registry_path: str,
        dockerhub_token: str,
        project_access_token: str,
):
    """
    Create build and push to DockerHub.

    Args:
        repo_url (str): URL of git repository to be cloned.
        branch (str): Branch of git repository used for checkout to build
        image.
        commit (str): Commit used for checkout to build image.
        base_dir (str): Location of base directory to clone git repository.
        build_id (str): Build Identifier.
        dockerfile_location (str): Location of dockerfile used for docker build
        taking git repository as base.
        intermediate_registry_path (str): Path of repository to push build image.
        dockerhub_token (str): Base 64 encoded USER:PASSWORD to access
        dockerhub to push image `echo -n USER:PASSWD | base64`
        project_access_token (str): Secret used to verify source, will be used
        by callback_url to inform pubgrade for build completion.
    """
    deployment_file_location = "%s/%s/%s.yaml" % (base_dir, build_id, build_id)
    config_file_location = "%s/%s/config.json" % (base_dir, build_id)

    # Clone project repository.
    clone_path = git_clone_and_checkout(
        repo_url=repo_url,
        branch=branch,
        commit=commit,
        base_dir=base_dir,
        build_id=build_id,
    )

    # Create kaniko deployment file.
    create_deployment_YAML(
        "%s/%s" % (clone_path, dockerfile_location),
        intermediate_registry_path,
        clone_path,
        deployment_file_location,
        "%s/config.json" % build_id,
        project_access_token,
    )

    # Create dockerhub config file
    create_dockerhub_config_file(
        dockerhub_token=dockerhub_token,
        config_file_location=config_file_location,
    )

    # Create kaniko deployment to build and publish image.
    build_push_image_using_kaniko(
        deployment_file_location=deployment_file_location
    )


def git_clone_and_checkout(
        repo_url: str, branch: str, commit: str, base_dir: str, build_id: str
):
    """Clone git repository and checkout to specified branch/commit/tag.

    Args:
        repo_url (str): URL of git repository to be cloned.
        branch (str): Branch of git repository used for checkout to build
        image.
        commit (str): Commit used for checkout to build image.
        base_dir (str): Location of base directory to clone git repository.
        build_id (str): Build Identifier.

    Returns:
        clone_path (str): Path of the directory where git repository is cloned.

    Raises:
        GitCloningError: Raised when there is problem while cloning repository.
    """
    clone_path = "%s/%s/%s" % (
        base_dir,
        build_id,
        repo_url.split("/")[4].split(".")[0],
    )
    try:
        # Check if head commit is branch or tag.
        if branch != "":
            # If branch is specified.
            repo = Repo.clone_from(repo_url, clone_path, branch=branch)
        else:
            # If tag is specified.
            repo = Repo.clone_from(repo_url, clone_path)
        # Checkout only if tag or commit sha is specified, otherwise stay at
        # HEAD of branch.
        if commit != "":
            repo.git.checkout(commit)
        return clone_path
    except GitCommandError:
        raise GitCloningError


def create_deployment_YAML(
        dockerfile_location: str,
        intermediate_registry_path: str,
        build_context: str,
        deployment_file_location: str,
        config_file_location: str,
        project_access_token: str,
):
    """Create kaniko deployment file.

    Use template kaniko deployment file and create a new deployment file with
    specified values.

    Args:
        dockerfile_location (str): Location of dockerfile used for docker build
        taking git repository as base.
        intermediate_registry_path (str): Path of repository to push build image.
        build_context: Location of build context.
        deployment_file_location (str): Location to create deployment file.
        config_file_location (str): Dockerhub config file location, contains
        dockerhub access token.
        project_access_token (str): Secret used to verify source, will be used
        by callback_url to inform pubgrade for build completion.

    Returns:
        deployment_file_location (str): Location of kaniko deployment file
        created.

    Raises:
        IOError: Raised when Input/Output operation failed while creating
        deployment file.
    """
    try:
        build_id = deployment_file_location.split("/")[2]
        file_stream = open(template_file, "r")
        data = yaml.load(file_stream, Loader=yaml.FullLoader)
        data["metadata"]["name"] = build_id
        data["spec"]["containers"][0]["args"] = [
            f"--dockerfile={dockerfile_location}",
            f"--destination={intermediate_registry_path}",
            f"--context={build_context}",
            "--cleanup",
        ]
        data["spec"]["containers"][0]["volumeMounts"][1][
            "mountPath"
        ] = "/kaniko/.docker/config.json"
        data["spec"]["volumes"][0]["persistentVolumeClaim"][
            "claimName"
        ] = os.getenv("PV_NAME")
        data["spec"]["containers"][0]["volumeMounts"][1][
            "subPath"
        ] = config_file_location
        data["spec"]["containers"][0]["env"][0][
            "value"
        ] = build_id  # BUILDNAME
        data["spec"]["containers"][0]["env"][1][
            "value"
        ] = project_access_token  # ACCESSTOKEN
        if os.getenv("NAMESPACE"):
            data["spec"]["containers"][0]["env"][2]["value"] = os.getenv(
                "NAMESPACE"
            )  # NAMESPACE
        else:
            data["spec"]["containers"][0]["env"][2]["value"] = "default"
        data["spec"]["containers"][0]["env"][3][
            "value"
        ] = os.getenv("PUBGRADE_URL")
        data["spec"]["containers"][0]["env"][4]["value"] = "8080"  # PORT
        with open(deployment_file_location, "w") as yaml_file:
            yaml_file.write(yaml.dump(data, default_flow_style=False))
        return deployment_file_location
    except OSError:
        raise OSError


def create_dockerhub_config_file(
        dockerhub_token: str, config_file_location: str
):
    """Create dockerhub config file.

    Args:
        dockerhub_token (str): Base 64 encoded USER:PASSWORD to access
        dockerhub to push image `echo -n USER:PASSWD | base64`
        config_file_location (str): Location to create Dockerhub config file,
        it contains dockerhub access token.
    """
    intermediate_registry_format = current_app.config["FOCA"].endpoints["builds"]["intermediate_registery_format"]
    intermediate_registry_token = current_app.config["FOCA"].endpoints["builds"]["intermediate_registry_token"]
    template_config_file = (
            """{
"auths": {
"%s": {
"auth": "%s"
        }
    }
}"""
                           ) % (intermediate_registry_format.split("/", 1)[0],  intermediate_registry_token )
    f = open(config_file_location, "w")
    f.write(template_config_file)
    f.close()


def build_push_image_using_kaniko(deployment_file_location: str):
    """Create kaniko deployment. Build and push image.

    Args:
        deployment_file_location (str): Location of kaniko deployment file.

    Raises:
        CreatePodError: Raised when unable to create deployment.
    """
    # Retrieve values of NAMESPACE and KUBERNETES_SERVICE_HOST from
    # environment variables.
    if os.getenv("NAMESPACE"):
        namespace = os.getenv("NAMESPACE")
    else:
        namespace = "default"
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        config.load_incluster_config()
    else:
        config.load_kube_config()
    v1 = client.CoreV1Api()

    # Create namespaced pod using kubernetes CoreV1Api from kaniko
    # deployment file.
    with open(deployment_file_location) as f:
        dep = yaml.safe_load(f)
        try:
            resp = v1.create_namespaced_pod(body=dep, namespace=namespace)
        except ApiException as e:
            logger.error(
                "Exception when calling "
                "AppsV1Api->create_namespaced_pod: "
                "%s\n" % e
            )
            raise CreatePodError
        logger.info("Deployment created. status='%s'" % resp)


def build_completed(
        repository_id: str, build_id: str, project_access_token: str
):
    """Update build completion.

    Args:
        repository_id (str): Repository identifier.
        build_id (str): Build identifier.
        project_access_token (str): Secret to verify source of the request.

    Returns:
        build_id (str): Build identifier of completed build.

    Raises:
        RepositoryNotFound: Raised when object with given repository
        identifier is not found.
        BuildNotFound: Raised when object with given build identifier was
        not found.
    """
    db_collection_repositories = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["repositories"]
        .client
    )
    db_collection_builds = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["builds"]
        .client
    )

    data_from_db = db_collection_repositories.find_one({"id": repository_id})
    if data_from_db is None:
        raise RepositoryNotFound
    if data_from_db["access_token"] != project_access_token:
        raise Unauthorized
    try:
        data = db_collection_builds.find(
            {'id': build_id}, {'_id': False}
        ).limit(1).next()
        data['status'] = "SUCCEEDED"
        data['finished_at'] = str(
            datetime.datetime.now().isoformat())

        intermediate_registry_format = current_app.config["FOCA"].endpoints["builds"]["intermediate_registery_format"]
        trigger_signing_image(
            image_path=data["images"][0]["name"],
            cosign_private_key=cosign_private_key,
            dockerhub_token=data["dockerhub_token"],
            cosign_password=cosign_password,
            pull_tag=intermediate_registry_format.format(data["images"][0]["name"].split("/")[1].split(":")[0]),
            push_tag=data["images"][0]["name"]
        )

        db_collection_builds.update_one({"id": data['id']},
                                        {"$set": data})
        remove_files(BASE_DIR + "/" + build_id, build_id, "pubgrade-ns")

        # Notifies available subscriptions registered for the repository.
        if "subscription_list" in data_from_db:
            subscription_list = data_from_db["subscription_list"]
            for subscription in subscription_list:
                # for image_name in data['images']:
                notify_subscriptions(
                    subscription, data["images"][0]["name"], build_id
                )
        return {"id": build_id}
    except StopIteration:
        raise BuildNotFound


def remove_files(dir_location: str, pod_name: str, namespace: str):
    """Removes build directory and kaniko pod.

    Args:
        dir_location (str): Path of directory containing build files.
        pod_name (str): Name of kaniko pod which is completed and needs to be
        deleted.
        namespace (str): Namespace of pod.
    """
    shutil.rmtree(dir_location)
    delete_pod(pod_name, namespace)


def delete_pod(name: str, namespace: str):
    """Delete pod.

    Args:
        name (str): Name of kaniko pod which is completed and needs to be
        deleted.
        namespace (str): Namespace of pod.

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
        logger.error(
            "Exception when calling "
            "AppsV1Api->delete_namespaced_deployment: "
            "%s\n" % e
        )
        raise DeletePodError


def trigger_signing_image(cosign_private_key: str, cosign_password: str, dockerhub_token: str,
                          image_path: str, pull_tag: str, push_tag: str):
    username, password = base64.b64decode(dockerhub_token).decode('utf-8').split(":")
    url = "https://api.github.com/repos/{}/dispatches".format(
        current_app.config["FOCA"].endpoints["builds"]["gh_action_path"])
    payload = json.dumps({
        "event_type": "sign-image",
        "client_payload": {
            "cosign_key": cosign_private_key,
            "docker_username": username,
            "docker_password": password,
            "cosign_password": cosign_password,
            "image_path": image_path,
            "pull_tag": pull_tag,
            "push_tag": push_tag,

        }
    })
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': 'Bearer {}'.format(gh_access_token),
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
