#!/usr/bin/env bash
# Registers a prebuilt image as a build of a repository at Pubgrade (`POST
# /repositories/{id}/builds`), which then notifies the repository's
# subscriptions. Run by the action `actions/notify` (`action.yml`), with its
# inputs in the environment variables `INPUT_*` and the run's context in
# `GITHUB_*`; see "Notify Pubgrade from CI" in `docs/usage.md`.
#
# The token is masked first, never printed and never on a command line (it
# goes to curl through stdin). Invalid inputs always fail; failed requests
# fail unless `fail-on-error` is `false`. Only requests that didn't reach
# Pubgrade are retried: no connection (curl exit status 6 or 7), or a 503,
# which proxies answer when Pubgrade has no ready instance. A 502 or 504 may
# come after Pubgrade registered the build (e.g. while it notifies the
# subscriptions), so it isn't retried, so that a build isn't registered twice.

set -euo pipefail

token="${INPUT_TOKEN:-}"
if [[ -n "${token}" ]]; then
  echo "::add-mask::${token}"
fi

url="${INPUT_URL:-}"
repository_id="${INPUT_REPOSITORY_ID:-}"
image="${INPUT_IMAGE:-}"
build_type="${INPUT_BUILD_TYPE:-}"
git_tag="${INPUT_GIT_TAG:-}"
git_branch="${INPUT_GIT_BRANCH:-}"
git_commit="${INPUT_GIT_COMMIT:-}"
fail_on_error="${INPUT_FAIL_ON_ERROR:-true}"
allow_http="${INPUT_ALLOW_HTTP:-false}"
attempts=3
# Seconds between attempts; the variable is for the tests only
retry_delay="${NOTIFY_RETRY_DELAY:-5}"

# Prints a workflow command (`error` or `warning`) with a message, escaped so
# that it stays one command whatever the message holds
annotate() {
  local message="$2"
  message="${message//'%'/%25}"
  message="${message//$'\r'/%0D}"
  message="${message//$'\n'/%0A}"
  echo "::$1::${message}"
}

fail() {
  annotate error "$1"
  exit 1
}

for name in url repository-id token image; do
  variable="${name//-/_}"
  if [[ -z "${!variable}" ]]; then
    fail "Input '${name}' is required"
  fi
done
for name in fail-on-error allow-http; do
  variable="${name//-/_}"
  if [[ "${!variable}" != "true" && "${!variable}" != "false" ]]; then
    fail "Invalid input '${name}': must be 'true' or 'false'"
  fi
done
# Pubgrade's identifiers and tokens are made of the characters that its
# settings allow (`pubgrade/charsets.py`). The identifier is part of the path,
# so it starts with a letter or digit (no `.` or `..`); the token goes into
# curl's configuration in quotes, so it has no quotes, backslashes or line
# breaks (and isn't printed)
if [[ ! "${repository_id}" =~ ^[A-Za-z0-9][A-Za-z0-9._~-]*$ ]]; then
  fail "Invalid input 'repository-id': letters, digits, '.', '_', '~' and '-' only, starting with a letter or digit"
fi
if [[ ! "${token}" =~ ^[A-Za-z0-9._~-]+$ ]]; then
  fail "Invalid input 'token': letters, digits, '.', '_', '~' and '-' only"
fi
# Pubgrade notifies subscribers of the image's tag, so it needs a tag and
# takes no digest; it checks the full reference itself
if [[ "${image}" == *@* || ! "${image##*/}" =~ :. ]]; then
  fail "Input 'image' needs a tag and no digest, e.g. 'org/image:1.0.0'"
fi
if [[ "${allow_http}" == "true" ]]; then
  protocols="=http,https"
  [[ "${url}" =~ ^https?:// ]] \
    || fail "Input 'url' must start with https:// or http://"
else
  protocols="=https"
  [[ "${url}" =~ ^https:// ]] \
    || fail "Input 'url' must start with https:// (or set 'allow-http')"
fi

# The Git reference the image was built from: the inputs, else the run's tag,
# else its branch and commit. A run for a tag has no branch to go with a
# commit
if [[ -z "${git_tag}${git_branch}" && -n "${git_commit}" \
  && "${GITHUB_REF_TYPE:-}" == "tag" ]]; then
  fail "Input 'git-commit' needs 'git-branch' (or 'git-tag') in a run for a tag"
fi
if [[ -n "${git_tag}" ]]; then
  head_commit="$(jq --null-input --arg tag "${git_tag}" '{tag: $tag}')"
elif [[ -z "${git_branch}${git_commit}" && "${GITHUB_REF_TYPE:-}" == "tag" ]]; then
  head_commit="$(jq --null-input --arg tag "${GITHUB_REF_NAME:-}" '{tag: $tag}')"
else
  head_commit="$(jq --null-input \
    --arg branch "${git_branch:-${GITHUB_REF_NAME:-}}" \
    --arg commit "${git_commit:-${GITHUB_SHA:-}}" \
    '{branch: $branch, commit_sha: $commit}')"
fi
body="$(jq --null-input --compact-output \
  --arg name "${image}" --arg type "${build_type}" \
  --argjson head "${head_commit}" \
  '{images: [{name: $name}], head_commit: $head}
   + if $type == "" then {} else {build_type: $type} end')"

response="$(mktemp)"
trap 'rm -f "${response}"' EXIT

# Reports a failed request as an error, or as a warning without
# `fail-on-error`
give_up() {
  if [[ "${fail_on_error}" == "true" ]]; then
    fail "$1"
  fi
  annotate warning "$1"
  exit 0
}

for attempt in $(seq 1 "${attempts}"); do
  status=0
  code="$(curl --proto "${protocols}" --silent --show-error \
    --connect-timeout 10 --max-time 60 \
    --request POST "${url%/}/repositories/${repository_id}/builds" \
    --header 'Content-Type: application/json' \
    --data "${body}" \
    --output "${response}" --write-out '%{http_code}' \
    --config - <<< "header = \"X-Project-Access-Token: ${token}\"")" || status=$?
  case "${status}:${code}" in
    0:200)
      break
      ;;
    6:* | 7:* | 0:503)
      if [[ "${status}" -eq 0 ]]; then
        reason="Pubgrade answered ${code}"
      else
        reason="Could not reach Pubgrade (curl exit status ${status})"
      fi
      if [[ "${attempt}" -lt "${attempts}" ]]; then
        echo "${reason}; retrying in ${retry_delay} s"
        sleep "${retry_delay}"
        continue
      fi
      give_up "${reason}"
      ;;
    0:*)
      # Pubgrade's errors are problem details (`title`, `detail`)
      detail="$(jq -r '[.title, .detail] | map(select(. != null)) | join(": ")' \
        "${response}" 2> /dev/null | head -c 500 || true)"
      give_up "Pubgrade answered ${code}${detail:+: ${detail}}"
      ;;
    *)
      give_up "Could not reach Pubgrade (curl exit status ${status})"
      ;;
  esac
done

build_id="$(jq -r '.id // empty' "${response}" 2> /dev/null || true)"
if [[ ! "${build_id}" =~ ^[A-Za-z0-9._~-]+$ ]]; then
  give_up "Pubgrade's response has no build ID"
fi
echo "build-id=${build_id}" >> "${GITHUB_OUTPUT}"
echo "Registered build ${build_id} of ${image}"
