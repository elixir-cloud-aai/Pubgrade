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
