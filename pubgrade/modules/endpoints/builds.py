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

logger = logging.getLogger(__name__)

template_file = '/app/pubgrade/modules/endpoints/kaniko/template.yaml'
BASE_DIR = os.getenv("BASE_DIR")
if BASE_DIR is None:
    BASE_DIR = '/pubgrade_temp_files'
gh_action_path="akash2237778/github-actions",
gh_access_token="YWthc2gyMjM3Nzc4OmdocF9wRW5KUHJFVXd4cWJ6YjNrNTU4ZHdtODk0cFl4TWUwdDlENlE=",
cosign_password="redhat"

cosign_private_key="""-----BEGIN ENCRYPTED COSIGN PRIVATE KEY-----
eyJrZGYiOnsibmFtZSI6InNjcnlwdCIsInBhcmFtcyI6eyJOIjozMjc2OCwiciI6
OCwicCI6MX0sInNhbHQiOiIwQjJtUmxkd2Z6aERzL24yOGZHSk1maXpubmJxZXB0
YktHaEtLVDdJUTNrPSJ9LCJjaXBoZXIiOnsibmFtZSI6Im5hY2wvc2VjcmV0Ym94
Iiwibm9uY2UiOiJrTkx4UVRNb0JmWFdBbzB4U0drK0xZbEJ4V0xHSEN1NyJ9LCJj
aXBoZXJ0ZXh0IjoiWGJPYW5oMnN1UUpoY0xVNFlSdzJzZzlocUQrOFpiVGZRUnJj
RmpNM1dRbmljZldpZlYydTlIVXhMamFQRmNvdnp5M0lsNG5zZDVwcnlWMHo1ak9j
blR4VXllM3dySWpGZHpURXpKemUrRVB1ZkZtc1lGdE85bHgveWszZmZBbG5ZbTlw
VklNMm5wQVlPek0yWWRNQnloQVg3ajBXb3ZESmN4cmxVVGtZNTNMdG12M2xsNVpK
RDMwU0ZiRjNYbi9KOGh4a2M4cGFjQlh0ZFE9PSJ9
-----END ENCRYPTED COSIGN PRIVATE KEY-----"""


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
            create_build(
                repo_url=data_from_db["url"],
                branch=branch,
                commit=commit_sha,
                base_dir=BASE_DIR,
                build_id=build_data["id"],
                dockerfile_location=build_data["images"][0]["location"],
                registry_destination=build_data["images"][0]["name"],
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
    registry_destination: str,
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
        registry_destination (str): Path of repository to push build image.
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
        registry_destination,
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
    registry_destination: str,
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
        registry_destination (str): Path of repository to push build image.
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
            f"--destination={registry_destination}",
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
        ] = "http://pubgrade-service.pubgrade-ns"  # PUBGRADE_URL
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
    template_config_file = (
        """{
"auths": {
"https://index.docker.io/v1/": {
"auth": "%s"
        }
    }
}"""
        % dockerhub_token
    )
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

        # trigger_signing_image(
        #     gh_action_path=gh_action_path,
        #     gh_access_token=gh_access_token,
        #     image_path=data["images"][0]["name"],
        #     cosign_private_key=cosign_private_key,
        #     dockerhub_token=data["dockerhub_token"],
        #     cosign_password=cosign_password
        # )

        db_collection_builds.update_one({"id": data['id']},
                                        {"$set": data})
        remove_files(BASE_DIR +"/" + build_id, build_id, "pubgrade")

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
    # shutil.rmtree(dir_location)
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
        print(name)
        print(namespace)
        api_response = api_instance.delete_namespaced_pod(name, namespace)
        return api_response
    except ApiException as e:
        logger.error(
            "Exception when calling "
            "AppsV1Api->delete_namespaced_deployment: "
            "%s\n" % e
        )
        raise DeletePodError

