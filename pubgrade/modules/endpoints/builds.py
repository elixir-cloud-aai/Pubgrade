"""Registration of builds and publication of images."""

import base64
import json
import logging
import os
import re
import shutil
from typing import Any

from git import GitCommandError, Repo
from kubernetes import client, config
from kubernetes.client import ApiException
from pymongo.errors import DuplicateKeyError
import requests
from werkzeug.exceptions import Unauthorized
import yaml

from pubgrade.charsets import get_charset
from pubgrade.errors.exceptions import (
    BuildNotFound,
    BuildsDisabled,
    CreatePodError,
    DeletePodError,
    GitCloningError,
    GitRefNotFound,
    InternalServerError,
    InvalidImage,
    RepositoryNotFound,
)
from pubgrade.modules.endpoints.repositories import generate_id
from pubgrade.modules.endpoints.subscriptions import notify_all_subscriptions
from pubgrade.settings import collection, endpoints
from pubgrade.timestamps import now, repaired_build

logger = logging.getLogger(__name__)

template_file = "/app/pubgrade/modules/endpoints/kaniko/template.yaml"
BASE_DIR = os.getenv("BASE_DIR", "/pubgrade_temp_files")
# Seconds to connect to GitHub and for its response, when triggering the
# signing of an image
REQUEST_TIMEOUT = 30

# An image with a tag (no digest), optionally with a registry and its port,
# following Docker's rules for references
IMAGE_WITH_TAG = re.compile(
    r"(?:(?:localhost|[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+|[a-zA-Z0-9-]+(?=:))"
    r"(?::[0-9]+)?/)?"
    r"[a-z0-9]+(?:[._-]+[a-z0-9]+)*(?:/[a-z0-9]+(?:[._-]+[a-z0-9]+)*)*"
    r":[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}"
)


def builds_enabled() -> bool:
    """Check whether Pubgrade builds images itself.

    Returns:
        The setting `endpoints.builds.enabled`; False if it isn't set.
    """
    return endpoints()["builds"].get("enabled", False)


def validate_prebuilt_image(build_data: dict[str, Any]) -> None:
    """Check a request to publish a prebuilt image.

    Args:
        build_data: Request data.

    Raises:
        BuildsDisabled: Raised when the request asks for a build.
        InvalidImage: Raised when the request doesn't name exactly one image.
    """
    images = build_data["images"]
    if "dockerhub_token" in build_data or any("location" in image for image in images):
        raise BuildsDisabled
    if len(images) != 1:
        raise InvalidImage


def publish_prebuilt_image(build_id: str, image: str, subscriptions: list[str]) -> None:
    """Notify subscriptions of a prebuilt image and finish its build.

    Args:
        build_id: Identifier of the build.
        image: Name and tag of the image.
        subscriptions: Identifiers of the repository's subscriptions.
    """
    results = notify_all_subscriptions(subscriptions, image, build_id)
    failed = any(result["result"] == "failed" for result in results)
    collection("builds").update_one(
        {"id": build_id},
        {
            "$set": {
                "status": "FAILED" if failed else "SUCCEEDED",
                "finished_at": now(),
            }
        },
    )


