#!/usr/bin/env bash
# End-to-end check of a deployed Pubgrade, for operators after an install or
# upgrade: sets up a test Deployment with a Pubgrade-Sidecar in a namespace of
# the current kubectl context, registers a repository, a user and a
# subscription, publishes a prebuilt image and checks that the sidecar rolls
# it out. Removes everything it created afterwards, also on failure. Needs
# curl, jq and kubectl; exits non-zero on failure.
#
# Credentials come from the environment only, never from the command line;
# none of them is passed to another program's arguments either.
#
# Required:
#   PUBGRADE_URL           Base URL of Pubgrade, e.g. https://pubgrade.example.org
#   PUBGRADE_ADMIN_ID      `uid` of an admin user (verifies the test user)
#   PUBGRADE_ADMIN_TOKEN   `user_access_token` of that admin user
#
# Optional:
#   CHECK_NAMESPACE        An existing namespace for the test Deployment and
#                          sidecar, which is kept (default: a new one per run,
#                          created and deleted)
#   CHECK_NAME             Prefix of the objects' names, e.g. to route to the
#                          Service `<prefix>-sidecar` (default: one per run)
#   CHECK_CALLBACK_URL     The URL Pubgrade notifies; by default the sidecar's
#                          Service, which works if Pubgrade runs in the same
#                          cluster and may reach the namespace
#   CHECK_SIDECAR_IMAGE    default: elixircloud/pubgrade-sidecar:0.2.0
#   CHECK_IMAGE            Image repository on Docker Hub that the test
#                          Deployment runs (default: rancher/mirrored-pause),
#   CHECK_OLD_TAG          from this tag (default: 3.9)
#   CHECK_NEW_TAG          to this one (default: 3.10); both must exist
#   CHECK_REPOSITORY_URL   URL of the test repository, only stored; by default
#                          one that can't be cloned, so that a Pubgrade with
#                          builds on refuses the build
#   CHECK_TIMEOUT          Seconds to wait for each rollout (default: 300)
#   KUBECTL                kubectl or a compatible command, e.g. oc
#
# Usage: tests/e2e/check.sh

set -euo pipefail

: "${PUBGRADE_URL:?Set PUBGRADE_URL to the base URL of Pubgrade}"
: "${PUBGRADE_ADMIN_ID:?Set PUBGRADE_ADMIN_ID to the uid of an admin user}"
: "${PUBGRADE_ADMIN_TOKEN:?Set PUBGRADE_ADMIN_TOKEN to the token of that admin user}"

KUBECTL="${KUBECTL:-kubectl}"
for tool in curl jq "${KUBECTL}"; do
  command -v "${tool}" > /dev/null || {
    echo "ERROR: ${tool} not found" >&2
    exit 1
  }
done

api_url="${PUBGRADE_URL%/}"
run_id="$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
name="${CHECK_NAME:-pubgrade-check-${run_id}}"
namespace="${CHECK_NAMESPACE:-pubgrade-check-${run_id}}"
target="${name}-target"
sidecar="${name}-sidecar"
callback_url="${CHECK_CALLBACK_URL:-http://${sidecar}.${namespace}.svc:8080/deployment}"
sidecar_image="${CHECK_SIDECAR_IMAGE:-elixircloud/pubgrade-sidecar:0.2.0}"
image="${CHECK_IMAGE:-rancher/mirrored-pause}"
old_tag="${CHECK_OLD_TAG:-3.9}"
new_tag="${CHECK_NEW_TAG:-3.10}"
repository_url="${CHECK_REPOSITORY_URL:-https://example.org/pubgrade-check.git}"
timeout="${CHECK_TIMEOUT:-300}"
# The sidecar's token, for the subscription
sidecar_token="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')"

# Private files for headers, bodies and responses, which hold tokens
work="$(umask 077 && mktemp -d)"
created_namespace=""
created_objects=""
repository_id=""
uid=""
subscription_id=""

kube() {
  "${KUBECTL}" --namespace "${namespace}" "$@"
}

