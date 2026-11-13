"""Tests for the notify action's script (`actions/notify/notify.sh`).

The script runs against a stub of Pubgrade's `POST
/repositories/{id}/builds` on localhost, which answers with queued responses
and records the requests. The CI job `notify` also runs the action itself
against Pubgrade.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[1] / "actions" / "notify" / "notify.sh"
TOKEN = "s3cr3t-t0ken-value"
SHA = "0123456789abcdef0123456789abcdef01234567"

TOOLS = {tool: shutil.which(tool) for tool in ("bash", "curl", "jq")}

pytestmark = pytest.mark.skipif(
    not all(TOOLS.values()), reason="needs bash, curl and jq"
)


@dataclass
class Request:
    """A request received by the stub.

    Attributes:
        path: Path of the request.
        headers: Headers of the request, with lower-case names.
        body: Body of the request, parsed as JSON.
    """

    path: str
    headers: dict[str, str]
    body: Any


@dataclass
class Stub:
    """A stub of Pubgrade's builds endpoint.

    Attributes:
        url: Base URL of the stub.
        responses: Status and body of the next responses, in order; once
            they are used up, the stub answers with 200 and a build ID.
        requests: Requests received so far.
    """

    url: str
    responses: list[tuple[int, Any]] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)


@pytest.fixture
def stub() -> Iterator[Stub]:
    """Start a stub of Pubgrade on a free port of localhost.

    Yields:
        The stub, with its URL.
    """
    state = Stub(url="")

    class Handler(BaseHTTPRequestHandler):
        """Records each request and sends the next queued response."""

        def do_POST(self) -> None:
            """Answer a POST request."""
            length = int(self.headers.get("Content-Length", "0"))
            state.requests.append(
                Request(
                    path=self.path,
                    headers={k.lower(): v for k, v in self.headers.items()},
                    body=json.loads(self.rfile.read(length) or b"null"),
                )
            )
            status, body = (
                state.responses.pop(0) if state.responses else (200, {"id": "b1"})
            )
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            """Keep the test output quiet.

            Args:
                format: Format string of the message.
                *args: Arguments of the format string.
            """

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


@dataclass
class Result:
    """Result of a run of the script.

    Attributes:
        returncode: Exit status.
        output: Standard output and standard error, combined.
        outputs: Step outputs written to `GITHUB_OUTPUT`.
    """

    returncode: int
    output: str
    outputs: dict[str, str]


def run(
    tmp_path: Path,
    stub_url: str,
    inputs: dict[str, str] | None = None,
    context: dict[str, str] | None = None,
) -> Result:
    """Run the script with the action's inputs as environment variables.

    Args:
        tmp_path: Directory for the `GITHUB_OUTPUT` file.
        stub_url: Base URL of the stub, used as input `url` unless given.
        inputs: Inputs of the action to override, by their environment
            variable names without the prefix `INPUT_` (e.g. `TOKEN`); the
            defaults are those of a run for a pushed tag, with HTTP allowed.
        context: Variables of the GitHub context to override (e.g.
            `GITHUB_REF_TYPE`).

    Returns:
        The result of the run.
    """
    output_file = tmp_path / "github_output"
    output_file.touch()
    env = {
        "PATH": os.environ["PATH"],
        "TMPDIR": str(tmp_path),
        "GITHUB_OUTPUT": str(output_file),
        "GITHUB_REF_TYPE": "tag",
        "GITHUB_REF_NAME": "v1.2.0",
        "GITHUB_SHA": SHA,
        "NOTIFY_RETRY_DELAY": "0",
        "INPUT_URL": stub_url,
        "INPUT_REPOSITORY_ID": "repo1",
        "INPUT_TOKEN": TOKEN,
        "INPUT_IMAGE": "elixircloud/tesk-api:v1.2.0",
        "INPUT_BUILD_TYPE": "",
        "INPUT_GIT_TAG": "",
        "INPUT_GIT_BRANCH": "",
        "INPUT_GIT_COMMIT": "",
        "INPUT_FAIL_ON_ERROR": "true",
        "INPUT_ALLOW_HTTP": "true",
    }
    env.update(context or {})
    env.update({f"INPUT_{name}": value for name, value in (inputs or {}).items()})
    process = subprocess.run(  # noqa: S603 (fixed arguments, no shell)
        [str(TOOLS["bash"]), str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    outputs = {
        name: value
        for name, _, value in (
            line.partition("=") for line in output_file.read_text().splitlines()
        )
    }
    return Result(process.returncode, process.stdout + process.stderr, outputs)


def test_success(tmp_path: Path, stub: Stub) -> None:
    """A build is registered with the token in its header and the ID output."""
    result = run(tmp_path, stub.url)
    assert result.returncode == 0, result.output
    assert result.outputs == {"build-id": "b1"}
    [request] = stub.requests
    assert request.path == "/repositories/repo1/builds"
    assert request.headers["x-project-access-token"] == TOKEN
    assert request.headers["content-type"] == "application/json"
    assert request.body == {
        "images": [{"name": "elixircloud/tesk-api:v1.2.0"}],
        "head_commit": {"tag": "v1.2.0"},
    }


def test_token_masked_and_not_printed(tmp_path: Path, stub: Stub) -> None:
    """The token is masked first and appears nowhere else in the output."""
    stub.responses = [(403, {"status": 403, "title": "Forbidden"})]
    result = run(tmp_path, stub.url)
    assert result.output.startswith(f"::add-mask::{TOKEN}\n")
    assert result.output.count(TOKEN) == 1


def test_trailing_slash_and_build_type(tmp_path: Path, stub: Stub) -> None:
    """A trailing slash of the URL is dropped; a build type is sent."""
    result = run(tmp_path, f"{stub.url}/", {"BUILD_TYPE": "production"})
    assert result.returncode == 0, result.output
    [request] = stub.requests
    assert request.path == "/repositories/repo1/builds"
    assert request.body["build_type"] == "production"


def test_identifiers_with_all_characters(tmp_path: Path, stub: Stub) -> None:
    """Identifiers and tokens may have all characters Pubgrade generates."""
    stub.responses = [(200, {"id": "b.1~x-y"})]
    result = run(tmp_path, stub.url, {"REPOSITORY_ID": "r.1-a", "TOKEN": "t.~-1"})
    assert result.returncode == 0, result.output
    assert result.outputs == {"build-id": "b.1~x-y"}
    [request] = stub.requests
    assert request.path == "/repositories/r.1-a/builds"
    assert request.headers["x-project-access-token"] == "t.~-1"


def test_branch_from_context(tmp_path: Path, stub: Stub) -> None:
    """A run for a branch sends the branch and the commit of the run."""
    result = run(
        tmp_path,
        stub.url,
        context={"GITHUB_REF_TYPE": "branch", "GITHUB_REF_NAME": "dev"},
    )
    assert result.returncode == 0, result.output
    [request] = stub.requests
    assert request.body["head_commit"] == {"branch": "dev", "commit_sha": SHA}


@pytest.mark.parametrize(
    ("inputs", "head_commit"),
    [
        ({"GIT_TAG": "v2"}, {"tag": "v2"}),
        ({"GIT_BRANCH": "main"}, {"branch": "main", "commit_sha": SHA}),
        (
            {"GIT_BRANCH": "main", "GIT_COMMIT": "fedcba9"},
            {"branch": "main", "commit_sha": "fedcba9"},
        ),
        (
            {"GIT_TAG": "v2", "GIT_BRANCH": "main"},
            {"tag": "v2"},
        ),
    ],
)
def test_git_inputs(
    tmp_path: Path, stub: Stub, inputs: dict[str, str], head_commit: dict[str, str]
) -> None:
    """The inputs `git-tag`, `git-branch` and `git-commit` set `head_commit`.

    Args:
        tmp_path: Pytest's temporary directory.
        stub: The stub of Pubgrade.
        inputs: Inputs of the action.
        head_commit: Expected `head_commit` of the request.
    """
    result = run(tmp_path, stub.url, inputs)
    assert result.returncode == 0, result.output
    [request] = stub.requests
    assert request.body["head_commit"] == head_commit


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ({"URL": ""}, "Input 'url' is required"),
        ({"REPOSITORY_ID": ""}, "Input 'repository-id' is required"),
        ({"TOKEN": ""}, "Input 'token' is required"),
        ({"IMAGE": ""}, "Input 'image' is required"),
        ({"REPOSITORY_ID": "../x"}, "Invalid input 'repository-id'"),
        ({"REPOSITORY_ID": ".."}, "Invalid input 'repository-id'"),
        ({"TOKEN": 'a" -o "x'}, "Invalid input 'token'"),
        ({"TOKEN": "a\nb"}, "Invalid input 'token'"),
        ({"IMAGE": "org/image"}, "needs a tag"),
        ({"IMAGE": "org/image:1@sha256:" + "a" * 64}, "needs a tag"),
        ({"URL": "ftp://example.org"}, "must start with https:// or http://"),
        ({"ALLOW_HTTP": "false"}, "must start with https:// (or set"),
        ({"GIT_COMMIT": "abc1234"}, "Input 'git-commit' needs 'git-branch'"),
        ({"FAIL_ON_ERROR": "maybe"}, "Invalid input 'fail-on-error'"),
        ({"ALLOW_HTTP": "maybe"}, "Invalid input 'allow-http'"),
    ],
)
def test_invalid_inputs(
    tmp_path: Path, stub: Stub, inputs: dict[str, str], message: str
) -> None:
    """Invalid inputs fail before any request, even without `fail-on-error`.

    Args:
        tmp_path: Pytest's temporary directory.
        stub: The stub of Pubgrade.
        inputs: Inputs of the action.
        message: Expected part of the error message.
    """
    result = run(tmp_path, stub.url, {"FAIL_ON_ERROR": "false", **inputs})
    assert result.returncode == 1
    assert "::error::" in result.output
    assert message in result.output
    assert stub.requests == []
    assert result.outputs == {}


def test_error_response(tmp_path: Path, stub: Stub) -> None:
    """An error response fails the step with Pubgrade's title and detail."""
    stub.responses = [
        (400, {"status": 400, "title": "Bad Request", "detail": "No such build type"})
    ]
    result = run(tmp_path, stub.url)
    assert result.returncode == 1
    assert "::error::Pubgrade answered 400: Bad Request: No such build type" in (
        result.output
    )
    assert len(stub.requests) == 1
    assert result.outputs == {}


