"""Report finished builds to Pubgrade.

Runs in its own image next to Pubgrade when Pubgrade builds images: every
`SLEEP_INTERVAL` seconds, it looks for build pods that succeeded in the
namespace `NAMESPACE` and reports each one to Pubgrade (`BROKER_URL`), with
the build's access token.
"""

from collections.abc import Iterable
import json
import logging
import os
import time
from typing import Any

from kubernetes import client, config
import requests

logger = logging.getLogger(__name__)

NAMESPACE = "broker"
BROKER_PORT = "8080"
SLEEP_INTERVAL = 5
BUILD_ID_LENGTH = 6
BROKER_URL = ""
# Seconds to connect to Pubgrade and for its response
REQUEST_TIMEOUT = 30

if os.getenv("NAMESPACE"):
    NAMESPACE = os.getenv("NAMESPACE", NAMESPACE)

if os.getenv("KUBERNETES_SERVICE_HOST"):
    config.load_incluster_config()
else:
    config.load_kube_config()

if os.getenv("BROKER_URL"):
    BROKER_URL = os.getenv("BROKER_URL", "") + "/repositories/{}/builds/{}"

if os.getenv("BROKER_PORT"):
    BROKER_PORT = os.getenv("BROKER_PORT", BROKER_PORT)


def get_env(env: Iterable[Any], name: str) -> str | None:
    """Return the value of an environment variable of a container.

    Args:
        env: Environment variables of the container (`V1EnvVar`).
        name: Name of the variable.

    Returns:
        Its value, or `None` if the container doesn't have it.
    """
    for var in env:
        if var.name == name:
            return var.value
    return None


while True:
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=NAMESPACE, watch=False)
    for pod in pods.items:
        if pod.spec is None or pod.status is None:
            continue
        env = pod.spec.containers[0].env
        if env is None or pod.status.phase != "Succeeded":
            continue
        build_name = get_env(env, "BUILDNAME")
        access_token = get_env(env, "ACCESSTOKEN")
        if build_name is None or access_token is None:
            continue
        repo_id = build_name[:BUILD_ID_LENGTH]
        url = BROKER_URL.format(repo_id, build_name)
        payload = json.dumps({"id": build_name})
        headers = {
            "X-Project-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        try:
            requests.request(
                "PUT", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT
            )
        except requests.exceptions.RequestException as error:
            # Only the type: messages of requests can quote the headers
            logger.error(
                "Reporting build %s failed: %s", build_name, type(error).__name__
            )
    time.sleep(SLEEP_INTERVAL)
