# Pubgrade

[![License][badge-license]][badge-url-license]
[![Build_status][badge-build-status]][badge-url-build-status]

## Description

**Pubgrade** (**Pub**lish-Up**grade**) is a decoupled, publish-subscribe-based
continuous integration (CI) and continuous delivery (CD) service that allows
developers to notify deployments of available updates. These can can then
autonomously decide what to do with them. Pubgrade has an optional link with
the [ELIXIR Cloud Service Registry][elixir-cloud-registry].

Currently supported features:

- Register git repository.
- Create and publish builds.
- Register subscriptions.
- Notify subscriptions on build updates.

![app-schema][anim-schema]

## Installation

The Helm chart in `helm/` installs Pubgrade and a MongoDB on Kubernetes or
OpenShift, into any namespace, without special rights. Install one release per
namespace, as resource names are fixed.

1. Install and setup [kubernetes][kubernetes-install].
2. Install [Helm][helm-install].
3. Create a namespace: `kubectl create namespace pubgrade`
4. Copy `pubgrade/config.yaml`, add your admin users with new tokens under
   `endpoints.subscriptions.admin_users`, and store it in a Secret:
   `kubectl create secret generic pubgrade-config -n pubgrade --from-file=config.yaml`.
   Secrets don't belong in values files. Admin users are the only ones who can
   verify other users. After changing the Secret, restart Pubgrade: the database
   then follows the list of admin users.
5. Install: `helm install pubgrade helm/ -n pubgrade --set pubgrade.configSecret=pubgrade-config --set hostName=<host name>`

The service is exposed by a Route if the cluster serves Routes (OpenShift; TLS
at the router); on other clusters, enable it with
`--set pubgrade.ingress.enabled=true`, which requests a certificate from
[cert-manager][cert-manager] by default. See `helm/values.yaml` for all values.
Pubgrade's pods run as any user ID in group 0, with no fixed ID, as OpenShift
assigns its own.

Builds are off by default. To let Pubgrade build images, set
`endpoints.builds.enabled` in the configuration and `builds.enabled` in the
chart, which must match, with the other values under `builds`; this adds an
updater, a shared volume and rights to manage pods in the namespace. The volume
needs a storage class with `ReadWriteMany` (`builds.volume.storageClass`). Build
pods run as root, so builds don't work under OpenShift's default restrictions.

### Moving from chart 0.1

Chart 0.2 can't upgrade a 0.1 release, as its selectors and names changed:

- Remove the old release and install anew. MongoDB's volume has a new name and a
  newer major version, so its data doesn't carry over: register repositories and
  subscriptions again.
- Values were renamed: `pubgrade_webserver` to `pubgrade`, `pubgrade_mongodb` to
  `mongodb`, `pubgrade_build_complete_updater` to `builds.updater`,
  `pubgrade_url` to `builds.pubgradeUrl`, and the Ingress's `url` to `hostName`.
- The configuration in the image has no admin users any more, and no debug mode:
  bring your own, with new tokens, in a Secret (step 4).
- The Secret `pubgrade-secret` is gone: with builds on, create your own
  (`builds.existingSecret`).

## Usage

1. Register git repository.

```bash
    curl --location --request POST 'http://<host_url>:<host_port>/repositories' \
--header 'Content-Type: application/json' \
--data-raw '{
    "url": "<repository_url>"
}'
```

2. Create a user (System administrator).

```bash
curl --location --request POST 'http://<host_url>:<host_port>/users/register' \
--header 'Content-Type: application/json' \
--data-raw '{
    "name": "<name>"
}'
```

3. Ask pubgrade admin to verify created user. (Only Admin) 

```bash
curl --location --request PUT 'http://<host_url>:<host_port>/users/<user-id>/verify' \
--header 'X-Super-User-Access-Token: <Super-User-Access-Token>' \
--header 'X-Super-User-Id: <Super-User-Id>'
```

4. Subscribe to `repository`. (Use admin user)

```bash
curl --location --request POST 'http://<host_url>:<host_port>/subscriptions' \
--header 'X-User-Access-Token: <user_access_token>' \
--header 'X-User-Id: <user_identifier>' \
--header 'Content-Type: application/json' \
--data-raw '{
    "repository_id": "<repository_identifier>",
    "callback_url": "<url>",
    "access_token": "<access_token>",
    "type": "<branch OR tag>",
    "value": "<branch_name OR tag_name>"
}'
```

   Pubgrade sends `access_token` to `callback_url`, so use `https` for anything
   outside the cluster.

5. Publish an image. (The repository's CI builds and pushes the image, then
   calls this)

```bash
    curl --location --request POST 'http://<host_url>:<host_port>/repositories/{repo_id}/builds' \
--header 'X-Project-Access-Token: <access_token>' \
--header 'Content-Type: application/json' \
--data-raw '{
    "images": [
        {
            "name": "<image_name>:<image_tag>"
       }
    ],
    "head_commit": {
        "tag": "<tag_name>"
   }
}'
```

A subscription's `value` must equal the `tag` or `branch` of `head_commit`; the
value `*` matches any of them, e.g., every new tag.