def test_error_without_fail_on_error(tmp_path: Path, stub: Stub) -> None:
    """With `fail-on-error: false`, an error response only warns."""
    stub.responses = [(403, {"status": 403, "title": "Forbidden"})]
    result = run(tmp_path, stub.url, {"FAIL_ON_ERROR": "false"})
    assert result.returncode == 0
    assert "::warning::Pubgrade answered 403: Forbidden" in result.output
    assert result.outputs == {}


def test_retry_when_unavailable(tmp_path: Path, stub: Stub) -> None:
    """A 503 is retried; the build ID of the success is output."""
    stub.responses = [(503, {}), (503, {}), (200, {"id": "b2"})]
    result = run(tmp_path, stub.url)
    assert result.returncode == 0, result.output
    assert result.outputs == {"build-id": "b2"}
    assert len(stub.requests) == 3
    assert result.output.count("retrying") == 2


@pytest.mark.parametrize("fail_on_error", ["true", "false"])
def test_retries_exhausted(tmp_path: Path, stub: Stub, fail_on_error: str) -> None:
    """After three 503s, the step fails, or only warns.

    Args:
        tmp_path: Pytest's temporary directory.
        stub: The stub of Pubgrade.
        fail_on_error: Input `fail-on-error`.
    """
    stub.responses = [(503, {}), (503, {}), (503, {})]
    result = run(tmp_path, stub.url, {"FAIL_ON_ERROR": fail_on_error})
    level = "error" if fail_on_error == "true" else "warning"
    assert result.returncode == (1 if fail_on_error == "true" else 0)
    assert f"::{level}::Pubgrade answered 503" in result.output
    assert len(stub.requests) == 3
    assert result.outputs == {}