def register_builds(
    repository_id: str, access_token: str, build_data: dict[str, Any]
) -> dict[str, str]:
    """Register new builds for already registered repository.

    With builds switched off (`endpoints.builds.enabled`), the request names a
    prebuilt image, and the repository's subscriptions are notified of it.
    With builds switched on, a build that can't start (e.g., of an unknown
    branch) is removed again: only builds whose identifier the client got are
    kept.

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
        BuildsDisabled: Raised when the request asks for a build, with builds
        switched off.
        InvalidImage: Raised when there is no image, an image isn't a valid
        reference with a tag, or a request for a prebuilt image doesn't name
        exactly one.
        GitRefNotFound: Raised when the branch, tag or commit to build isn't
        in the repository.
    """
    db_collection_builds = collection("builds")
    db_collection_repositories = collection("repositories")
    retries = endpoints()["repository"]["retries"]
    id_length: int = endpoints()["repository"]["id_length"]
    id_charset = get_charset("repository", "id_charset")

    data_from_db = db_collection_repositories.find_one({"id": repository_id})

    if data_from_db is None:
        logger.error(
            "Could not find repository with given identifier: %s", repository_id
        )
        raise RepositoryNotFound
    if data_from_db["access_token"] != access_token:
        raise Unauthorized
    images = build_data.get("images")
    if not images or not all(
        IMAGE_WITH_TAG.fullmatch(image.get("name", "")) for image in images
    ):
        raise InvalidImage
    build_path = builds_enabled()
    if not build_path:
        validate_prebuilt_image(build_data)
    for i in range(retries):
        logger.debug("Trying to insert/update object: try %s", i)
        build_data["id"] = repository_id + generate_id(
            charset=id_charset,
            length=id_length,
        )
        db_collection_repositories.update_one(
            {"id": repository_id}, {"$push": {"build_list": build_data["id"]}}
        )
        try:
            build_data["finished_at"] = None
            build_data["started_at"] = now()
            build_data["status"] = "QUEUED"
            db_collection_builds.insert_one(build_data)
            logger.info("Added build %s.", build_data["id"])
            break
        except DuplicateKeyError:
            logger.error(
                "DuplicateKeyError (%s): Key generated is already present.",
                build_data["id"],
            )
            continue
    else:
        logger.error(
            "Could not generate unique identifier. Tried %s times.", retries + 1
        )
        raise InternalServerError
    if not build_path:
        publish_prebuilt_image(
            build_data["id"],
            build_data["images"][0]["name"],
            data_from_db.get("subscription_list", []),
        )
        return {"id": build_data["id"]}
    try:
        start_build(build_data, data_from_db["url"], access_token)
    except Exception:
        # The client gets an error instead of the build's identifier, so the
        # build is not kept
        db_collection_builds.delete_one({"id": build_data["id"]})
        db_collection_repositories.update_one(
            {"id": repository_id}, {"$pull": {"build_list": build_data["id"]}}
        )
        logger.info("Removed build %s, which could not start.", build_data["id"])
        raise
    return {"id": build_data["id"]}


def start_build(build_data: dict[str, Any], repo_url: str, access_token: str) -> None:
    """Start a registered build.

    Args:
        build_data: The build, as registered.
        repo_url: URL of the repository.
        access_token: Access token of the repository.
    """
    head_commit = build_data["head_commit"]
    if "branch" in head_commit:
        branch = head_commit["branch"]
        commit_sha = head_commit.get("commit_sha", "")
    else:
        branch = ""
        commit_sha = head_commit["tag"]
    intermediate_registry_format = endpoints()["builds"][
        "intermediate_registery_format"
    ]
    intermediate_registry_path = intermediate_registry_format.format(
        build_data["images"][0]["name"].split("/")[1].split(":")[0]
    )
    create_build(
        repo_url=repo_url,
        branch=branch,
        commit=commit_sha,
        base_dir=BASE_DIR,
        build_id=build_data["id"],
        dockerfile_location=build_data["images"][0]["location"],
        intermediate_registry_path=intermediate_registry_path,
        dockerhub_token=build_data["dockerhub_token"],
        project_access_token=access_token,
    )


def get_builds(repository_id: str) -> list[dict[str, Any]]:
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
    db_collection_repositories = collection("repositories")
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
            "No build found for given repository identifier. %s", repository_id
        )
        raise BuildNotFound from None
    return build_object_list


def get_build_info(build_id: str) -> dict[str, Any]:
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
    db_collection_builds = collection("builds")
    try:
        build_object = (
            db_collection_builds.find({"id": build_id}, {"_id": False}).limit(1).next()
        )
        del build_object["id"]
        build_object.pop("dockerhub_token", None)
        return repaired_build(build_object)
    except StopIteration:
        raise BuildNotFound from None


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
) -> None:
    """Create build and push to DockerHub.

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

    Raises:
        InternalServerError: If the build's directory would be outside
            `base_dir`.
        GitRefNotFound: If the branch, tag or commit isn't in the
            repository.

    If the build can't start, its directory is removed again.
    """
    # Build identifiers are generated, but keep the files of a build in
    # `base_dir` regardless
    base = os.path.abspath(base_dir)
    build_dir = os.path.abspath(os.path.join(base, build_id))
    # `join(base, "")` ends in a separator, also for the root directory
    if not build_dir.startswith(os.path.join(base, "")):
        logger.error("Directory of build %s is outside the base directory.", build_id)
        raise InternalServerError
    deployment_file_location = f"{base_dir}/{build_id}/{build_id}.yaml"
    config_file_location = os.path.join(build_dir, "config.json")

    try:
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
            f"{clone_path}/{dockerfile_location}",
            intermediate_registry_path,
            clone_path,
            deployment_file_location,
            f"{build_id}/config.json",
            project_access_token,
        )

        # Create dockerhub config file
        create_dockerhub_config_file(
            dockerhub_token=dockerhub_token,
            config_file_location=config_file_location,
        )

        # Create kaniko deployment to build and publish image.
        build_push_image_using_kaniko(deployment_file_location=deployment_file_location)
    except Exception:
        # No pod uses the files of a build that didn't start
        shutil.rmtree(build_dir, ignore_errors=True)
        raise


