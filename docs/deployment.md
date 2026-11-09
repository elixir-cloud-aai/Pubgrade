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
Docker Hub. The chart of a release (attached to the GitHub release) uses the
images of that release (`X.Y.Z`); the chart in the repository uses `dev`,
which follows the branch `dev`. Pin `X.Y.Z` or `sha-<commit>` to control
upgrades. Until the first release, `latest` is outdated.

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
- `repository.id_charset`, `user.uid_charset` and `access_token.charset`
  (default: lowercase letters, digits, `.` and `-`): the characters of
  generated identifiers and access tokens, drawn with Python's `secrets`
  module. Each takes one of these forms:
    - a list of names of character sets (without quotes) and literal
      characters, optionally in quotes: `[string.ascii_lowercase,
      string.digits, '.', '-']`;
    - a string joining such names and quoted literal characters with `+`, or
      listing them in brackets: `string.ascii_lowercase + string.digits +
      '.' + '-'`;
    - a single name or quoted string: `string.ascii_letters`, `'abcdef'`;
    - any other string, as literal characters: `abcdef`.

    The names are `string.ascii_letters`, `string.ascii_lowercase`,
    `string.ascii_uppercase`, `string.digits` and `string.hexdigits`; anything
    else that looks like a name (e.g., in quotes, misspelt, or without
    `string.`) is an error. Literal characters are ASCII letters, digits,
    `.`, `-` and `~`; for `repository.id_charset`, whose identifiers also
    name the Kubernetes pods of builds, only lowercase letters, digits, `.`
    and `-`. Each setting needs at least two characters. Generated values
    neither start nor end with `.`, `-` or a digit, so each setting needs at
    least one other character. Pubgrade checks these settings
    at start and stops with an error naming the setting if one can't be used.

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
to manage pods in the namespace. Every 5 seconds, the updater reports build
pods that succeeded to Pubgrade, waiting up to 30 seconds to connect and
again for the response; a report that fails is logged and doesn't stop the
others. The volume needs a storage class with `ReadWriteMany`
(`builds.volume.storageClass`). Build pods run as root, so
builds don't work under OpenShift's default restrictions. With builds off,
requests that need them get a 403, as does
`PUT /repositories/{id}/builds/{build_id}`.

Pubgrade clones the repository and checks out the `branch` (and the
`commit_sha`, if given) or the `tag` in `head_commit`. Branches and tags must
be given by their exact names, and `commit_sha` as a commit hash (4 to 64
hexadecimal digits); revision expressions such as `dev~1` aren't accepted.
If one of them is empty, isn't in the repository or (a short hash) isn't
unique, the request gets a 400 that says so (before: a 500). A build that
can't start, for this or another reason (e.g., a Dockerfile that can't be
read, which still gets a 500), is removed again, with its files: only
builds whose identifier the client got are kept. While the repository is
cloned, the build is listed as `QUEUED`. If only creating the build pod
fails (a 500), the build and its files are kept, as the pod may have been
created nonetheless.

Deleting a repository (`DELETE /repositories/{id}`) stops its builds: their
pods are deleted and their files removed, also the files left by finished
builds whose cleanup failed. A build started while the repository is deleted
is stopped and removed again, and its request gets a 404. If a pod or a
build's files can't be removed (the Kubernetes API gets 10 seconds per pod),
the request gets a 500; the repository, its builds and subscriptions stay
(pods and files removed until then stay removed), so the request can be
repeated.

