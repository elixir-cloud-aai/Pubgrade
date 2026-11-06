# Deployment

The Helm chart in
[`helm/`](https://github.com/elixir-cloud-aai/Pubgrade/tree/dev/helm) installs
Pubgrade and a MongoDB on Kubernetes or OpenShift, into any namespace, without
special rights. Install one release per namespace, as resource names are
fixed.

## Installation

1. Install [kubectl](https://kubernetes.io/docs/tasks/tools/) and
   [Helm](https://helm.sh/docs/intro/install/).
2. Create a namespace: `kubectl create namespace pubgrade`
3. Copy
   [`pubgrade/config.yaml`](https://github.com/elixir-cloud-aai/Pubgrade/blob/dev/pubgrade/config.yaml),
   add your admin users with new tokens under
   `endpoints.subscriptions.admin_users` (see [Configuration](#configuration)),
   and store it in a Secret:
   `kubectl create secret generic pubgrade-config -n pubgrade --from-file=config.yaml=<your copy>`.
   Secrets don't belong in values files, nor in the checkout, from where they
   would end up in Git or in images you build.
4. Install:
   `helm install pubgrade helm/ -n pubgrade --set pubgrade.configSecret=pubgrade-config --set hostName=<host name>`

The service is exposed by a Route if the cluster serves Routes (OpenShift; TLS
at the router); on other clusters, enable an Ingress with
`--set pubgrade.ingress.enabled=true`, which requests a certificate from
[cert-manager](https://cert-manager.io/) by default. See
[`helm/values.yaml`](https://github.com/elixir-cloud-aai/Pubgrade/blob/dev/helm/values.yaml)
for all values. Pubgrade's pods run as any user ID in group 0, with no fixed
ID, as OpenShift assigns its own.

The images are `elixircloud/pubgrade` and `elixircloud/pubgrade-updater` on
Docker Hub. Until there are releases, use the tag `dev`, which follows the
branch `dev`, or `sha-<commit>` to control upgrades; `latest` is outdated.

## Configuration

Pubgrade reads its configuration from `pubgrade/config.yaml` in the image, or
from the Secret given by `pubgrade.configSecret`. The environment variable
`MONGO_HOST` takes precedence over `db.host`. Settings under `endpoints`:

- `subscriptions.admin_users`: the users that can verify other users, each with
  `name`, `uid` and `user_access_token`. At each start, the database is made to
  match this list: after changing the Secret, restart Pubgrade.
- `repository.registration_enabled`, `user.registration_enabled` and
  `subscriptions.registration_enabled` (default: on): switch these off once
  repositories, users and subscriptions are set up. Further registrations then
  get a 403.
- `subscriptions.notification_timeout` (default: 10): seconds for each call to
  a subscriber, to connect and for the response. Publishing waits for this, so
  with both, keep it below the time limit of the Route or Ingress (e.g., 30
  seconds by default on OpenShift).
- `subscriptions.max_per_repository` (default: 100): the most subscriptions a
  repository takes; each one gets its own thread when publishing.
- `builds.enabled` (default: off): see [Builds](#builds).

Log messages name repositories, users, subscriptions, builds and pods by
their identifiers; they contain no access tokens or other credentials.
Failed calls to the Kubernetes API are logged with status and reason, and
requests to GitHub that fail (e.g., no connection) with the type of the
error; responses of GitHub are not checked.

## Builds

By default, Pubgrade doesn't build images: a repository's CI builds and pushes
the image, and publishes it to Pubgrade (see [Usage](usage.md#publish-an-image)).
To let Pubgrade build images instead, set `endpoints.builds.enabled` in the
configuration and `builds.enabled` in the chart, which must match, with the
other values under `builds`. Publishing then also needs a `location` for the
image and a `dockerhub_token`. This adds an updater, a shared volume and rights
to manage pods in the namespace. The volume needs a storage class with
`ReadWriteMany` (`builds.volume.storageClass`). Build pods run as root, so
builds don't work under OpenShift's default restrictions. With builds off,
requests that need them get a 403, as does
`PUT /repositories/{id}/builds/{build_id}`.

## Upgrading to FOCA 0.21 (API 2.0.0)

From November 2026, the image runs on FOCA 0.21 and Python 3.13 instead of FOCA
0.7 and Python 3.9. The chart and its values stay the same. What changes:

- **Configuration:** a configuration of your own (`pubgrade.configSecret`)
  needs the changes of FOCA's migration guides; compare it with
  `pubgrade/config.yaml`. In short: remove `server.environment` and
  `server.use_reloader`; give `api.specs` as in the image's configuration;
  replace the section `exceptions` with `mapping:
  pubgrade.errors.exceptions.exceptions`; set `server.max_content_length`.
  Unknown or removed settings stop the app at start, with an error naming
  them. The settings under `endpoints` stay as they are.
- **Errors** are problem details (see [API](api.md)), with `title`, `status`
  and `detail` instead of `msg` and `status_code`.
- **Timestamps** are in UTC with time zone, and `finished_at` of an
  unfinished build is `null`. At each start, Pubgrade brings stored
  timestamps into this format (those without time zone count as UTC), as
  responses are checked against the API; so do responses with builds and
  subscriptions that the previous version writes during a rolling update.
  Until it is replaced, the pod of the previous version answers requests
  for unfinished builds started by the new one with a 500 (`finished_at` is
  `null`).
  Other values (not written by Pubgrade) stay as they are, and responses
  with them fail with a 500, as do subscriptions whose `callback_url` is
  not a URI with scheme (e.g., `10.0.0.5:8080/update`): subscribe again
  with a full URL.
- **Server:** the image serves the app with Gunicorn instead of Flask's
  development server, still on port 8080, with one worker and 16 threads
  (`pubgrade/gunicorn_config.py`; change Gunicorn's settings via
  `GUNICORN_CMD_ARGS`, e.g., `--threads 32`). Each thread serves one request
  at a time: a publish holds one until its subscribers answer (up to twice
  `notification_timeout`, plus 5 seconds), and a slow client holds one while
  it sends its request. Raise `--threads` for many concurrent publishes, and
  serve Pubgrade behind a proxy that buffers request bodies (as ingress-nginx
  does by default). On shutdown, Gunicorn lets running requests finish for
  up to 28 seconds, within Kubernetes' default grace period of 30 seconds;
  with a `notification_timeout` above 10, a publish may be cut off then. Request bodies larger
  than 1 MiB are rejected.
- **Image:** it runs as user 1000 (group 0), and its app files are read-only;
  any user ID works, e.g., on OpenShift.
- **MongoDB:** FOCA 0.21 needs MongoDB 4.4 or later; the chart's MongoDB is
  newer.

## Moving from chart 0.1

Chart 0.2 can't upgrade a 0.1 release, as its selectors and names changed:

- Remove the old release and install anew. MongoDB's volume has a new name and
  a newer major version, so its data doesn't carry over: register repositories
  and subscriptions again.
- Values were renamed: `pubgrade_webserver` to `pubgrade`, `pubgrade_mongodb`
  to `mongodb`, `pubgrade_build_complete_updater` to `builds.updater`,
  `pubgrade_url` to `builds.pubgradeUrl`, and the Ingress's `url` to
  `hostName`.
- The configuration in the image has no admin users any more, and no debug
  mode: bring your own, with new tokens, in a Secret (step 3 of
  [Installation](#installation)).
- The Secret `pubgrade-secret` is gone: with builds on, create your own
  (`builds.existingSecret`).

## Subscribers

Deploy [Pubgrade-Sidecar](sidecar/index.md) next to each Deployment that
should follow new images, and subscribe its callback URL (see
[Usage](usage.md#subscribe-to-a-repository)).
