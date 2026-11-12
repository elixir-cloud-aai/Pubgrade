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
# The intermediate registry: Docker Hub, with the token from the builds' Secret
has "$(grep -A1 'name: INTERMEDIATE_REGISTRY_HOST' <<< "${chart}")" \
  'value: "docker.io"' "registry default"
has "$(grep -A4 'name: INTERMEDIATE_REGISTRY_TOKEN' <<< "${chart}")" \
  'name: "builds"' "registry default"
hasnt "${chart}" 'INTERMEDIATE_REGISTRY_NAMESPACE' "registry default"
registry="$(render --set builds.enabled=true --set builds.existingSecret=builds \
  --set builds.pubgradeUrl=https://pubgrade.example.org \
  --set builds.registry.host=harbor.example.org \
  --set builds.registry.namespace=pubgrade \
  --set builds.registry.existingSecret=harbor-robot \
  --set builds.registry.key=auth)"
has "$(grep -A1 'name: INTERMEDIATE_REGISTRY_HOST' <<< "${registry}")" \
  'value: "harbor.example.org"' "registry"
has "$(grep -A1 'name: INTERMEDIATE_REGISTRY_NAMESPACE' <<< "${registry}")" \
  'value: "pubgrade"' "registry"
has "$(grep -A4 'name: INTERMEDIATE_REGISTRY_TOKEN' <<< "${registry}")" \
  'name: "harbor-robot"' "registry"
has "$(grep -A4 'name: INTERMEDIATE_REGISTRY_TOKEN' <<< "${registry}")" \
  'key: "auth"' "registry"
# Without registry values, the defaults
unset_registry="$(render --set builds.enabled=true --set builds.existingSecret=builds \
  --set builds.pubgradeUrl=https://pubgrade.example.org --set builds.registry=null)"
has "$(grep -A4 'name: INTERMEDIATE_REGISTRY_TOKEN' <<< "${unset_registry}")" \
  'key: "intermediate_registry_token"' "registry unset"
has "$(grep -A1 'name: INTERMEDIATE_REGISTRY_HOST' <<< "${unset_registry}")" \
  'value: "docker.io"' "registry unset"
if render --set builds.enabled=true > /dev/null 2>&1; then
  echo "::error::Builds without their Secret must fail"
  status=1
fi

# Count the lines of the rendered chart that match a pattern (fixed string)
count() {
  if [ "$(grep -cF -- "$2" <<< "$1")" -ne "$3" ]; then
    echo "::error::$4: expected '$2' $3 times"
    status=1
  fi
}

# Security contexts: by default, the app's and the updater's containers are
# restricted, with the runtime's seccomp profile, and the pods have none
builds=(--set builds.enabled=true --set builds.existingSecret=builds
  --set builds.pubgradeUrl=https://pubgrade.example.org)
for workload in pubgrade updater; do
  chart="$(render "${builds[@]}" --show-only "templates/${workload}/deployment.yaml")"
  for pattern in 'type: RuntimeDefault' 'allowPrivilegeEscalation: false' \
    'runAsNonRoot: true' '- ALL'; do
    count "${chart}" "${pattern}" 1 "security context default (${workload})"
  done
  # The container's only, not the pod's
  count "${chart}" 'securityContext:' 1 "security context default (${workload})"
done
count "$(render --show-only templates/mongodb/deployment.yaml)" 'securityContext' 0 \
  "security context default (mongodb)"
# Without a seccomp profile (e.g., on clusters that set their own), whether
# removed or left empty (its type removed), and the rest of the context stays.
# (An empty map, `{}`, would be merged with the default and keep its type)
for key in seccompProfile seccompProfile.type; do
  chart="$(render "${builds[@]}" \
    --set "pubgrade.securityContext.${key}=null" \
    --set "builds.updater.securityContext.${key}=null")"
  hasnt "${chart}" 'seccompProfile' "${key}=null"
  count "${chart}" 'allowPrivilegeEscalation: false' 2 "${key}=null"
done
# Other values than maps aren't dropped, so that Kubernetes rejects them
has "$(render --set pubgrade.securityContext.seccompProfile=false 2> /dev/null)" \
  'seccompProfile: false' "seccompProfile=false"
# Pod security contexts on request, also for MongoDB
# in each workload's own Deployment, at the pod's level (`spec.template.spec`,
# indented by 6) or the container's (by 10)
contexts=("${builds[@]}" --set pubgrade.podSecurityContext.fsGroup=1001
  --set builds.updater.podSecurityContext.fsGroup=1002
  --set mongodb.podSecurityContext.fsGroup=1003
  --set mongodb.securityContext.allowPrivilegeEscalation=false)
for entry in pubgrade:1001 updater:1002 mongodb:1003; do
  workload="${entry%%:*}"
  chart="$(render "${contexts[@]}" --show-only "templates/${workload}/deployment.yaml")"
  has "$(grep -A1 '^      securityContext:$' <<< "${chart}")" \
    "^        fsGroup: ${entry##*:}$" "pod security context (${workload})"
  count "${chart}" 'fsGroup:' 1 "pod security context (${workload})"
done
has "$(render "${contexts[@]}" --show-only templates/mongodb/deployment.yaml \
  | grep -A1 '^          securityContext:$')" \
  '^            allowPrivilegeEscalation: false$' "MongoDB security context"
# No security context at all, on request
count "$(render "${builds[@]}" --set pubgrade.securityContext=null \
  --set builds.updater.securityContext=null)" 'securityContext' 0 \
  "security context removed"

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
