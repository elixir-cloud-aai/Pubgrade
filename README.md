# Pubgrade

[![License][badge-license]][badge-url-license]
[![Build_status][badge-build-status]][badge-url-build-status]
[![Coverage Status][badge-coverage]][badge-url-coverage]

## Description

**Pubgrade** (**Pub**lish-Up**grade**) is a decoupled, publish-subscribe-based
continuous integration (CI) and continuous delivery (CD) service that allows
developers to notify deployments of available updates. These can can then
autonomously decide what to do with them. Pubgrade has an optional link with
the [ELIXIR Cloud Service Registry][elixir-cloud-registry].

Currently supported features:

- Register Git repositories
- Create and publish builds
- Register subscriptions
- Notify subscriptions on updated builds

![app-schema][anim-schema]

## Installation

1. Install and setup [Kubernetes][kubernetes-install].
2. Install [Helm][helm-install].
3. Modify `deployment/values.yaml`.
4. Create a namespace, e.g., with `kubectl create namespace pubgrade`
5. Create a deployment using Helm with `helm install pubgrade deployment/ -n
   pubgrade`

## Usage

Register Git repository:

```bash
    curl --location --request POST 'http://{host_url}:{host_port}/repositories' \
--header 'Content-Type: application/json' \
--data-raw '{
    "url": "{ repository_url }"
}'
```

Subscribe to repository (use admin user):

```bash
curl --location --request POST 'http://{host_url}:{host_port}/subscriptions' \
--header 'X-User-Access-Token: { user_access_token }' \
--header 'X-User-Id: { user_identifier }' \
--header 'Content-Type: application/json' \
--data-raw '{
    "repository_id": "{ repository_identifier }",
    "callback_url": "{ url }",
    "access_token": "{ access_token }",
    "type": "{ branch OR tag }",
    "value": "{ branch_name OR tag_name }"
}'
```

Register build (CI should be configured to call this automatically):

```bash
    curl --location --request POST 'http://{host_url}:{host_port}/repositories/{repo_id}/builds' \
--header 'X-Project-Access-Token: { access_token }' \
--header 'Content-Type: application/json' \
--data-raw '{
    "images": [
        {
            "name": "{ image_name }",
            "location": "{ docker_file_location }"
        }
    ],
    "head_commit": {
        "branch": "{ branch_name }"
    },
    "dockerhub_token": "{ echo -n USER:PASSWD | base64 }"
}'
```

List available repositories:

```bash
curl --location --request GET 'http://{host_url}:{host_port}/repositories'
```

List available builds for a specific repository:

```bash
curl --location --request GET 'http://{host_url}:{host_port}/repositories/{repo_id}/builds'
```

List subscribed repositories:

```bash
curl --location --request GET 'http://{host_url}:{host_port}/subscriptions' \
--header 'X-User-Access-Token: { user_access_token }' \
--header 'X-User-Id: { user_identifier }'
```

## Contributing

This project is a community effort and lives off your contributions, be it in
the form of bug reports, feature requests, discussions, or fixes and other code
changes. Please refer to our organization's [contribution
guidelines][contributing] if you are interested to contribute. Please mind the
[code of conduct][coc] for all interactions with the community.

## Versioning

The project adopts the [semantic versioning][semver] scheme for versioning.
Currently the service is in beta stage, so the API may change without further
notice.

## License

This project is covered by the [Apache License 2.0][license-apache]
also [shipped with this repository][license].

## Contact

The project is a collaborative effort under the umbrella of [ELIXIR Cloud &
AAI][elixir-cloud]. Follow the link to get in touch with us via chat or email.
Please mention the name of this service for any inquiry, proposal, question etc.

![Logo_banner][img-logo-banner]

[anim-schema]: images/app-schema-animation.gif
[badge-build-status]: https://travis-ci.com/elixir-cloud-aai/Pubgrade.svg?branch=dev
[badge-coverage]: https://coveralls.io/repos/github/elixir-cloud-aai/Pubgrade/badge.svg?branch=dev
[badge-license]: https://img.shields.io/badge/license-Apache%202.0-blue.svg
[badge-url-build-status]: https://travis-ci.com/elixir-cloud-aai/Pubgrade
[badge-url-license]: http://www.apache.org/licenses/LICENSE-2.0
[badge-url-coverage]: https://coveralls.io/github/elixir-cloud-aai/Pubgrade?branch=dev
[coc]: https://github.com/elixir-cloud-aai/elixir-cloud-aai/blob/dev/CODE_OF_CONDUCT.md
[contributing]: https://github.com/elixir-cloud-aai/elixir-cloud-aai/blob/dev/CONTRIBUTING.md
[elixir-cloud]: https://github.com/elixir-cloud-aai/elixir-cloud-aai
[elixir-cloud-registry]: https://cloud-registry.rahtiapp.fi/ga4gh/registry/v1/ui/
[helm-install]: https://helm.sh/docs/intro/install/
[img-logo-banner]: images/logo-banner.svg
[kubernetes-install]: https://kubernetes.io/docs/tasks/tools/
[semver]: https://semver.org/
[license-apache]: https://www.apache.org/licenses/LICENSE-2.0
[license]: LICENSE
[ga4gh]: https://www.ga4gh.org/