Pubgrade notifies all subscriptions of the repository at the same time, with a
timeout per call (`endpoints.subscriptions.notification_timeout` in the
configuration, by default 10 seconds, for connecting and for the response). Results per subscription, once all calls
are done, are in the field `notifications` of the build
(`GET /repositories/{repo_id}/builds/{build_id}`): `delivered` for a 2xx
response, `failed` for another response or none in time, `skipped` if the
subscription doesn't match the build. `delivered` means that the subscriber
accepted the notification: Pubgrade-Sidecar then rolls out in the background,
and reports the state at `GET /deployment/{deployment-name}`. A repository takes at most 100
subscriptions (`endpoints.subscriptions.max_per_repository`); further ones get a
403.

### Configuration

Settings under `endpoints` in the configuration (`pubgrade/config.yaml`):

- `builds.enabled` (default: off): with this on, Pubgrade clones the repository
  and builds the image, and step 5 also needs a `location` for the image and a
  `dockerhub_token`. With this off, such requests get a 403, as does
  `PUT /repositories/{repo_id}/builds/{build_id}`.
- `repository.registration_enabled`, `user.registration_enabled` and
  `subscriptions.registration_enabled` (default: on): switch these off once
  repositories, users and subscriptions are set up. Further registrations then
  get a 403.

### Queries

List available repositories.

```bash
curl --location --request GET 'http://<host_url>:<host_port>/repositories'
```

List available builds for the repository.

```bash
curl --location --request GET 'http://<host_url>:<host_port>/repositories/{repo_id}/builds'
```

List subscribed repositories

```bash
curl --location --request GET 'http://<host_url>:<host_port>/subscriptions' \
--header 'X-User-Access-Token: <user_access_token>' \
--header 'X-User-Id: <user_identifier>'
```

## Contributing

This project is a community effort and lives off your contributions, be it in
the form of bug reports, feature requests, discussions, or fixes and other code
changes. Please refer to our organization's [contribution guidelines][contributing] if you are interested to
contribute. Please mind the [code of conduct][coc] for all interactions with
the community.

## Development

`make test` builds the image and runs the unit tests in it, with coverage: the
base image of [FOCA][foca] pins most of the dependencies. Some tests clone a
public repository, so they need network access.

`tests/e2e/upgrade.sh` tests the whole path, and needs Docker, Helm and jq: it
starts a throwaway k3s cluster, installs Pubgrade from its chart, sets up two
namespaces with a Deployment and a sidecar each, publishes one image and checks
that both roll out. It also covers an unreachable subscriber and a tag that
doesn't exist, which takes a few minutes, as sidecars retry first. Sidecars are built from the branch `master` of
[Pubgrade-Sidecar](https://github.com/elixir-cloud-aai/Pubgrade-Sidecar); set
`SIDECAR_IMAGE` to use a local image instead. CI runs this test as well.

[CI](.github/workflows/ci.yml) runs on pull requests and pushes to `dev`. The
job `CI passed` sums up all other jobs. Pushes to `dev` publish
`elixircloud/pubgrade` and `elixircloud/pubgrade-updater`, tagged `dev`,
`sha-<commit>` and `<YYYYMMDD>`. The tag `latest` stays as it is until there are
releases, so use one of these instead.

## Versioning

The project adopts the [semantic versioning][semver] scheme for versioning.
Currently the service is in beta stage, so the API may change without further
notice.

## License

This project is covered by the [Apache License 2.0][license-apache]
also [shipped with this repository][license].

## Contact

The project is a collaborative effort under the umbrella
of [ELIXIR Cloud & AAI][elixir-cloud]. Follow the link to get in touch with us
via chat or email. Please mention the name of this service for any inquiry,
proposal, question etc.

[anim-schema]: images/app-schema-animation.gif
[badge-build-status]: https://github.com/elixir-cloud-aai/Pubgrade/actions/workflows/ci.yml/badge.svg?branch=dev
[badge-license]: https://img.shields.io/badge/license-Apache%202.0-blue.svg
[badge-url-build-status]: https://github.com/elixir-cloud-aai/Pubgrade/actions/workflows/ci.yml
[contributing]: https://github.com/elixir-cloud-aai/elixir-cloud-aai/blob/dev/CONTRIBUTING.md
[cert-manager]: https://cert-manager.io/
[elixir-cloud]: https://github.com/elixir-cloud-aai/elixir-cloud-aai
[elixir-cloud-registry]: https://cloud-registry.rahtiapp.fi/ga4gh/registry/v1/ui/
[helm-install]: https://helm.sh/docs/intro/install/
[kubernetes-install]: https://kubernetes.io/docs/tasks/tools/
[semver]: https://semver.org/
[license-apache]: https://www.apache.org/licenses/LICENSE-2.0
[license]: LICENSE
[badge-license]: https://img.shields.io/badge/license-Apache%202.0-blue.svg
[badge-url-license]: http://www.apache.org/licenses/LICENSE-2.0
[foca]: https://github.com/elixir-cloud-aai/foca
[ga4gh]: https://www.ga4gh.org/
[coc]: https://github.com/elixir-cloud-aai/elixir-cloud-aai/blob/dev/CODE_OF_CONDUCT.md