#!/usr/bin/env bash
# Checks the rendered chart in its variants, for CI's chart job.
# Usage: tests/chart.sh

set -euo pipefail

cd "$(dirname "$0")/.."
status=0

render() {
  helm template pubgrade helm --namespace pubgrade "$@"
}

# Check that a pattern is (`has`) or isn't (`hasnt`) in the rendered chart
has() {
  if ! grep -Eq "$2" <<< "$1"; then
    echo "::error::$3: expected '$2'"
    status=1
  fi
}
hasnt() {
  if grep -Eq "$2" <<< "$1"; then
    echo "::error::$3: unexpected '$2'"
    status=1
  fi
}

# Without builds, on plain Kubernetes
chart="$(render)"
for pattern in 'kind: (Ingress|Route|Role|RoleBinding|ServiceAccount|Secret)$' \
  'name: pubgrade-updater' 'pubgrade-builds' 'runAsUser' 'nodePort|NodePort' \
  'akash' 'kind: PersistentVolume$' 'GH_ACCESS_TOKEN'; do
  hasnt "${chart}" "${pattern}" "default"
done
has "${chart}" 'image: "elixircloud/pubgrade:' "default"
has "${chart}" 'image: "mongo:7' "default"
has "${chart}" 'kind: NetworkPolicy$' "default"
has "${chart}" 'automountServiceAccountToken: false' "default"
has "$(render --set mongodb.port=27018)" 'args: \["--port", "27018"\]' "MongoDB port"

# OpenShift: a Route, also for the Ingress off by default
chart="$(render --api-versions route.openshift.io/v1 --set hostName=pubgrade.example.org)"
has "${chart}" 'kind: Route$' "OpenShift"
has "${chart}" 'termination: edge' "OpenShift"
hasnt "${chart}" 'kind: Ingress$' "OpenShift"
hasnt "${chart}" 'runAsUser' "OpenShift"

# An Ingress wins over a Route, on request, and can't go without a host name
chart="$(render --api-versions route.openshift.io/v1 --set hostName=pubgrade.example.org \
  --set pubgrade.ingress.enabled=true)"
has "${chart}" 'kind: Ingress$' "Ingress"
has "${chart}" 'cert-manager.io/cluster-issuer' "Ingress"
hasnt "${chart}" 'kind: Route$' "Ingress"
if render --set pubgrade.ingress.enabled=true > /dev/null 2>&1; then
  echo "::error::Ingress without hostName must fail"
  status=1
fi
if render --api-versions route.openshift.io/v1 > /dev/null 2>&1; then
  echo "::error::Route without hostName must fail"
  status=1
fi

# The configuration from a Secret
chart="$(render --set pubgrade.configSecret=config)"
has "${chart}" 'secretName: config' "config"
has "${chart}" 'mountPath: /app/pubgrade/config.yaml' "config"

# With builds
chart="$(render --set builds.enabled=true --set builds.existingSecret=builds \
  --set builds.pubgradeUrl=https://pubgrade.example.org)"
for pattern in 'kind: Role$' 'kind: RoleBinding$' 'kind: ServiceAccount$' \
  'name: pubgrade-updater' 'claimName: pubgrade-builds' 'GH_ACCESS_TOKEN'; do
  has "${chart}" "${pattern}" "builds"
done
has "${chart}" 'resources: \["pods"\]' "builds"
if render --set builds.enabled=true > /dev/null 2>&1; then
  echo "::error::Builds without their Secret must fail"
  status=1
fi

# Each Deployment has its own selector, so that no Service selects other pods
selectors="$(render --set builds.enabled=true --set builds.existingSecret=builds \
  --set builds.pubgradeUrl=https://pubgrade.example.org \
  | grep -c 'app.kubernetes.io/component: updater')"
if [ "${selectors}" -ne 2 ]; then
  echo "::error::Only the updater's Deployment may select its pods"
  status=1
fi

[ "${status}" -eq 0 ] && echo "Chart checks passed"
exit "${status}"
