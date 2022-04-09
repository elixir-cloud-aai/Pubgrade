from kubernetes import client, config
import os
import time
import requests
import json

NAMESPACE = "broker"
BROKER_URL = "http://broker-service.broker"
BROKER_PORT = "8080"
SLEEP_INTERVAL = 5
BUILD_ID_LENGTH = 6

if os.getenv("NAMESPACE"):
    NAMESPACE = os.getenv("NAMESPACE")

if os.getenv("KUBERNETES_SERVICE_HOST"):
    config.load_incluster_config()
else:
    config.load_kube_config()

if os.getenv("BROKER_URL"):
    BROKER_URL = os.getenv("BROKER_URL")

if os.getenv("BROKER_PORT"):
    BROKER_PORT = os.getenv("BROKER_PORT")


while True:
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=NAMESPACE, watch=False)
    for pod in pods.items:
        if pod.spec.containers[0].env is not None:
            if pod.status.phase == "Succeeded":
                if (
                    "BUILDNAME" == pod.spec.containers[0].env[0].name
                    and "ACCESSTOKEN" == pod.spec.containers[0].env[1].name
                ):
                    build_name = pod.spec.containers[0].env[0].value
                    repo_id = build_name[:BUILD_ID_LENGTH]
                    access_token = pod.spec.containers[0].env[1].value
                    url = "{}:{}/repositories/{}/builds/{}".format(
                        BROKER_URL, BROKER_PORT, repo_id, build_name
                    )
                    payload = json.dumps({"id": build_name})
                    headers = {
                        "X-Project-Access-Token": access_token,
                        "Content-Type": "application/json",
                    }
                    response = requests.request(
                        "PUT", url, headers=headers, data=payload
                    )
    time.sleep(SLEEP_INTERVAL)
