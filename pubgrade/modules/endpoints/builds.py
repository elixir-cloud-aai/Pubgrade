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
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
import requests
from werkzeug.exceptions import Unauthorized
import yaml

from pubgrade.charsets import get_charset
from pubgrade.errors.exceptions import (
    BuildCanceled,
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
from pubgrade.modules.endpoints.repositories import (
    ACCEPTING,
    accepts_additions,
    generate_id,
)
from pubgrade.modules.endpoints.subscriptions import notify_all_subscriptions
from pubgrade.settings import collection, endpoints
from pubgrade.timestamps import now, repaired_build

logger = logging.getLogger(__name__)

template_file = "/app/pubgrade/modules/endpoints/kaniko/template.yaml"
BASE_DIR = os.getenv("BASE_DIR", "/pubgrade_temp_files")
# Seconds to connect to GitHub and for its response, when triggering the
# signing of an image
REQUEST_TIMEOUT = 30
# Seconds to connect to the Kubernetes API and for its response, when
# deleting a pod
KUBERNETES_TIMEOUT = 10

# States of builds that have finished
FINISHED = ["SUCCEEDED", "FAILED"]
# State of builds that have been withdrawn (`cancel_build()`); they keep it
CANCELED = "CANCELED"
# Matches builds that haven't been withdrawn
NOT_CANCELED: dict[str, Any] = {"status": {"$ne": CANCELED}}

# An abbreviated or full commit hash (SHA-1 or SHA-256)
COMMIT_HASH = re.compile(r"[0-9a-fA-F]{4,64}")

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

    A build withdrawn meanwhile stays `CANCELED`.

    Args:
        build_id: Identifier of the build.
        image: Name and tag of the image.
        subscriptions: Identifiers of the repository's subscriptions.
    """
    results = notify_all_subscriptions(subscriptions, image, build_id)
    failed = any(result["result"] == "failed" for result in results)
    collection("builds").update_one(
        {"id": build_id, **NOT_CANCELED},
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
    kept. Until then, while the repository is cloned, the build is listed as
    `QUEUED`.

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
        identifier, or is being deleted; a build registered meanwhile is
        removed again.
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
        pushed = db_collection_repositories.update_one(
            {"id": repository_id, **ACCEPTING},
            {"$push": {"build_list": build_data["id"]}},
        )
        if pushed.matched_count == 0:
            raise RepositoryNotFound
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
        # The repository's deletion may have started after the build was
        # listed, and missed it in the database
        ensure_accepting(repository_id, build_data["id"])
        publish_prebuilt_image(
            build_data["id"],
            build_data["images"][0]["name"],
            data_from_db.get("subscription_list", []),
        )
        return {"id": build_data["id"]}
    try:
        start_build(build_data, data_from_db["url"], access_token)
    except CreatePodError:
        # The pod may have been created nonetheless, and reports to the build
        ensure_accepting(repository_id, build_data["id"])
        raise
    except Exception:
        # The client gets an error instead of the build's identifier, so the
        # build is not kept; the client gets the original error even if this
        # fails. The repository's list goes first: a listed build that is
        # missing would break the listing of the repository's builds.
        try:
            db_collection_repositories.update_one(
                {"id": repository_id}, {"$pull": {"build_list": build_data["id"]}}
            )
            db_collection_builds.delete_one({"id": build_data["id"]})
        except Exception as error:
            logger.error(
                "Removing build %s, which could not start, failed: %s",
                build_data["id"],
                type(error).__name__,
            )
        else:
            logger.info("Removed build %s, which could not start.", build_data["id"])
        raise
    ensure_accepting(repository_id, build_data["id"])
    return {"id": build_data["id"]}


def start_build(build_data: dict[str, Any], repo_url: str, access_token: str) -> None:
    """Start a registered build.

    Args:
        build_data (dict): The build, as registered.
        repo_url (str): URL of the repository.
        access_token (str): Access token of the repository.

    Raises:
        GitRefNotFound: Raised when the branch, tag or commit isn't in the
            repository.
        GitCloningError: Raised when cloning or checking out the repository
            fails.
    """
    head_commit = build_data["head_commit"]
    if "branch" in head_commit:
        branch = head_commit["branch"]
        commit_sha = head_commit.get("commit_sha")
        # An empty `commit_sha` would build the branch's head
        if commit_sha == "":
            raise GitRefNotFound
        commit_sha = commit_sha or ""
        name = branch
    else:
        branch = ""
        commit_sha = head_commit["tag"]
        name = commit_sha
    # An empty branch or tag would build the repository's default branch
    if name == "":
        raise GitRefNotFound
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

    If the build can't start, its directory is removed again, unless creating
    its pod failed: the pod may have been created nonetheless.

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
        CreatePodError: If creating the build's pod failed.
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
    except Exception:
        # No pod uses the files of a build that didn't start
        remove_build_dir(build_dir, build_id)
        raise

    # Create kaniko deployment to build and publish image. The pod may have
    # been created even if this fails (e.g., a lost response), so the build's
    # files are kept
    try:
        build_push_image_using_kaniko(deployment_file_location=deployment_file_location)
    except CreatePodError:
        raise
    except Exception as error:
        logger.error(
            "Creating the pod of build %s failed: %s", build_id, type(error).__name__
        )
        raise CreatePodError from None


def remove_build_dir(build_dir: str, build_id: str) -> None:
    """Remove the directory of a build that didn't start or was stopped, if any.

    Args:
        build_dir: Directory of the build.
        build_id: Identifier of the build.
    """
    try:
        shutil.rmtree(build_dir)
    except FileNotFoundError:
        pass
    except OSError as error:
        logger.error(
            "Removing the files of build %s failed: %s", build_id, type(error).__name__
        )


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
    # that unknown ones are told apart from other errors. Only exact names of
    # branches and tags, and hexadecimal commit hashes, are accepted: no
    # options and no revision expressions (e.g. `dev~1`)
    remote_branch = f"refs/remotes/origin/{branch}"
    try:
        if branch != "":
            # `origin/HEAD` is a remote ref, but not a branch
            if branch == "HEAD" or branch.startswith("-"):
                raise GitRefNotFound
            repo.git.show_ref("--verify", "--quiet", remote_branch)
        target = ""
        if commit != "":
            # With a branch, `commit` is a `commit_sha`, not a tag
            target = resolve_tag_or_commit(repo, commit, tags=branch == "")
    except GitCommandError as error:
        # Git's lookups exit with 1 for unknown (and ambiguous) names
        if error.status == 1:
            raise GitRefNotFound from None
        raise GitCloningError from None
    try:
        if branch != "":
            repo.git.checkout("-B", branch, remote_branch)
        # Check out the tag or commit, if any, else stay at the branch's head
        if target != "":
            repo.git.checkout(target)
    except GitCommandError:
        raise GitCloningError from None
    return clone_path


def resolve_tag_or_commit(repo: Repo, name: str, tags: bool = True) -> str:
    """Get the commit of a tag or of an abbreviated or full commit hash.

    Args:
        repo: Clone of the repository.
        name: Name of a tag, or a commit hash with 4 to 64 hexadecimal digits.
        tags: Whether `name` may be a tag; if not, only commit hashes are
            accepted.

    Returns:
        The full hash of the commit.

    Raises:
        GitRefNotFound: If `name` is neither a tag nor a commit hash.
        GitCommandError: If Git can't resolve the tag or hash to a commit
            (status 1 if it isn't in the repository or isn't unique).
    """
    revision = name
    if tags:
        tag = f"refs/tags/{name}"
        try:
            repo.git.show_ref("--verify", "--quiet", tag)
            revision = tag
        except GitCommandError as error:
            if error.status != 1:
                raise
    if revision == name and not COMMIT_HASH.fullmatch(name):
        raise GitRefNotFound
    commit: str = repo.git.rev_parse("--verify", "--quiet", f"{revision}^{{commit}}")
    return commit


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


def load_cluster_config() -> None:
    """Load the configuration of the Kubernetes API.

    In a cluster (`KUBERNETES_SERVICE_HOST` is set), from its service
    account; otherwise from the kubeconfig.
    """
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        config.load_incluster_config()
    else:
        config.load_kube_config()


def build_push_image_using_kaniko(deployment_file_location: str) -> None:
    """Create kaniko deployment. Build and push image.

    Args:
        deployment_file_location (str): Location of kaniko deployment file.

    Raises:
        CreatePodError: Raised when unable to create deployment.
    """
    namespace = os.getenv("NAMESPACE") or "default"
    load_cluster_config()
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
    """Record the completion of a build, reported by its pod.

    This is the internal callback of the build pods (via the updater), not a
    way to change a build: a changed build is registered anew. A build that
    has been withdrawn (`CANCELED`), also while its completion is processed,
    doesn't succeed, and its subscriptions aren't notified.

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
        BuildCanceled: Raised when the build has been withdrawn.
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
        if data.get("status") == CANCELED:
            raise BuildCanceled

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

        # Only if the build hasn't been withdrawn meanwhile, which stopped it
        completed = db_collection_builds.update_one(
            {"id": build_id, **NOT_CANCELED},
            {"$set": {"status": "SUCCEEDED", "finished_at": now()}},
        )
        if completed.matched_count == 0:
            raise BuildCanceled
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


def cancel_build(
    repository_id: str, build_id: str, access_token: str
) -> dict[str, str]:
    """Withdraw a build, keeping its record.

    The build is marked `CANCELED` and stays listed; a build that hadn't
    finished gets its `finished_at`. With builds switched on, its pod and
    files are removed (see `stop_builds()`), and its completion is no longer
    recorded: it doesn't succeed, and no one is notified. If the pod or the
    files can't be removed, the build gets its previous state back, so that
    the request can be repeated. Deployments that have been notified keep
    what they pulled: nothing is undeployed, notified again or deleted from
    a registry.

    Args:
        repository_id: Identifier of the repository.
        build_id: Identifier of the build.
        access_token: Access token of the repository.

    Returns:
        The identifier of the build.

    Raises:
        RepositoryNotFound: Raised when the repository is not found.
        Unauthorized: Raised when the access token isn't the repository's.
        BuildNotFound: Raised when the build is not found, or isn't the
            repository's.
        BuildCanceled: Raised when the build has been withdrawn already.
        DeletePodError: Raised when the build's pod can't be deleted.
        OSError: Raised when the build's files can't be removed.
    """
    repository = collection("repositories").find_one({"id": repository_id})
    if repository is None:
        raise RepositoryNotFound
    if repository["access_token"] != access_token:
        raise Unauthorized
    if build_id not in repository.get("build_list", []):
        raise BuildNotFound
    db_collection_builds = collection("builds")
    previous = db_collection_builds.find_one_and_update(
        {"id": build_id, **NOT_CANCELED},
        {"$set": {"status": CANCELED}},
        projection={"_id": False, "status": True, "finished_at": True},
        return_document=ReturnDocument.BEFORE,
    )
    if previous is None:
        if db_collection_builds.find_one({"id": build_id}, {"_id": True}) is None:
            raise BuildNotFound
        raise BuildCanceled
    if previous.get("status") in FINISHED:
        logger.info("Canceled build %s, which had finished.", build_id)
        return {"id": build_id}
    try:
        stop_builds([build_id], force=True)
    except Exception:
        # The build is as before, so that the request can be repeated
        db_collection_builds.update_one(
            {"id": build_id, "status": CANCELED},
            {"$set": {"status": previous.get("status")}},
        )
        raise
    if previous.get("finished_at") is None:
        db_collection_builds.update_one(
            {"id": build_id, "finished_at": None},
            {"$set": {"finished_at": now()}},
        )
    logger.info("Canceled build %s.", build_id)
    return {"id": build_id}


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


def delete_pod(name: str, namespace: str, missing_ok: bool = False) -> Any:
    """Delete pod.

    Args:
        name (str): Name of kaniko pod which is completed and needs to be
        deleted.
        namespace (str): Namespace of pod.
        missing_ok: Whether a pod that doesn't exist counts as deleted.

    Returns:
        Response of CoreV1Api on deleting pod; None for a missing pod, with
        `missing_ok`.

    Raises:
        DeletePodError: Raised when encountered an error while deleting pod.
    """
    try:
        api_instance = client.CoreV1Api()
        api_response = api_instance.delete_namespaced_pod(
            name, namespace, _request_timeout=KUBERNETES_TIMEOUT
        )
        return api_response
    except ApiException as e:
        if missing_ok and e.status == 404:
            return None
        logger.error("Deleting pod %s failed: %s %s", name, e.status, e.reason)
        raise DeletePodError from None


def stop_builds(build_ids: list[str], force: bool = False) -> None:
    """Remove the pods and files of builds that may still have them.

    Only with builds switched on, as only then do builds have pods and
    files. Unfinished builds are stopped this way, and finished builds
    whose files are left because their cleanup failed are cleaned up.
    Canceled builds count as finished: they were stopped when they were
    canceled. Pods that no longer exist count as deleted, so this can be
    repeated after an error.

    Args:
        build_ids: Identifiers of the builds.
        force: Whether to stop the builds whatever their state, e.g., a
            build that is being canceled.

    Raises:
        DeletePodError: Raised when a pod can't be deleted; the builds after
            it are left as they are.
        OSError: Raised when a build's files can't be removed.
    """
    if not builds_enabled() or not build_ids:
        return
    unfinished = (
        set(build_ids)
        if force
        else {
            build["id"]
            for build in collection("builds").find(
                {"id": {"$in": build_ids}, "status": {"$nin": [*FINISHED, CANCELED]}},
                {"id": True, "_id": False},
            )
        }
    )
    # Directories of the builds; identifiers that would lead outside
    # `BASE_DIR` get none
    base = os.path.join(os.path.abspath(BASE_DIR), "")
    build_dirs: dict[str, str | None] = {}
    for build_id in build_ids:
        build_dir = os.path.abspath(os.path.join(base, build_id))
        if build_dir.startswith(base):
            build_dirs[build_id] = build_dir
        else:
            logger.error(
                "Directory of build %s is outside the base directory.", build_id
            )
            build_dirs[build_id] = None
    stopping = [
        build_id
        for build_id, build_dir in build_dirs.items()
        if build_id in unfinished
        or (build_dir is not None and os.path.isdir(build_dir))
    ]
    if not stopping:
        return
    load_cluster_config()
    namespace = os.getenv("NAMESPACE") or "default"
    for build_id in stopping:
        delete_pod(build_id, namespace, missing_ok=True)
        stopped_dir = build_dirs[build_id]
        # Checked again here, where the files are removed
        if stopped_dir is not None and stopped_dir.startswith(base):
            # Errors stop the deletion, which can then be repeated
            shutil.rmtree(stopped_dir, ignore_errors=False, onexc=_ignore_missing)
        logger.info("Stopped build %s.", build_id)


def _ignore_missing(function: Any, path: str, error: BaseException) -> None:
    """Ignore files that are gone already, when removing a directory.

    Args:
        function: Function that failed.
        path: Path it failed on.
        error: The error.

    Raises:
        BaseException: The error, unless the file is missing.
    """
    if not isinstance(error, FileNotFoundError):
        raise error


def ensure_accepting(repository_id: str, build_id: str) -> None:
    """Withdraw a new build if its repository is being deleted.

    The repository's deletion may have started after the build was listed,
    and missed its document or pod.

    Args:
        repository_id: Identifier of the repository.
        build_id: Identifier of the build.

    Raises:
        RepositoryNotFound: Raised when the repository is being deleted or
            is gone; the build has been withdrawn then.
    """
    if accepts_additions(repository_id):
        return
    withdraw_build(repository_id, build_id)
    raise RepositoryNotFound


def withdraw_build(repository_id: str, build_id: str) -> None:
    """Remove a build whose repository is being deleted.

    The build leaves the repository's list first, in case the deletion
    fails and the repository stays. Its pod and files, if any, are removed
    as far as possible; errors are logged, as the client gets a 404 anyway.

    Args:
        repository_id: Identifier of the repository.
        build_id: Identifier of the build.
    """
    collection("repositories").update_one(
        {"id": repository_id}, {"$pull": {"build_list": build_id}}
    )
    try:
        stop_builds([build_id])
    except Exception as error:
        logger.error(
            "Build %s could not be stopped: %s", build_id, type(error).__name__
        )
    collection("builds").delete_one({"id": build_id})
    logger.info("Removed build %s, whose repository is being deleted.", build_id)


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
