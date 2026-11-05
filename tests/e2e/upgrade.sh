#!/usr/bin/env bash
# End-to-end test of one orchestrated upgrade: Pubgrade from its chart, two
# namespaces with a Deployment and a sidecar each, one call to publish an image.
# Needs Docker, Helm and jq; removes everything afterwards.
#
# Variables: SIDECAR_IMAGE (a local image, by default built from the branch
# `master` of Pubgrade-Sidecar), and those of `cluster.sh`.
#
# Usage: tests/e2e/upgrade.sh

set -euo pipefail

# shellcheck source=tests/e2e/cluster.sh
source "$(dirname "$0")/cluster.sh"

SIDECAR_REPO="https://github.com/elixir-cloud-aai/Pubgrade-Sidecar.git#master"
# A small image on Docker Hub that stays up, as the sidecar checks that tags
# exist there
IMAGE=rancher/mirrored-pause
OLD_TAG=3.9
NEW_TAG=3.10
SITES=(site-a site-b)

fail() {
  # To stderr, as most callers capture stdout
  {
    echo "::error::$1"
    k get pods --all-namespaces || true
    k logs --namespace pubgrade deployment/pubgrade --tail=30 || true
  } >&2
  exit 1
}

# Create a namespace with the Deployment to upgrade and a sidecar with rights
# on that one only
create_site() {
  local site="$1" token="$2"
  k create namespace "${site}" > /dev/null
  k apply --namespace "${site}" --filename - > /dev/null << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: target
spec:
  selector: {matchLabels: {app: target}}
  template:
    metadata: {labels: {app: target}}
    spec:
      containers:
        - name: target
          image: ${IMAGE}:${OLD_TAG}
---
apiVersion: v1
kind: ServiceAccount
metadata: {name: sidecar}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: sidecar}
rules:
  - apiGroups: [apps]
    resources: [deployments]
    resourceNames: [target]
    verbs: [get, patch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: sidecar}
subjects:
  - {kind: ServiceAccount, name: sidecar}
roleRef:
  {apiGroup: rbac.authorization.k8s.io, kind: Role, name: sidecar}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sidecar
spec:
  selector: {matchLabels: {app: sidecar}}
  template:
    metadata: {labels: {app: sidecar}}
    spec:
      serviceAccountName: sidecar
      containers:
        - name: sidecar
          image: ${SIDECAR_IMAGE}
          imagePullPolicy: Never
          env:
            - {name: NAMESPACE, value: ${site}}
            - {name: ACCESS_TOKEN, value: ${token}}
          ports:
            - {containerPort: 8080}
---
apiVersion: v1
kind: Service
metadata: {name: sidecar}
spec:
  selector: {app: sidecar}
  ports:
    - {port: 8080}
EOF
  k rollout status deployment/target --namespace "${site}" --timeout=180s
  k rollout status deployment/sidecar --namespace "${site}" --timeout=180s
}

# Call the API and check the status; prints the body
call() {
  local expected="$1" output status
  shift
  output="$(api "$@")"
  status="$(tail -n 1 <<< "${output}")"
  if [ "${status}" != "${expected}" ]; then
    fail "$1 $2: status ${status}, expected ${expected}: ${output}"
  fi
  sed '$d' <<< "${output}"
}

image_of() {
  k get deployment target --namespace "$1" \
    --output 'jsonpath={.spec.template.spec.containers[0].image}'
}

# Print a sidecar's report on the Deployment
sidecar_report() {
  k exec --namespace "$1" deployment/sidecar -- python -c '
import sys, urllib.request
request = urllib.request.Request(
    "http://localhost:8080/deployment/target",
    headers={"X-Access-Token": sys.argv[1]},
)
with urllib.request.urlopen(request, timeout=30) as response:
    print(response.read().decode())
' "${tokens[$1]}"
}

# Wait until a sidecar reports a status, or fail
wait_for_report() {
  local site="$1" status="$2" _ report=""
  for _ in $(seq 1 90); do
    report="$(sidecar_report "${site}")"
    if [ "$(jq -r .status <<< "${report}")" = "${status}" ]; then
      return 0
    fi
    sleep 2
  done
  fail "${site}: sidecar didn't report ${status}: ${report}"
}

# Wait until a site runs an image, and print the seconds this took
wait_for_rollout() {
  local site="$1" image="$2" start="${SECONDS}" _
  for _ in $(seq 1 60); do
    if [ "$(image_of "${site}")" = "${image}" ] \
      && k rollout status deployment/target --namespace "${site}" --timeout=5s > /dev/null 2>&1; then
      echo "$((SECONDS - start))"
      return 0
    fi
    sleep 2
  done
  fail "${site} didn't roll out ${image}; it has $(image_of "${site}")"
}