# [2023-01-15 15:52:55,887: ERROR ] Traceback (most recent call last):\n File "/app/pubgrade/modules/endpoints/builds.py", line 540, in delete_pod\n api_response = api_instance.delete_namespaced_pod(name, namespace)\n File "/usr/local/lib/python3.9/site-packages/kubernetes/client/api/core_v1_api.py", line 12141, in delete_namespaced_pod\n return self.delete_namespaced_pod_with_http_info(name, namespace, **kwargs) # noqa: E501\n File "/usr/local/lib/python3.9/site-packages/kubernetes/client/api/core_v1_api.py", line 12248, in delete_namespaced_pod_with_http_info\n return self.api_client.call_api(\n File "/usr/local/lib/python3.9/site-packages/kubernetes/client/api_client.py", line 348, in call_api\n return self.__call_api(resource_path, method,\n File "/usr/local/lib/python3.9/site-packages/kubernetes/client/api_client.py", line 180, in __call_api\n response_data = self.request(\n File "/usr/local/lib/python3.9/site-packages/kubernetes/client/api_client.py", line 415, in request\n return self.rest_client.DELETE(url,\n File "/usr/local/lib/python3.9/site-packages/kubernetes/client/rest.py", line 265, in DELETE\n return self.request("DELETE", url,\n File "/usr/local/lib/python3.9/site-packages/kubernetes/client/rest.py", line 233, in request\n raise ApiException(http_resp=r)\nkubernetes.client.exceptions.ApiException: (403)\nReason: Forbidden\nHTTP response headers: HTTPHeaderDict({'Audit-Id': 'b19e49df-4b85-4502-ad86-acc562208eb2', 'Cache-Control': 'no-cache, private', 'Content-Type': 'application/json', 'X-Content-Type-Options': 'nosniff', 'X-Kubernetes-Pf-Flowschema-Uid': '9be32bf1-fb16-42ed-ba4b-08e870d56884', 'X-Kubernetes-Pf-Prioritylevel-Uid': '65342b8c-d58f-47e4-b499-73e62bb393da', 'Date': 'Sun, 15 Jan 2023 15:52:55 GMT', 'Content-Length': '402'})\nHTTP response body: {"kind":"Status","apiVersion":"v1","metadata":{},"status":"Failure","message":"pods \"giii.srairil\" is forbidden: User \"system:serviceaccount:pubgrade-ns:pubgrade\" cannot d
# elete resource \"pods\" in API group \"\" in the namespace \"pubgrade\": RBAC: clusterrole.rbac.authorization.k8s.io \"fleet-content\" not found","reason":"Forbidden","details":{"name":"giii.srairil","kind":"pods"},"code":403}\n\nDuring handling of the above exception, another exception occurred:\nTraceback (most recent call last):\n File "/usr/local/lib/python3.9/site-packages/flask/app.py", line 1950, in full_dispatch_request\n rv = self.dispatch_request()\n File "/usr/local/lib/python3.9/site-packages/flask/app.py", line 1936, in dispatch_request\n return self.view_functions[rule.endpoint](**req.view_args)\n File "/usr/local/lib/python3.9/site-packages/connexion/decorators/decorator.py", line 48, in wrapper\n response = function(request)\n File "/usr/local/lib/python3.9/site-packages/connexion/decorators/uri_parsing.py", line 144, in wrapper\n response = function(request)\n File "/usr/local/lib/python3.9/site-packages/connexion/decorators/validation.py", line 184, in wrapper\n response = function(request)\n File "/usr/local/lib/python3.9/site-packages/connexion/decorators/validation.py", line 384, in wrapper\n return function(request)\n File "/usr/local/lib/python3.9/site-packages/connexion/decorators/response.py", line 103, in wrapper\n response = function(request)\n File "/usr/local/lib/python3.9/site-packages/connexion/decorators/parameter.py", line 121, in wrapper\n return function(**kwargs)\n File "/usr/local/lib/python3.9/site-packages/foca/utils/logging.py", line 61, in _wrapper\n response = fn(*args, **kwargs)\n File "/app/pubgrade/modules/server.py", line 154, in updateBuild\n return build_completed(\n File "/app/pubgrade/modules/endpoints/builds.py", line 496, in build_completed\n remove_files(BASE_DIR +"/" + build_id, build_id, "pubgrade")\n File "/app/pubgrade/modules/endpoints/builds.py", line 521, in remove_files\n delete_pod(pod_name, namespace)\n File "/app/pubgrade/modules/endpoints/builds.py", line 548, in delete_pod\n raise DeletePodError\n
# pubgrade.errors.exceptions.DeletePodError: 500 Internal Server Error: The server encountered an internal error and was unable to complete your request. Either the server is overloaded or there is an error in the application. [foca.errors.exceptions]


def trigger_signing_image(gh_action_path: str, cosign_private_key: str, cosign_password: str, dockerhub_token: str, gh_access_token: str, image_path: str):

    username, password = base64.b64decode(dockerhub_token).decode('utf-8').split(":")
    url = "https://api.github.com/repos/{}/dispatches".format("akash2237778/github-actions")
    payload = json.dumps({
        "event_type": "sign-image",
        "client_payload": {
            "cosign_key": cosign_private_key,
            "docker_username": username,
            "docker_password": password,
            "cosign_password": cosign_password,
            "image_path": image_path
        }
    })
    headers = {
    'Accept': 'application/vnd.github+json',
    'Authorization': 'Bearer {}'.format("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"),
    'X-GitHub-Api-Version': '2022-11-28',
    'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload)






# from nacl import encoding, public

# def encrypt(public_key: str, secret_value: str) -> str:
#   """Encrypt a Unicode string using the public key."""
#   public_key = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
#   sealed_box = public.SealedBox(public_key)
#   encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
#   return b64encode(encrypted).decode("utf-8")


# def post_github_secrets(secret_keys: dict, github_pub_key: str, key_id: str, github_access_token: str, github_username: str, github_repo: str):

#     url = "https://api.github.com/repos/{}/{}/actions/secrets/{}"
    

#     for key, value in secret_keys.items():
#         url = url.format(github_username, github_repo, key)

#         encrypted_secret = encrypt(github_pub_key, value)

#         payload = json.dumps({
#             "encrypted_value": encrypted_secret,
#             "key_id": key_id
#         })
#         headers = {
#             'Accept': 'application/vnd.github.v3+json',
#             'Authorization': 'Basic {}'.format(github_access_token),
#             'Content-Type': 'application/json'
#         }
#         response = requests.request("PUT", url, headers=headers, data=payload)

#         if response.status_code is not 204:
#             logger.error('Unable to post secrets to github repo')


# key = "i+QSRQxCG4eWpYaJ4fdaCk+Q6WmtgxmQ1+OYs9FZfn8="
# key_id = "568250167242549743"
# github_access_token = "YWthc2gyMjM3Nzc4OmdocF9wRW5KUHJFVXd4cWJ6YjNrNTU4ZHdtODk0cFl4TWUwdDlENlE="
# github_repo = "github-actions"
# github_username = "akash2237778"


    # post_github_secrets(
    #     secret_keys=secret_keys,
    #     github_pub_key="i+QSRQxCG4eWpYaJ4fdaCk+Q6WmtgxmQ1+OYs9FZfn8=",
    #     key_id="568250167242549743",
    #     github_access_token="YWthc2gyMjM3Nzc4OmdocF9wRW5KUHJFVXd4cWJ6YjNrNTU4ZHdtODk0cFl4TWUwdDlENlE=",
    #     github_repo="github-actions",
    #     github_username = "akash2237778"
    # )
