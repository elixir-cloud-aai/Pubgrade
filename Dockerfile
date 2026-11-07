##### TOOLS #####
## uv, to export the locked requirements (`uv.lock`) for the image build, and
## to install them; mounted into the step that uses it only, so that the image
## doesn't contain it (the FOCA image has no pip). Pinned by digest; Dependabot
## updates the tag and digest together
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

##### BASE IMAGE #####
## Pinned by digest, so that rebuilds use the same base image. FOCA is bumped
## by hand, the base image and `foca` in `pyproject.toml` and `uv.lock`
## together (`.github/dependabot.yml`; `tests/test_image.py` checks that they
## match, and that the Python version is the one `pyproject.toml` requires)
FROM elixircloud/foca:0.21.0-py3.13@sha256:ba79033cab60dd79419c2c44f90000f4fb9aa8d495ea09c2798a7348516bd84f

##### METADATA #####
## OCI annotations; CI's `docker/metadata-action` sets the version, revision
## and creation date
LABEL org.opencontainers.image.title="Pubgrade"
LABEL org.opencontainers.image.description="Publish-subscribe service that notifies deployments of new images"
LABEL org.opencontainers.image.url="https://github.com/elixir-cloud-aai/Pubgrade"
LABEL org.opencontainers.image.source="https://github.com/elixir-cloud-aai/Pubgrade"
LABEL org.opencontainers.image.documentation="https://pubgrade.readthedocs.io/"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.authors="ELIXIR On-Cloud <cloud-service@elixir-europe.org>"
LABEL org.opencontainers.image.vendor="ELIXIR On-Cloud"

USER root

## Git, which GitPython needs to clone repositories for builds (and to be
## imported at all); the FOCA image has none
RUN apt-get update \
  && apt-get install -y --no-install-recommends git \
  && rm -rf /var/lib/apt/lists/*

## Install the locked dependencies into the Python of the base image: the
## runtime dependencies (`project.dependencies` of `pyproject.toml`; `--no-dev`
## leaves out the dependency groups) and all their own dependencies, at the
## exact versions of `uv.lock`, checked against its hashes, as wheels only,
## without resolving anything else (`--no-deps`), and compiled, as the root
## file system of deployments may be read-only. `--frozen` takes the lock as
## is, unchecked against `pyproject.toml` (CI's `uv lock --check` checks it).
## Packages that the base image already has at the locked version, such as
## FOCA, are kept as they are. Then uv checks that the installed packages meet
## each other's requirements, as nothing was resolved
COPY pyproject.toml uv.lock /tmp/src/
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
  export UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never \
  && uv export --frozen --no-dev --no-emit-project \
    --project /tmp/src --output-file /tmp/src/requirements.txt \
  && uv pip install --system --require-hashes --only-binary :all: --no-deps \
    --compile-bytecode -r /tmp/src/requirements.txt \
  && uv pip check --system \
  && rm -rf /tmp/src /tmp/uv-*.lock

## Copy the app, which runs from its source directory, owned by root and
## read-only for the app's user (any user ID in group 0, e.g., on OpenShift)
COPY pubgrade /app/pubgrade
RUN chmod -R a+rX,go-w /app/pubgrade && python -m compileall -q /app/pubgrade

## Clones of repositories for builds (`BASE_DIR`), writable for group 0
RUN mkdir /pubgrade_temp_files && chown 1000:0 /pubgrade_temp_files \
  && chmod g+rwX /pubgrade_temp_files

WORKDIR /app
USER 1000

## Serve with Gunicorn: FOCA's settings for containers (port 8080, one worker
## with threads), with more threads and shutdown time
## (`pubgrade/gunicorn_config.py`); override them via `GUNICORN_CMD_ARGS`.
## Each worker creates the app, and Gunicorn exits if that fails.
## `python -m pubgrade.app` runs Flask's development server instead
CMD ["gunicorn", "--config", "python:pubgrade.gunicorn_config", \
  "pubgrade.app:create_app()"]
