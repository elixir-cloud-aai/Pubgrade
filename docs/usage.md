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
- `skipped`: the subscription doesn't match the build.

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