def git_clone_and_checkout(
    repo_url: str, branch: str, commit: str, base_dir: str, build_id: str
) -> str:
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
        GitRefNotFound: Raised when the branch, or the tag or commit, isn't in
            the repository.
    """
    repo_name = repo_url.split("/")[4].split(".", maxsplit=1)[0]
    clone_path = f"{base_dir}/{build_id}/{repo_name}"
    try:
        repo = Repo.clone_from(repo_url, clone_path)
    except GitCommandError:
        raise GitCloningError from None
    # Look the branch and the tag or commit up before checking them out, so
    # that unknown ones are told apart from other errors, and never passed to
    # Git as options or as revisions with a suffix (e.g. `dev~1`)
    remote_branch = f"refs/remotes/origin/{branch}"
    try:
        if branch != "":
            repo.git.show_ref("--verify", "--quiet", remote_branch)
        target = ""
        if commit != "":
            if commit.startswith("-"):
                raise GitRefNotFound
            target = repo.git.rev_parse("--verify", "--quiet", f"{commit}^{{commit}}")
    except GitCommandError:
        raise GitRefNotFound from None
    try:
        if branch != "":
            repo.git.checkout("-B", branch, remote_branch)
        # Check out the tag or commit, if any, else stay at the branch's head
        if target != "":
            repo.git.checkout(target)
    except GitCommandError:
        raise GitCloningError from None
    return clone_path


def create_deployment_YAML(
    dockerfile_location: str,
    intermediate_registry_path: str,
    build_context: str,
    deployment_file_location: str,
    config_file_location: str,
    project_access_token: str,
) -> str:
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
        with open(template_file) as file_stream:
            data = yaml.safe_load(file_stream)
        data["metadata"]["name"] = build_id
        data["spec"]["containers"][0]["args"] = [
            f"--dockerfile={dockerfile_location}",
            f"--destination={intermediate_registry_path}",
            f"--context={build_context}",
            "--cleanup",
        ]
        data["spec"]["containers"][0]["volumeMounts"][1]["mountPath"] = (
            "/kaniko/.docker/config.json"
        )
        data["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"] = os.getenv(
            "PV_NAME"
        )
        data["spec"]["containers"][0]["volumeMounts"][1]["subPath"] = (
            config_file_location
        )
        data["spec"]["containers"][0]["env"][0]["value"] = build_id  # BUILDNAME
        data["spec"]["containers"][0]["env"][1]["value"] = (
            project_access_token  # ACCESSTOKEN
        )
        if os.getenv("NAMESPACE"):
            data["spec"]["containers"][0]["env"][2]["value"] = os.getenv(
                "NAMESPACE"
            )  # NAMESPACE
        else:
            data["spec"]["containers"][0]["env"][2]["value"] = "default"
        data["spec"]["containers"][0]["env"][3]["value"] = os.getenv("PUBGRADE_URL")
        data["spec"]["containers"][0]["env"][4]["value"] = "8080"  # PORT
        with open(deployment_file_location, "w") as yaml_file:
            yaml_file.write(yaml.dump(data, default_flow_style=False))
        return deployment_file_location
    except OSError:
        raise


def create_dockerhub_config_file(
    dockerhub_token: str, config_file_location: str
) -> None:
    """Create dockerhub config file.

    Args:
        dockerhub_token (str): Base 64 encoded USER:PASSWORD to access
        dockerhub to push image `echo -n USER:PASSWD | base64`
        config_file_location (str): Location to create Dockerhub config file,
        it contains dockerhub access token.
    """
    intermediate_registry_format = endpoints()["builds"][
        "intermediate_registery_format"
    ]
    registry = intermediate_registry_format.split("/", 1)[0]
    token = os.getenv("INTERMEDIATE_REGISTRY_TOKEN")
    template_config_file = (
        f'{{\n"auths": {{\n"{registry}": {{\n"auth": "{token}"\n        }}\n    }}\n}}'
    )
    with open(config_file_location, "w") as config_file:
        config_file.write(template_config_file)


def build_push_image_using_kaniko(deployment_file_location: str) -> None:
    """Create kaniko deployment. Build and push image.

    Args:
        deployment_file_location (str): Location of kaniko deployment file.

    Raises:
        CreatePodError: Raised when unable to create deployment.
    """
    # Retrieve values of NAMESPACE and KUBERNETES_SERVICE_HOST from
    # environment variables.
    namespace = os.getenv("NAMESPACE") or "default"
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        config.load_incluster_config()
    else:
        config.load_kube_config()
    v1 = client.CoreV1Api()

    # Create namespaced pod using kubernetes CoreV1Api from kaniko
    # deployment file.
    with open(deployment_file_location) as f:
        dep = yaml.safe_load(f)
        name = (dep.get("metadata") or {}).get("name")
        try:
            v1.create_namespaced_pod(body=dep, namespace=namespace)
        except ApiException as e:
            logger.error("Creating pod %s failed: %s %s", name, e.status, e.reason)
            raise CreatePodError from None
        logger.info("Pod %s created.", name)


def build_completed(
    repository_id: str, build_id: str, project_access_token: str
) -> dict[str, str]:
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
        BuildsDisabled: Raised when builds are switched off.
    """
    if not builds_enabled():
        raise BuildsDisabled
    db_collection_repositories = collection("repositories")
    db_collection_builds = collection("builds")

    data_from_db = db_collection_repositories.find_one({"id": repository_id})
    if data_from_db is None:
        raise RepositoryNotFound
    if data_from_db["access_token"] != project_access_token:
        raise Unauthorized
    if build_id not in data_from_db.get("build_list", []):
        raise BuildNotFound
    try:
        data = (
            db_collection_builds.find({"id": build_id}, {"_id": False}).limit(1).next()
        )
        data["status"] = "SUCCEEDED"
        data["finished_at"] = now()

        intermediate_registry_format = endpoints()["builds"][
            "intermediate_registery_format"
        ]
        trigger_signing_image(
            image_path=data["images"][0]["name"],
            dockerhub_token=data["dockerhub_token"],
            pull_tag=intermediate_registry_format.format(
                data["images"][0]["name"].split("/")[1].split(":")[0]
            ),
            push_tag=data["images"][0]["name"],
        )

        db_collection_builds.update_one({"id": data["id"]}, {"$set": data})
        remove_files(
            f"{BASE_DIR}/{build_id}",
            build_id,
            os.getenv("NAMESPACE", "default"),
        )

        # Notifies available subscriptions registered for the repository.
        notify_all_subscriptions(
            data_from_db.get("subscription_list", []),
            data["images"][0]["name"],
            build_id,
        )
        return {"id": build_id}
    except StopIteration:
        raise BuildNotFound from None