Canceling a running build (`DELETE /repositories/{id}/builds/{build_id}`, see
[Usage](usage.md#cancel-a-build)) stops it the same way: its pod is deleted
and its files are removed, and the build is kept with the status `CANCELED`.
If the pod or the files can't be removed, the request gets a 500, and the
build stays canceled; repeat the request to stop it again (it gets a 409
only once the build is stopped). Deleting the repository stops it too. A build canceled while it starts is stopped
once its pod has been created. When the updater reports a canceled build as
finished, it gets a 409: the build doesn't succeed, its image isn't signed,
no one is notified, and a pod that is left is deleted. Pubgrade records a
build as `SUCCEEDED` before it triggers the signing of its image (back to its
previous status if that fails); a build canceled from then on counts as
finished: the signing goes ahead, and subscriptions aren't notified unless
the notifications have started already. Finished builds are only marked;
their files, if their cleanup failed, are removed when their repository is
deleted.

### Registries

Images can come from any registry that implements the OCI distribution API
(e.g., Docker Hub, Harbor, GitLab, Quay or GHCR). With builds off, Pubgrade
never contacts a registry: it passes the image name of the request,
including its registry host (e.g., `harbor.example.org/project/app`), to
the subscribers, which check for the image themselves (see the sidecar's
[Deployment](sidecar/deployment.md#registries)).

With builds on, build pods push each image to an intermediate registry, set
by the chart values `builds.registry.host` (default `docker.io`) and
`builds.registry.namespace` (e.g., a Harbor project, or a Docker Hub
organization, which Docker Hub needs): the image
`harbor.example.org/project/app:1.0` goes to `<host>/<namespace>/app:build-<build ID>`.
Without the chart, set the environment variables `INTERMEDIATE_REGISTRY_HOST`
and `INTERMEDIATE_REGISTRY_NAMESPACE`. The credentials
are base64 of `<user>:<password>` (e.g., of a Harbor robot account that may
push), by default in the key `intermediate_registry_token` of
`builds.existingSecret`, or in `builds.registry.existingSecret` and
`builds.registry.key`. The setting
`endpoints.builds.intermediate_registery_format` of the app's configuration
(a path with `{}` for the image's name) still works, and takes precedence
over the chart values if it is set; without a tag in it, each build
gets the tag `build-<build ID>`, and with one (e.g., `ttl.sh/{}:1h`), the
image name gets a suffix derived from the build ID, so that each build has
its own image there.

The signing workflow (`endpoints.builds.gh_action_path`) then pulls the
image from the intermediate registry, signs it and pushes it to its final
name. It logs in to Docker Hub only, with the request's `dockerhub_token`:
with builds on, images are still published to Docker Hub, so the names of
the images to build must be Docker Hub names (e.g., `org/app:1.0`, not
`harbor.example.org/project/app:1.0`), and the intermediate registry must
be one that the workflow can pull from.

## Upgrading to API 2.1.0

Version 2.1.0 of the API completes the subscriptions API:

- `POST /subscriptions` needs `type` and `value`; without them, it gets a
  400. Before, such subscriptions were stored, and every build of their
  repository then failed to notify them. Stored subscriptions without
  `type` or `value` now match no build (their notification is skipped):
  delete them and subscribe again.
- `POST /subscriptions` and `POST /repositories/{id}/builds` store only the
  top-level fields that the API defines; others are ignored instead of
  stored (and returned by `GET`). Fields within `images` and `head_commit`
  are stored as given. Subscriptions and builds stored before keep their
  fields, and `GET` still returns them.
- `GET /subscriptions` gives an empty list to a user without subscriptions,
  instead of a 404.
- `DELETE /subscriptions/{subscription_id}` also removes the subscription
  from the lists of its user and its repository, so `GET /subscriptions`
  no longer lists it. Subscriptions deleted before stay listed for their
  user and repository: deleting them again removes them from both lists
  (the request gets a 404, as they are gone).
- Verifying or unverifying a user changes only that flag, so it no longer
  undoes a subscription that the user registers or deletes meanwhile.
- `GET /repositories/{id}/builds/{build_id}` gets a 404 for a build of
  another repository than `{id}`. The spec declares the 404 of the calls
  that can answer it.

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
  them. The settings under `endpoints` stay as they are, but the character
  sets (`repository.id_charset`, `user.uid_charset`, `access_token.charset`)
  take only the forms listed under [Configuration](#configuration): names of
  character sets and literal characters (ASCII letters, digits, `.`, `-`,
  `~`; for `repository.id_charset` only lowercase letters, digits, `.` and
  `-`), at least two of them, no other Python expressions and no other
  characters (e.g., `_`, spaces, `!`, non-ASCII). The image's values are
  unchanged; a value that can't be used stops the app at start, with an
  error naming the setting.
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
- **Repositories:** `PUT /repositories/{id}` changes only the URL (and the
  build types, if given); before, the repository lost its builds and
  subscriptions. `DELETE
  /repositories/{id}` also deletes the repository's builds and subscriptions
  and stops its builds (see [Builds](#builds)); before, they were left
  behind. Unknown repositories get a 404 for both. A configuration of your
  own should add the index on `repository_id` of the collection
  `subscriptions` (see `pubgrade/config.yaml`), which speeds up deletions
  and the limit of subscriptions per repository.
- **Build types** (new, optional): repositories may declare
  `build_types`, builds may name a `build_type`, and subscriptions may ask
  for some `build_types` only (see
  [Usage](usage.md#subscribe-to-a-repository)). Nothing needs to change:
  stored repositories, builds and subscriptions have none, so subscriptions
  get all builds, as before. Responses have these fields where they are
  set (the response of `POST /repositories` stays `id` and `access_token`
  only): clients that reject unknown fields need to accept them.
- **Builds:** `DELETE /repositories/{id}/builds/{build_id}` cancels a build
  (see [Usage](usage.md#cancel-a-build)), and the status of builds has the
  new value `CANCELED`: clients that check `status` against a fixed list
  of values need to accept it. Completion reports of canceled builds get a
  409. The intermediate registry can be set with the chart values
  `builds.registry` (see [Registries](#registries)); before, only with
  `endpoints.builds.intermediate_registery_format`, which still works and
  takes precedence. Images whose name has a registry host or no namespace
  (e.g., `harbor.example.org/project/app`, `app`) are built under their
  last name part, `app`, and the tag `build-<build ID>` (unless
  `intermediate_registery_format` has a tag; then the name gets a suffix
  derived from the build ID), so that builds of images with
  the same name no longer replace each other's image before it is signed;
  before, a registry host broke the build. The
  credentials of a Docker Hub intermediate registry are stored under
  Docker's key for Docker Hub, so that build pods can push there. Let
  running builds finish before the upgrade, and before changing the
  intermediate registry: Pubgrade works out the image to sign again when a
  build completes.
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
