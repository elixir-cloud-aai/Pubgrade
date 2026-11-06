#!/usr/bin/env bash
# Checks the API of a running app with an empty database, for CI's smoke test.
# Usage: tests/smoke.sh <base URL>

set -euo pipefail

api="$1"
body="$(mktemp)"
trap 'rm -f "${body}"' EXIT

# Request a path; check the status and that the JSON body matches a jq filter.
# An optional fifth argument is the request's JSON body
check() {
  local method="$1" path="$2" status="$3" filter="$4" data="${5:-}" actual
  local -a args=()
  if [ -n "${data}" ]; then
    args=(--header 'Content-Type: application/json' --data "${data}")
  fi
  actual="$(curl --silent --show-error --output "${body}" \
    --write-out '%{http_code}' --request "${method}" \
    "${args[@]+"${args[@]}"}" "${api}${path}")"
  if [ "${actual}" != "${status}" ] \
    || ! jq -e "${filter}" "${body}" > /dev/null; then
    echo "::error::${method} ${path}: status ${actual}, expected ${status} and ${filter}"
    cat "${body}"
    return 1
  fi
  echo "OK: ${method} ${path} ${status}"
}

check GET /repositories 200 '. == []'
check POST /repositories 200 'has("id") and has("access_token")' \
  '{"url": "https://github.com/elixir-cloud-aai/Pubgrade.git"}'
check GET /repositories 200 'length == 1 and (.[0] | has("access_token") | not)'
check GET /repositories/unknown 404 '.status_code == "404"'

# Publish a prebuilt image, with builds switched off by default
check POST /repositories 200 'has("id")' \
  '{"url": "https://github.com/elixir-cloud-aai/Pubgrade.git"}'
repository="$(jq -r .id "${body}")"
token="$(jq -r .access_token "${body}")"
publish() {
  local status="$1" filter="$2" data="$3" actual
  actual="$(curl --silent --show-error --output "${body}" \
    --write-out '%{http_code}' --request POST \
    --header "X-Project-Access-Token: ${token}" \
    --header 'Content-Type: application/json' --data "${data}" \
    "${api}/repositories/${repository}/builds")"
  if [ "${actual}" != "${status}" ] \
    || ! jq -e "${filter}" "${body}" > /dev/null; then
    echo "::error::POST builds: status ${actual}, expected ${status} and ${filter}"
    cat "${body}"
    return 1
  fi
  echo "OK: POST builds ${status}"
}
publish 200 'has("id")' \
  '{"images": [{"name": "org/image:1"}], "head_commit": {"tag": "1"}}'
build="$(jq -r .id "${body}")"
check GET "/repositories/${repository}/builds/${build}" 200 \
  '.status == "SUCCEEDED" and .notifications == []'
publish 403 '.status_code == "403"' \
  '{"images": [{"name": "org/image:1", "location": "./Dockerfile"}], "head_commit": {"tag": "1"}}'
publish 400 '.status_code == "400"' \
  '{"images": [{"name": "org/image"}], "head_commit": {"tag": "1"}}'
