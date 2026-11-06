# Development

Contributions are welcome! See the organisation's [contributing
guide](https://github.com/elixir-cloud-aai/.github/blob/main/CONTRIBUTING.md),
and mind our [code of
conduct](https://github.com/elixir-cloud-aai/.github/blob/main/CODE_OF_CONDUCT.md).

## Tests

`make test` installs the requirements (`requirements.txt`) and the test
dependencies (`setup.py`) into the active Python environment, which should
have Python 3.13, the version of the base image, and runs the unit tests with
coverage (written to `reports/coverage.xml`; 100% coverage is required), e.g.:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
PATH="${PWD}/.venv/bin:${PATH}" make test
```

Some tests clone a public repository, so they need network access.

The app is built on [FOCA](https://foca.readthedocs.io/) 0.21: its
configuration is `pubgrade/config.yaml`, and `pubgrade/app.py` creates the app
(`create_app()`). The image serves it with Gunicorn, with FOCA's settings
(`foca.gunicorn_config`); `python -m pubgrade.app` runs Flask's development
server instead. FOCA is bumped by hand: the tag and digest of the base image in
the `Dockerfile` and `foca` in `requirements.txt` together, following FOCA's
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

## CI

[CI](https://github.com/elixir-cloud-aai/Pubgrade/blob/dev/.github/workflows/ci.yml)
runs on pull requests and pushes to `dev`: the pull request title
(Conventional Commits, at most 50 characters, as it becomes the commit message
of the squash merge), lint (the citation metadata in `CITATION.cff`), the
tests with coverage to Codecov, the chart, the smoke
and upgrade tests, the documentation, and a scan of the images. The scan fails
on critical and high vulnerabilities that have a fix in the app's image; the
updater's image, which isn't built on FOCA, is only reported for now.
The job `CI passed` sums up all other jobs and is the only required check.

Pushes to `dev` publish `elixircloud/pubgrade` and
`elixircloud/pubgrade-updater`, signed with Sigstore and tagged `dev` and
`sha-<commit>`. The tag `latest` stays as it is until there are releases.
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
python -m venv .venv
.venv/bin/pip install -e ".[docs]"
.venv/bin/mkdocs build --strict  # or `mkdocs serve` to preview
```

The build fails on warnings, e.g. of broken links.

## Versioning

The project follows [semantic versioning](https://semver.org/). It has no
releases yet and is in beta, so the API may change without notice; use the
image tags `dev` or `sha-<commit>` (see [CI](#ci)).