trap cluster_down EXIT

if [ -z "${SIDECAR_IMAGE:-}" ]; then
  SIDECAR_IMAGE=pubgrade-sidecar:e2e
  docker build --quiet --tag "${SIDECAR_IMAGE}" "${SIDECAR_REPO}" > /dev/null
fi

cluster_up
load_image "${SIDECAR_IMAGE}"
install_pubgrade

json='{"Content-Type": "application/json"}'
repository="$(call 200 POST /repositories "${json}" \
  '{"url": "https://github.com/elixir-cloud-aai/tesk-api.git"}')"
repository_id="$(jq -r .id <<< "${repository}")"
project_headers="$(jq -n --arg token "$(jq -r .access_token <<< "${repository}")" \
  '{"Content-Type": "application/json", "X-Project-Access-Token": $token}')"
user="$(call 200 POST /users/register "${json}" '{"name": "e2e"}')"
uid="$(jq -r .uid <<< "${user}")"
call 200 PUT "/users/${uid}/verify" \
  "$(jq -n --arg token "${E2E_ADMIN_TOKEN}" \
    '{"X-Super-User-Id": "e2e", "X-Super-User-Access-Token": $token}')" > /dev/null
user_headers="$(jq -n --arg uid "${uid}" \
  --arg token "$(jq -r .user_access_token <<< "${user}")" \
  '{"Content-Type": "application/json", "X-User-Id": $uid, "X-User-Access-Token": $token}')"

# Subscribe to any tag; `$1` is the callback's host, `$2` the token
subscribe() {
  call 200 POST /subscriptions "${user_headers}" "$(jq -n \
    --arg repository "${repository_id}" \
    --arg url "http://$1:8080/deployment/target" --arg token "$2" \
    '{repository_id: $repository, callback_url: $url, access_token: $token, type: "tag", value: "*"}')" \
    | jq -r .subscription_id
}

declare -A subscriptions tokens
for site in "${SITES[@]}"; do
  tokens[${site}]="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')"
  create_site "${site}" "${tokens[${site}]}"
  subscriptions[${site}]="$(subscribe "sidecar.${site}" "${tokens[${site}]}")"
done
unreachable="$(subscribe "nobody.pubgrade" "token")"

# One call to publish a new tag: both sites upgrade, and the build tells that
# the third one wasn't reached
start="${SECONDS}"
build="$(call 200 POST "/repositories/${repository_id}/builds" "${project_headers}" \
  "{\"images\": [{\"name\": \"${IMAGE}:${NEW_TAG}\"}], \"head_commit\": {\"tag\": \"${NEW_TAG}\"}}")"
build_id="$(jq -r .id <<< "${build}")"
echo "Publishing took $((SECONDS - start)) s"
for site in "${SITES[@]}"; do
  seconds="$(wait_for_rollout "${site}" "${IMAGE}:${NEW_TAG}")"
  echo "${site} rolled out after ${seconds} s more"
  wait_for_report "${site}" complete
done
result="$(call 200 GET "/repositories/${repository_id}/builds/${build_id}")"
jq . <<< "${result}"
for site in "${SITES[@]}"; do
  jq -e --arg id "${subscriptions[${site}]}" \
    '.notifications[] | select(.subscription_id == $id) | .result == "delivered"' \
    <<< "${result}" > /dev/null || fail "${site} wasn't reported as delivered"
done
jq -e --arg id "${unreachable}" \
  '.status == "FAILED" and (.notifications[] | select(.subscription_id == $id) | .result == "failed")' \
  <<< "${result}" > /dev/null || fail "The unreachable subscriber wasn't reported"
if grep -Eq 'nobody|callback_url|access_token' <<< "${result}"; then
  fail "The public build shows URLs or tokens"
fi

# A sidecar accepts a tag that doesn't exist, as an image can take a while to
# arrive, and only reports the failure after its retries: nothing changes
call 200 POST "/repositories/${repository_id}/builds" "${project_headers}" \
  "{\"images\": [{\"name\": \"${IMAGE}:does-not-exist\"}], \"head_commit\": {\"tag\": \"does-not-exist\"}}" > /dev/null
for site in "${SITES[@]}"; do
  wait_for_report "${site}" failed
  [ "$(image_of "${site}")" = "${IMAGE}:${NEW_TAG}" ] \
    || fail "${site} changed to a tag that doesn't exist: $(image_of "${site}")"
done

echo "Upgrade test passed"
