#!/usr/bin/env bash
# Runs `tests/e2e/check.sh` against Pubgrade on a throwaway local cluster, as
# an operator would against a deployment: from outside the cluster, with a
# kubeconfig and Pubgrade's URL. Needs Docker, Helm, kubectl, curl and jq;
# removes everything afterwards.
#
# Variables: SIDECAR_IMAGE (a local image, by default built from the branch
# `dev` of Pubgrade-Sidecar), and those of `cluster.sh` and `check.sh`.
#
# Usage: tests/e2e/check-local.sh

set -euo pipefail

# shellcheck source=tests/e2e/cluster.sh
source "$(dirname "$0")/cluster.sh"

SIDECAR_REPO="https://github.com/elixir-cloud-aai/Pubgrade-Sidecar.git#dev"
PORT=18080

kubeconfig_dir="$(umask 077 && mktemp -d)"
down() {
  cluster_down
  rm -rf "${kubeconfig_dir}"
}
trap down EXIT

if [ -z "${SIDECAR_IMAGE:-}" ]; then
  SIDECAR_IMAGE=pubgrade-sidecar:e2e
  docker build --quiet --tag "${SIDECAR_IMAGE}" "${SIDECAR_REPO}" > /dev/null
fi

cluster_up
load_image "${SIDECAR_IMAGE}"
install_pubgrade

# The cluster's API and Pubgrade, at the container's address on its network
address="$(docker inspect --format \
  "{{(index .NetworkSettings.Networks \"${E2E_NAME}\").IPAddress}}" "${E2E_NAME}")"
docker exec "${E2E_NAME}" cat /etc/rancher/k3s/k3s.yaml \
  | sed "s#https://127.0.0.1:6443#https://${address}:6443#" \
    > "${kubeconfig_dir}/config"
docker exec --detach "${E2E_NAME}" kubectl port-forward --address 0.0.0.0 \
  --namespace pubgrade service/pubgrade-service "${PORT}:8080"
for _ in $(seq 1 30); do
  if curl --fail --silent --output /dev/null "http://${address}:${PORT}/ui/"; then
    break
  fi
  sleep 1
done

KUBECONFIG="${kubeconfig_dir}/config" \
  PUBGRADE_URL="http://${address}:${PORT}" \
  PUBGRADE_ADMIN_ID=e2e PUBGRADE_ADMIN_TOKEN="${E2E_ADMIN_TOKEN}" \
  CHECK_SIDECAR_IMAGE="${SIDECAR_IMAGE}" \
  "$(dirname "$0")/check.sh"
