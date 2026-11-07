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

NAMESPACE = os.getenv("NAMESPACE") or "broker"
SLEEP_INTERVAL = 5
BUILD_ID_LENGTH = 6
_BROKER = os.getenv("BROKER_URL", "")
# URL of the build endpoint, with placeholders for the repository and build
BROKER_URL = f"{_BROKER}/repositories/{{}}/builds/{{}}" if _BROKER else ""
# Seconds to connect to Pubgrade and for its response
REQUEST_TIMEOUT = 30


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


def report_build(pod: Any) -> None:
    """Report a build pod to Pubgrade if it succeeded.

    Pods without a spec or status, that haven't succeeded, or whose first
    container lacks `BUILDNAME` or `ACCESSTOKEN`, are skipped. Failed
    requests are logged, so that the next pods are still reported.

    Args:
        pod: The pod (`V1Pod`).
    """
    if pod.spec is None or pod.status is None:
        return
    env = pod.spec.containers[0].env
    if env is None or pod.status.phase != "Succeeded":
        return
    build_name = get_env(env, "BUILDNAME")
    access_token = get_env(env, "ACCESSTOKEN")
    if build_name is None or access_token is None:
        return
    repo_id = build_name[:BUILD_ID_LENGTH]
    url = BROKER_URL.format(repo_id, build_name)
    payload = json.dumps({"id": build_name})
    headers = {
        "X-Project-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    try:
        response = requests.request(
            "PUT", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT
        )
        # Error responses fail too (`HTTPError`)
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        # Only the type: messages of requests can quote the headers
        logger.error("Reporting build %s failed: %s", build_name, type(error).__name__)


def report_builds() -> None:
    """Report the succeeded build pods of the namespace to Pubgrade."""
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=NAMESPACE, watch=False)
    for pod in pods.items:
        report_build(pod)


def main() -> None:
    """Load the cluster configuration and report builds until stopped."""
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        config.load_incluster_config()
    else:
        config.load_kube_config()
    while True:
        report_builds()
        time.sleep(SLEEP_INTERVAL)


if __name__ == "__main__":  # pragma: no cover
    main()