@pytest.mark.parametrize("status", [500, 502, 504])
def test_no_retry_after_request_may_have_arrived(
    tmp_path: Path, stub: Stub, status: int
) -> None:
    """500, 502 and 504 aren't retried, as Pubgrade may have the build.

    Args:
        tmp_path: Pytest's temporary directory.
        stub: The stub of Pubgrade.
        status: Status of the response.
    """
    stub.responses = [(status, {"status": status, "title": "Error"})]
    result = run(tmp_path, stub.url)
    assert result.returncode == 1
    assert f"::error::Pubgrade answered {status}: Error" in result.output
    assert len(stub.requests) == 1
    assert "retrying" not in result.output


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<html>Bad Gateway</html>", "Pubgrade answered 400\n"),
        ({"title": "Bad Request"}, "Pubgrade answered 400: Bad Request\n"),
        (
            {"title": "Bad\n::stop-commands::x", "detail": "100%"},
            "Pubgrade answered 400: Bad%0A::stop-commands::x: 100%25\n",
        ),
    ],
)
def test_error_details(tmp_path: Path, stub: Stub, body: Any, message: str) -> None:
    """Errors show Pubgrade's title and detail, escaped for the runner.

    Args:
        tmp_path: Pytest's temporary directory.
        stub: The stub of Pubgrade.
        body: Body of the error response; bytes are sent as they are.
        message: Expected error message, with its line end.
    """
    stub.responses = [(400, body)]
    result = run(tmp_path, stub.url)
    assert result.returncode == 1
    assert f"::error::{message}" in result.output


def test_response_without_id(tmp_path: Path, stub: Stub) -> None:
    """A success response without a build ID fails the step."""
    stub.responses = [(200, {"other": "x"})]
    result = run(tmp_path, stub.url)
    assert result.returncode == 1
    assert "::error::Pubgrade's response has no build ID" in result.output


@pytest.mark.parametrize("fail_on_error", ["true", "false"])
def test_unreachable(tmp_path: Path, fail_on_error: str) -> None:
    """A Pubgrade that can't be reached fails the step, or warns, after retries.

    Args:
        tmp_path: Pytest's temporary directory.
        fail_on_error: Input `fail-on-error`.
    """
    result = run(tmp_path, "http://127.0.0.1:9", {"FAIL_ON_ERROR": fail_on_error})
    level = "error" if fail_on_error == "true" else "warning"
    assert result.returncode == (1 if fail_on_error == "true" else 0)
    assert f"::{level}::Could not reach Pubgrade (curl exit status 7)" in (
        result.output
    )
    assert result.output.count("retrying") == 2


def test_other_curl_errors_not_retried(tmp_path: Path, stub: Stub) -> None:
    """Other curl errors (here TLS against plain HTTP) aren't retried."""
    url = stub.url.replace("http://", "https://")
    result = run(tmp_path, url, {"ALLOW_HTTP": "false"})
    assert result.returncode == 1
    assert "::error::Could not reach Pubgrade (curl exit status 35)" in result.output
    assert "retrying" not in result.output
