#!/usr/bin/env bash
# Starts a throwaway k3s cluster in a container of its own and installs Pubgrade
# from its chart, for local checks and CI. Source this file; call `cluster_down`
# to remove everything again.
#
# Variables: E2E_NAME (name of the container, network and volume),
# PUBGRADE_IMAGE (a local image, by default built from this repository).

E2E_NAME="${E2E_NAME:-pubgrade-e2e}"
E2E_K3S_IMAGE="${E2E_K3S_IMAGE:-rancher/k3s:v1.31.5-k3s1}"
E2E_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
E2E_ADMIN_TOKEN="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')"
export E2E_ADMIN_TOKEN

# Run kubectl in the cluster
k() {
  docker exec -i "${E2E_NAME}" kubectl "$@"
}

# Remove the cluster, with its network and volume
cluster_down() {
  docker rm --force --volumes "${E2E_NAME}" > /dev/null 2>&1 || true
  docker network rm "${E2E_NAME}" > /dev/null 2>&1 || true
}

# Copy a local image into the cluster
load_image() {
  docker save "$1" | docker exec -i "${E2E_NAME}" ctr images import - > /dev/null
}

# Start the cluster and wait for it
cluster_up() {
  cluster_down
  docker network create "${E2E_NAME}" > /dev/null
  docker run --detach --privileged --name "${E2E_NAME}" \
    --network "${E2E_NAME}" --tmpfs /run --tmpfs /var/run \
    "${E2E_K3S_IMAGE}" server --disable traefik --disable metrics-server \
    > /dev/null
  local _
  for _ in $(seq 1 60); do
    if k get serviceaccount default > /dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "::error::Cluster did not start"
  docker logs --tail 30 "${E2E_NAME}"
  return 1
}

# Install Pubgrade from the chart, with a configuration Secret that has an admin
# user. Arguments are passed to `helm install`
install_pubgrade() {
  local image="${PUBGRADE_IMAGE:-pubgrade:e2e}" config
  if [ -z "${PUBGRADE_IMAGE:-}" ]; then
    docker build --quiet --tag "${image}" "${E2E_REPO}" > /dev/null
  fi
  load_image "${image}"
  k create namespace pubgrade > /dev/null
  config="$(sed "s/admin_users: \[\]/admin_users: [{name: e2e, uid: e2e, user_access_token: ${E2E_ADMIN_TOKEN}}]/" \
    "${E2E_REPO}/pubgrade/config.yaml")"
  k create secret generic pubgrade-config --namespace pubgrade \
    --from-literal=config.yaml="${config}" > /dev/null
  helm template pubgrade "${E2E_REPO}/helm" --namespace pubgrade \
    --set pubgrade.image="${image}" --set pubgrade.imagePullPolicy=Never \
    --set pubgrade.configSecret=pubgrade-config "$@" \
    | k apply --namespace pubgrade --filename - > /dev/null
  k rollout status deployment/mongodb --namespace pubgrade --timeout=180s
  k rollout status deployment/pubgrade --namespace pubgrade --timeout=180s
}

# Call Pubgrade's API from inside the cluster's network. Usage:
# `api <method> <path> [headers as JSON] [body]`; prints the body, then the status
api() {
  local method="$1" path="$2"
  shift 2
  k exec --namespace pubgrade deployment/pubgrade -- python -c '
import json, sys, urllib.error, urllib.request
method, path, headers, data = sys.argv[1:5]
request = urllib.request.Request(
    "http://localhost:8080" + path,
    method=method,
    headers=json.loads(headers),
    data=data.encode() if data else None,
)
try:
    with urllib.request.urlopen(request, timeout=180) as response:
        print(response.read().decode())
        print(response.status)
except urllib.error.HTTPError as error:
    print(error.read().decode())
    print(error.code)
' "${method}" "${path}" "${1:-{\}}" "${2:-}"
}
