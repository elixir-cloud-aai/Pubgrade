# Usage

Pubgrade connects repositories, whose CI publishes new images, with
subscribers, e.g. [Pubgrade-Sidecar](sidecar/index.md) next to a deployment,
which Pubgrade notifies of them. The examples use `<base URL>` for the
address of Pubgrade, e.g. `https://pubgrade.example.org`.

## Register a repository

```bash
curl --request POST '<base URL>/repositories' \
  --header 'Content-Type: application/json' \
  --data '{"url": "<repository URL>"}'
```

The response holds the repository's `id` and its `access_token`: the
repository's CI needs both to publish images. Keep the token secret.

A repository may declare build types, e.g., to tell releases from test
builds, with `"build_types": ["production", "testing"]` next to `url`. Each
build type is a name of letters, digits, `.`, `_` and `-` (up to 64
characters, starting with a letter or digit); a repository declares at most
50. Its builds may then name one of them (see
[Publish an image](#publish-an-image)), and subscriptions may ask for some
of them only (see [Subscribe to a repository](#subscribe-to-a-repository)).
Without build types, builds have no type, as before.

## Register a user

Subscriptions belong to users, who must be verified by an admin. Admin users
are set up in the [configuration](deployment.md#configuration).

```bash
curl --request POST '<base URL>/users/register' \
  --header 'Content-Type: application/json' \
  --data '{"name": "<name>"}'
```

An admin verifies the user:

```bash
curl --request PUT '<base URL>/users/<user ID>/verify' \
  --header 'X-Super-User-Id: <admin user ID>' \
  --header 'X-Super-User-Access-Token: <admin access token>'
```

## Subscribe to a repository

A verified user subscribes a callback URL, e.g. of a Pubgrade-Sidecar, to a
tag or branch of a repository:

```bash
curl --request POST '<base URL>/subscriptions' \
  --header 'X-User-Id: <user ID>' \
  --header 'X-User-Access-Token: <user access token>' \
  --header 'Content-Type: application/json' \
  --data '{
    "repository_id": "<repository ID>",
    "callback_url": "<callback URL>",
    "access_token": "<subscriber access token>",
    "type": "<tag or branch>",
    "value": "<tag or branch name>"
  }'
```

Pubgrade sends `access_token` to `callback_url` with each notification, so use
`https` for anything outside the cluster. A subscription's `value` must equal
the `tag` or `branch` of a published image; the value `*` matches any of them,
e.g. every new tag. A repository takes at most 100 subscriptions by default
(the deployment can change this with
`endpoints.subscriptions.max_per_repository`); further ones get a 403.

A subscription may also list `build_types`, e.g., `"build_types":
["production"]`, to get only builds of these types. Each must be declared by
the repository; otherwise the request gets a 400. Without `build_types`, or
with an empty list, the subscription gets all builds that match `type` and
`value`, as before. With a non-empty `build_types` (at most 50), builds
without a type don't match. The subscription's details (`GET /subscriptions/<subscription
ID>`) show its `build_types`, the repository's (`GET /repositories/<repository
ID>`) its declared `build_types`, and each build its `build_type`, if any.

## Publish an image

The repository's CI builds and pushes the image, then publishes it:

```bash
curl --request POST '<base URL>/repositories/<repository ID>/builds' \
  --header 'X-Project-Access-Token: <repository access token>' \
  --header 'Content-Type: application/json' \
  --data '{
    "images": [{"name": "<image name>:<image tag>"}],
    "head_commit": {"tag": "<tag name>"}
  }'
```

If the repository declares build types, the build may name one of them with
`"build_type": "<build type>"`; a type that the repository doesn't declare
gets a 400. A build without a type reaches only subscriptions without
`build_types`, or with an empty list.

## Notifications

Pubgrade notifies all subscriptions of the repository at the same time, with a
timeout per call (`endpoints.subscriptions.notification_timeout` in the
configuration, by default 10 seconds, for connecting and for the response).
Results per subscription, once all calls are done, are in the field
`notifications` of the build
(`GET /repositories/<repository ID>/builds/<build ID>`):

- `delivered`: the subscriber answered with a 2xx status, so it accepted the
  notification. Pubgrade-Sidecar then rolls out in the background and reports
  the state at `GET /deployment/<deployment name>` (see its
  [API](sidecar/api.md)).
- `failed`: another response, or none in time.
- `skipped`: the subscription doesn't match the build (its `type`, `value`
  or `build_types`).

### Receiving notifications without the sidecar

Each notification is a `PUT` to the subscription's `callback_url`, with the
subscription's `access_token` in the header `X-Access-Token` and the image
in the body, split into name and tag at its last colon:

```bash
curl --request PUT '<callback URL>' \
  --header 'X-Access-Token: <subscriber access token>' \
  --header 'Content-Type: application/json' \
  --data '{"image_name": "elixircloud/tesk-api", "tag": "v1.2.0"}'
```

A listener of your own, instead of [Pubgrade-Sidecar](sidecar/index.md),
checks the token, answers with a 2xx status if it accepts the notification,
and does the actual work (e.g., triggering a CD pipeline) in the background:
it must answer in time (see above; to be safe, within `notification_timeout`
from the request). Pubgrade only reads the status
of the response, not its body, and doesn't follow redirects (a redirect
counts as `failed`). It doesn't repeat failed notifications. The API
describes the call as the callback `notification` of `POST /subscriptions`,
with the body `NotificationRequest` (see [API](api.md)); Pubgrade-Sidecar's
`PUT /deployment/<deployment name>` is an example of such a listener (see
its [API](sidecar/api.md)).

## Cancel a build

The repository's access token also allows withdrawing a build, e.g., one
published by mistake:

```bash
curl --request DELETE '<base URL>/repositories/<repository ID>/builds/<build ID>' \
  --header 'X-Project-Access-Token: <repository access token>'
```

The build is kept and stays listed, with the status `CANCELED`; `finished_at`
is set if it hadn't finished. With builds switched on, a build that is still
running is stopped (see [Builds](deployment.md#builds)): it doesn't succeed,
and no one is notified of it. Finished builds are only marked. Deployments
that have been notified keep what they pulled: Pubgrade doesn't notify them
again, undeploy anything or delete images from a registry. To roll
deployments back or forward, publish the image they should run as a new
build. A build that is canceled already gets a 409; an unknown one, or one of
another repository, gets a 404.

Builds can't be changed: to publish a corrected image, publish it as a new
build. `PUT /repositories/<repository ID>/builds/<build ID>` is Pubgrade's
internal callback for finished build pods, not a way to change a build.

## Change or delete a repository

The repository's access token also allows changing its URL, and its build
types if the request gives `build_types` (otherwise they stay as they are);
the repository keeps its identifier, access token, builds and subscriptions.
Subscriptions keep their `build_types`, also types that the repository no
longer declares; builds of those types can't be published any more:

```bash
curl --request PUT '<base URL>/repositories/<repository ID>' \
  --header 'X-Project-Access-Token: <repository access token>' \
  --header 'Content-Type: application/json' \
  --data '{"url": "<new repository URL>"}'
```

Deleting a repository deletes its builds and subscriptions too, permanently:

```bash
curl --request DELETE '<base URL>/repositories/<repository ID>' \
  --header 'X-Project-Access-Token: <repository access token>'
```

The subscriptions disappear from their users' lists, and their deployments
are no longer notified; they keep the images they already have. Pubgrade
doesn't manage deployments: to remove one, its operators undeploy it (e.g.,
with Helm or kubectl). Images and
subscriptions sent to the repository while it is deleted get a 404. With
builds switched on, its builds are stopped (see
[Builds](deployment.md#builds)).

## Queries

```bash
# Repositories
curl '<base URL>/repositories'
# Builds of a repository
curl '<base URL>/repositories/<repository ID>/builds'
# Subscriptions of a user
curl '<base URL>/subscriptions' \
  --header 'X-User-Id: <user ID>' \
  --header 'X-User-Access-Token: <user access token>'
```

See [API](api.md) for all endpoints.