log() {
  echo "$*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# Call Pubgrade: `api <method> <path> <expected status> <headers file or "">
# [body file]`. Headers and body come from files, so that no token is in an
# argument list. Prints the response body; fails on another status
api() {
  local method="$1" path="$2" expected="$3" headers="$4" body="${5:-}" status
  local -a args=(--silent --show-error --request "${method}"
    --output "${work}/response" --write-out '%{http_code}')
  if [ -n "${headers}" ]; then
    args+=(--header "@${headers}")
  fi
  if [ -n "${body}" ]; then
    args+=(--header 'Content-Type: application/json' --data-binary "@${body}")
  fi
  if ! status="$(curl "${args[@]}" "${api_url}${path}")"; then
    echo "ERROR: ${method} ${path}: no response from ${api_url}" >&2
    return 1
  fi
  if [ "${status}" != "${expected}" ]; then
    echo "ERROR: ${method} ${path}: status ${status}, expected ${expected}:" >&2
    # Error bodies hold no tokens
    head -c 2000 "${work}/response" >&2
    echo >&2
    return 1
  fi
  cat "${work}/response"
}

# Remove what the check created, newest first; report anything left behind
cleanup() {
  local status=$? left=()
  trap - EXIT
  log "Cleaning up"
  if [ -n "${subscription_id}" ] \
    && ! api DELETE "/subscriptions/${subscription_id}" 200 "${work}/user.headers" > /dev/null; then
    left+=("subscription ${subscription_id}")
  fi
  if [ -n "${uid}" ] \
    && ! api DELETE /users/register 200 "${work}/user.headers" > /dev/null; then
    left+=("user ${uid}")
  fi
  if [ -n "${repository_id}" ]; then
    if ! api DELETE "/repositories/${repository_id}" 200 "${work}/repository.headers" > /dev/null \
      || ! api GET "/repositories/${repository_id}" 404 "" > /dev/null 2>&1; then
      left+=("repository ${repository_id}")
    fi
  fi
  if [ -n "${created_namespace}" ]; then
    if ! "${KUBECTL}" delete namespace "${namespace}" --wait=true \
      --timeout="${timeout}s" > /dev/null; then
      left+=("namespace ${namespace}")
    fi
  elif [ -n "${created_objects}" ]; then
    if ! kube delete deployment,service,serviceaccount,role,rolebinding,secret \
      --selector "pubgrade-check=${run_id}" --wait=true \
      --timeout="${timeout}s" > /dev/null; then
      left+=("objects with the label pubgrade-check=${run_id} in ${namespace}")
    fi
  fi
  rm -rf "${work}"
  if [ "${#left[@]}" -gt 0 ]; then
    echo "ERROR: left behind, remove by hand: ${left[*]}" >&2
    status=1
  fi
  if [ "${status}" -eq 0 ]; then
    log "Check passed"
  else
    echo "Check FAILED" >&2
  fi
  exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

image_of() {
  kube get deployment "${target}" \
    --output 'jsonpath={.spec.template.spec.containers[0].image}'
}

log "Checking ${api_url} (run ${run_id})"
api GET /repositories 200 "" > /dev/null
log "OK: Pubgrade answers"

# The test Deployment and a sidecar with rights on it only. Applied from
# stdin, so that the token is in no argument list
if [ -z "${CHECK_NAMESPACE:-}" ]; then
  "${KUBECTL}" create namespace "${namespace}" > /dev/null
  created_namespace=1
fi
created_objects=1
kube apply --filename - > /dev/null << EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${sidecar}
  labels: {pubgrade-check: "${run_id}"}
stringData:
  token: "${sidecar_token}"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${target}
  labels: {pubgrade-check: "${run_id}"}
spec:
  replicas: 1
  selector: {matchLabels: {app: ${target}}}
  template:
    metadata: {labels: {app: ${target}}}
    spec:
      automountServiceAccountToken: false
      securityContext: {runAsNonRoot: true}
      containers:
        - name: target
          image: ${image}:${old_tag}
          securityContext:
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          resources:
            requests: {cpu: 10m, memory: 16Mi}
            limits: {cpu: 50m, memory: 32Mi}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${sidecar}
  labels: {pubgrade-check: "${run_id}"}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ${sidecar}
  labels: {pubgrade-check: "${run_id}"}
rules:
  - apiGroups: [apps]
    resources: [deployments]
    resourceNames: [${target}]
    verbs: [get, patch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ${sidecar}
  labels: {pubgrade-check: "${run_id}"}
subjects:
  - {kind: ServiceAccount, name: ${sidecar}}
roleRef:
  {apiGroup: rbac.authorization.k8s.io, kind: Role, name: ${sidecar}}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${sidecar}
  labels: {pubgrade-check: "${run_id}"}
spec:
  replicas: 1
  selector: {matchLabels: {app: ${sidecar}}}
  template:
    metadata: {labels: {app: ${sidecar}}}
    spec:
      serviceAccountName: ${sidecar}
      securityContext: {runAsNonRoot: true}
      containers:
        - name: sidecar
          image: ${sidecar_image}
          imagePullPolicy: IfNotPresent
          securityContext:
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          env:
            - {name: NAMESPACE, value: "${namespace}"}
            - {name: TARGET_DEPLOYMENTS, value: "${target}"}
            - name: ACCESS_TOKEN
              valueFrom: {secretKeyRef: {name: ${sidecar}, key: token}}
          ports:
            - {name: http, containerPort: 8080}
          readinessProbe:
            tcpSocket: {port: http}
            periodSeconds: 2
          resources:
            requests: {cpu: 50m, memory: 128Mi}
            limits: {cpu: 500m, memory: 256Mi}
---
apiVersion: v1
kind: Service
metadata:
  name: ${sidecar}
  labels: {pubgrade-check: "${run_id}"}
spec:
  selector: {app: ${sidecar}}
  ports:
    - {name: http, port: 8080, targetPort: http}
EOF
kube rollout status deployment "${target}" --timeout="${timeout}s" > /dev/null \
  || fail "The test Deployment didn't start in ${namespace}"
kube rollout status deployment "${sidecar}" --timeout="${timeout}s" > /dev/null \
  || fail "The sidecar didn't start in ${namespace}"
# Pubgrade notifies only once, so the Service must route to the sidecar first
for _ in $(seq 1 30); do
  if [ -n "$(kube get endpointslices --selector "kubernetes.io/service-name=${sidecar}" \
    --output 'jsonpath={.items[*].endpoints[?(@.conditions.ready==true)].addresses[*]}' 2> /dev/null)" ]; then
    break
  fi
  sleep 2
done
log "OK: test Deployment ${target} runs ${image}:${old_tag}, with a sidecar, in ${namespace}"

jq -n --arg url "${repository_url}" '{url: $url}' > "${work}/repository.json"
api POST /repositories 200 "" "${work}/repository.json" > "${work}/repository"
repository_id="$(jq -r .id "${work}/repository")"
printf 'X-Project-Access-Token: %s\n' "$(jq -r .access_token "${work}/repository")" \
  > "${work}/repository.headers"
log "OK: registered repository ${repository_id}"

jq -n --arg name "${name}" '{name: $name}' > "${work}/user.json"
api POST /users/register 200 "" "${work}/user.json" > "${work}/user"
uid="$(jq -r .uid "${work}/user")"
printf 'X-User-Id: %s\nX-User-Access-Token: %s\n' "${uid}" \
  "$(jq -r .user_access_token "${work}/user")" > "${work}/user.headers"
printf 'X-Super-User-Id: %s\nX-Super-User-Access-Token: %s\n' \
  "${PUBGRADE_ADMIN_ID}" "${PUBGRADE_ADMIN_TOKEN}" > "${work}/admin.headers"
api PUT "/users/${uid}/verify" 200 "${work}/admin.headers" > /dev/null
log "OK: registered and verified user ${uid}"

# The token goes to jq through its environment, not its arguments
CHECK_SIDECAR_TOKEN="${sidecar_token}" jq -n --arg repository "${repository_id}" \
  --arg url "${callback_url}" --arg tag "${new_tag}" \
  '{repository_id: $repository, callback_url: $url,
    access_token: env.CHECK_SIDECAR_TOKEN, type: "tag", value: $tag}' \
  > "${work}/subscription.json"
api POST /subscriptions 200 "${work}/user.headers" "${work}/subscription.json" \
  > "${work}/subscription"
subscription_id="$(jq -r .subscription_id "${work}/subscription")"
log "OK: subscribed ${callback_url} to tag ${new_tag}"

# Pubgrade notifies the subscriptions before it answers
jq -n --arg image "${image}:${new_tag}" --arg tag "${new_tag}" \
  '{images: [{name: $image}], head_commit: {tag: $tag}}' > "${work}/build.json"
build_id="$(api POST "/repositories/${repository_id}/builds" 200 \
  "${work}/repository.headers" "${work}/build.json" | jq -r .id)"
api GET "/repositories/${repository_id}/builds/${build_id}" 200 "" > "${work}/build"
result="$(jq -r --arg id "${subscription_id}" \
  '[.notifications[]? | select(.subscription_id == $id) | .result][0] // "none"' \
  "${work}/build")"
if [ "${result}" != delivered ]; then
  fail "Pubgrade's notification of ${callback_url}: ${result}, expected delivered" \
    "(build status $(jq -r .status "${work}/build")). Can Pubgrade reach the" \
    "callback URL, e.g. past NetworkPolicies, and are builds off?"
fi
log "OK: published ${image}:${new_tag} as build ${build_id}; the sidecar accepted it"

start="${SECONDS}"
until [ "$(image_of)" = "${image}:${new_tag}" ]; do
  if [ $((SECONDS - start)) -ge "${timeout}" ]; then
    fail "${target} still runs $(image_of) after ${timeout} s; sidecar log:" \
      "$(kube logs "deployment/${sidecar}" --tail=20 2>&1 || true)"
  fi
  sleep 2
done
kube rollout status deployment "${target}" --timeout="${timeout}s" > /dev/null \
  || fail "${target} didn't finish rolling out ${image}:${new_tag}"
log "OK: ${target} rolled out ${image}:${new_tag} after $((SECONDS - start)) s"