def remove_files(dir_location: str, pod_name: str, namespace: str) -> None:
    """Removes build directory and kaniko pod.

    Args:
        dir_location (str): Path of directory containing build files.
        pod_name (str): Name of kaniko pod which is completed and needs to be
        deleted.
        namespace (str): Namespace of pod.
    """
    shutil.rmtree(dir_location)
    delete_pod(pod_name, namespace)


def delete_pod(name: str, namespace: str) -> Any:
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
        logger.error("Deleting pod %s failed: %s %s", name, e.status, e.reason)
        raise DeletePodError from None


def trigger_signing_image(
    dockerhub_token: str, image_path: str, pull_tag: str, push_tag: str
) -> None:
    """Trigger the signing and publication of a built image on GitHub.

    Dispatches the `sign-image` event to the repository in
    `endpoints.builds.gh_action_path`, whose workflow pulls the image from
    the intermediate registry, signs it and pushes it.

    Args:
        dockerhub_token: Base64 encoded `USER:PASSWORD` for Docker Hub.
        image_path: Name of the image.
        pull_tag: Image in the intermediate registry.
        push_tag: Image to publish.

    Raises:
        InternalServerError: If GitHub can't be reached.
    """
    username, password = base64.b64decode(dockerhub_token).decode("utf-8").split(":")
    url = "https://api.github.com/repos/{}/dispatches".format(
        endpoints()["builds"]["gh_action_path"]
    )
    payload = json.dumps(
        {
            "event_type": "sign-image",
            "client_payload": {
                "cosign_key": os.getenv("COSIGN_PRIVATE_KEY"),
                "docker_username": username,
                "docker_password": password,
                "cosign_password": os.getenv("COSIGN_PASSWORD"),
                "image_path": image_path,
                "pull_tag": pull_tag,
                "push_tag": push_tag,
            },
        }
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer {}".format(
            (os.getenv("GH_ACCESS_TOKEN") or "").strip()
        ),
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    try:
        requests.request(
            "POST", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT
        )
    except requests.exceptions.RequestException as error:
        # Log only the type: messages of requests can quote the Authorization
        # header
        logger.error(
            "Triggering the signing of %s failed: %s", push_tag, type(error).__name__
        )
        raise InternalServerError from None
