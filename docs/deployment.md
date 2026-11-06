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
   `kubectl create secret generic pubgrade-config -n pubgrade --from-file=config.yaml`.
   Secrets don't belong in values files.
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
