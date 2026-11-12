# Development

Contributions are welcome! See the organisation's [contributing
guide](https://github.com/elixir-cloud-aai/.github/blob/main/CONTRIBUTING.md),
and mind our [code of
conduct](https://github.com/elixir-cloud-aai/.github/blob/main/CODE_OF_CONDUCT.md).

## Tests

Dependencies are managed with [uv](https://docs.astral.sh/uv/): `pyproject.toml`
lists them (the runtime dependencies, and the dependency groups `dev` for
tests, linters and type checks, and `docs` for the documentation), and
`uv.lock` pins them; the image installs the locked runtime dependencies. After
changing dependencies, run `uv lock` (CI checks that the lock matches). The
app runs from its source directory, not as an installed package.

`make test` installs the locked dependencies into `.venv` (`uv sync`, with
Python 3.13, the version of the base image) and runs the tests with
coverage (written to `coverage.xml`; 100% coverage is required). Without
make:

```bash
uv sync
uv run pytest --cov
```

The tests need no network access and no database. Unit tests mock the
database ([mongomock](https://github.com/mongomock/mongomock)) and clone
a local repository instead of one on GitHub (Git rewrites the URL, see
`tests/conftest.py`). The integration tests in `tests/integration/` run
the app as deployed, with response validation, and test registering,
publishing and notifying through its API, with a local subscriber. They
use mongomock too, unless `MONGODB_TEST_URI` is set: then they use the
MongoDB at that URI, which must not have a database `pubgradeStore` (the
tests drop it before each test). CI runs all tests with mongomock, and the
integration tests also against MongoDB 7.0; to do the latter locally:

```bash
docker run -d --rm --name pubgrade-test-mongo -p 127.0.0.1:27017:27017 mongo:7.0
MONGODB_TEST_URI=mongodb://localhost:27017 uv run pytest tests/integration
docker stop pubgrade-test-mongo
```

The app is built on [FOCA](https://foca.readthedocs.io/) 0.22: its
configuration is `pubgrade/config.yaml`, and `pubgrade/app.py` creates the app
(`create_app()`). The image serves it with Gunicorn, with FOCA's settings
and more threads and shutdown time (`pubgrade/gunicorn_config.py`);
`python -m pubgrade.app` runs Flask's development server instead. FOCA is
bumped by hand: the tag and digest of the base image in the `Dockerfile`
and `foca` in `pyproject.toml` and `uv.lock` together, following FOCA's
migration guides; `tests/test_image.py` fails if they don't match.

`tests/smoke.sh <base URL>` checks the API of a running Pubgrade with an empty
database, and `tests/chart.sh` the rendered chart.

`tests/e2e/upgrade.sh` tests the whole path, and needs Docker, Helm and jq: it
starts a throwaway k3s cluster, installs Pubgrade from its chart, sets up two
namespaces with a Deployment and a sidecar each, publishes one image and checks
that both roll out. It also covers an unreachable subscriber and a tag that
doesn't exist, which takes a few minutes, as sidecars retry first. Sidecars are
built from the branch `dev` of
[Pubgrade-Sidecar](https://github.com/elixir-cloud-aai/Pubgrade-Sidecar); set
`SIDECAR_IMAGE` to use a local image instead.

`tests/e2e/check-local.sh` runs the operators' check `tests/e2e/check.sh`
(see [Deployment](deployment.md#checking-a-deployment)) against such a
cluster from outside, with its kubeconfig and Pubgrade's URL, as against a
deployment. It needs kubectl and curl too, and takes `SIDECAR_IMAGE` as well.

## Lint

Code style, type hints and the absence of secrets are checked with
[pre-commit](https://pre-commit.com/) (`.pre-commit-config.yaml`):

- [Ruff](https://docs.astral.sh/ruff/) lints and formats the Python code
  (Black style; rules in `[tool.ruff]` of `pyproject.toml`), including
  Google-style docstrings for all modules, classes and functions.
- [mypy](https://mypy.readthedocs.io/) checks the type hints, which must be
  complete (`[tool.mypy]`).
- [gitleaks](https://github.com/gitleaks/gitleaks) looks for secrets in the
  staged changes; CI also scans all files.
- [actionlint](https://github.com/rhysd/actionlint) checks the GitHub
  workflows, and further hooks the YAML syntax, whitespace and file endings.

`make lint` runs all hooks on all files, including the scan of all files
for secrets, as CI does. To run them on each commit, install them once:

```bash
uv sync --all-groups  # mypy also checks the hook of the docs build
uv run pre-commit install
uv run pre-commit run --all-files  # without make
```

The Sidecar's submodule in `external/` is left out. Formatting changes that
touch many lines go in a commit of their own, listed in
`.git-blame-ignore-revs`, so that `git blame` skips them; for GitHub's blame
view this works as is, locally after
`git config blame.ignoreRevsFile .git-blame-ignore-revs`.

## CI

[CI](https://github.com/elixir-cloud-aai/Pubgrade/blob/dev/.github/workflows/ci.yml)
runs on pull requests and pushes to `dev`: the pull request title (Conventional
Commits, at most 50 characters, as it becomes the commit message of the squash
merge), lint (the pre-commit hooks, see [Lint](#lint), and the citation
metadata in `CITATION.cff`), the tests (with mongomock, with coverage to
Codecov; the integration tests also against MongoDB 7.0), the chart, the smoke
and upgrade tests, the deployment check, the documentation, and a scan of the images. The scan fails
on critical and high vulnerabilities that have a fix in the app's image; the
updater's image, which isn't built on FOCA, is only reported for now. The job
`CI passed` sums up all other jobs and is the only required check.

Pushes to `dev` publish `elixircloud/pubgrade` and
`elixircloud/pubgrade-updater`, signed with Sigstore and tagged `dev` and
`sha-<commit>`; releases tag `X.Y.Z` and `latest` (see
[Versioning and releases](#versioning-and-releases)).
Publishing runs in the environment `dev-images` (branch `dev` only), with the
Docker Hub secrets `DOCKERHUB_LOGIN` and `DOCKERHUB_TOKEN`; the variable
`DOCKERHUB_ORG` sets the Docker Hub organization (by default `elixircloud`),
and the secret `CODECOV_TOKEN` is for the coverage report. Verify an image's
signature with [cosign](https://docs.sigstore.dev/cosign/):

```bash
cosign verify elixircloud/pubgrade:dev \
  --certificate-identity-regexp '^https://github\.com/elixir-cloud-aai/Pubgrade/\.github/workflows/ci\.yml@refs/heads/dev$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Documentation

The documentation is built with [MkDocs](https://www.mkdocs.org/) and
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) from
`docs/` and `mkdocs.yml`, and published on [Read the
Docs](https://pubgrade.readthedocs.io/) (`.readthedocs.yaml`). The README's
synopsis and quick start are included in the home page, between
`--8<-- [start:<name>]` and `--8<-- [end:<name>]` markers in `README.md`.

The section Pubgrade-Sidecar is the documentation of
[Pubgrade-Sidecar](https://github.com/elixir-cloud-aai/Pubgrade-Sidecar), which
keeps it in its own repository (`docs/`, built strictly in its own CI). It is
included from the Git submodule `external/pubgrade-sidecar`, pinned to a commit
of the Sidecar's branch `dev`, by the hook `docs/hooks.py`: it adds the
Sidecar's pages under `sidecar/`, in the order of the Sidecar's `mkdocs.yml`.
Dependabot proposes updates of the submodule monthly; to update it by hand:

```bash
git submodule update --remote external/pubgrade-sidecar
```

To build the documentation as CI and Read the Docs do, with the submodule
checked out:

```bash
git submodule update --init
uv run --only-group docs mkdocs build --strict  # or `mkdocs serve` to preview
```

The build fails on warnings, e.g. of broken links.

## Versioning and releases

The project follows [semantic versioning](https://semver.org/). It is in
beta, so the API may change without notice. The app, its two images and its
chart are released together, with one version: the tag `vX.Y.Z` (or
`vX.Y.ZaN`, `vX.Y.ZbN` and `vX.Y.ZrcN` for pre-releases), `version` in
`[project]` of `pyproject.toml`, the chart's `appVersion` and `version`
(the SemVer form, e.g., `1.2.3-rc1` for `1.2.3rc1`), and the version in
`CITATION.cff`.
Until 1.0.0, all releases are GitHub pre-releases.

The first release, 0.2.0, took the chart's earlier `version` (0.2.0, from
before the release workflow) for the app, which was 0.1.0 before.

1. Release-prep pull request to `dev`: set the version in `pyproject.toml`
   (then run `uv lock`), `helm/Chart.yaml` (`version` and `appVersion`)
   and `CITATION.cff` (`python scripts/citation.py set <version>`, which
   also sets the release date).
2. Once CI has passed for its commit on `dev`, bring that commit to `main`.
3. Tag it on `main` with a signed, annotated tag and push the tag:
   `git tag -s v<version> -m v<version>`, then
   `git push origin v<version>`.

The [release workflow](https://github.com/elixir-cloud-aai/Pubgrade/blob/dev/.github/workflows/release.yml)
checks the tag (a release version, annotated, with a signature that GitHub
verified, on `main`), that the versions above match it
(`scripts/check_versions.py` and `scripts/citation.py check`) and that CI
passed for a push of the commit. It packages the chart, with the images of
the release as defaults (`elixircloud/pubgrade:X.Y.Z` and
`elixircloud/pubgrade-updater:X.Y.Z`), pushes both images by digest, scans
them, then attests and signs the images and the chart, tags the images
`X.Y.Z` (and `latest` if it is the highest stable release;
`scripts/release_version.py`) and creates the GitHub release, with the chart
and its Sigstore bundle attached. Pushing the images and publishing the
release each need approval in the environment `release`, which holds the
Docker Hub secrets `DOCKERHUB_LOGIN` and `DOCKERHUB_TOKEN`. Verify a released
image's signature with:

```bash
cosign verify elixircloud/pubgrade:<version> \
  --certificate-identity-regexp '^https://github\.com/elixir-cloud-aai/Pubgrade/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The release gets GitHub's generated notes; for a first release (no published
release before it), `scripts/release_notes.py` builds them instead, because
without a previous tag GitHub starts at an older tag of its own choice. Edit
the notes by hand into the agreed format after publishing: the notes of
immutable releases stay editable, their assets don't. So the release is
created as a draft, gets its assets and is published last
(`scripts/release_assets.py`); a re-run of failed jobs finishes it. Don't
re-run all jobs of a release that was published: that builds new image
digests and moves the release's image tags to them before it fails at the
release.

The images are scanned for known vulnerabilities with Trivy: in CI, in the
release workflow before the images are signed and tagged, and weekly for
`latest`
([`scan.yml`](https://github.com/elixir-cloud-aai/Pubgrade/blob/dev/.github/workflows/scan.yml)).
The scans of the app's image in CI and of releases fail on critical and high
vulnerabilities that have a fix; accept a finding only with a reason and an
expiry date, in `.trivyignore.yaml`. The updater's image, which isn't built
on FOCA, is reported only. Since 0.2.0, `latest` is the image of the highest
stable release; its weekly scan fails on the same findings as the other
scans of the app's image.

The scripts in `scripts/` use only the standard library and are tested in
`tests/scripts/`, with the app's coverage.
