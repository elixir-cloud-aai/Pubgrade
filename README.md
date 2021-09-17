# Pubgrade

[![License][badge-license]][badge-url-license]
[![Build_status][badge-build-status]][badge-url-build-status]
[![Coverage Status][coverage-badge-svg]][badge-url-coverage]

## Description

**Pubgrade** (**Pub**lish-Up**grade**) is a decoupled, publish-subscribe-based continuous integration (CI) and continuous delivery (CD) microservice that allows developers to notify deployments of available updates, which can then autonomously decide what to do with them. Pubgrade has an optional link with [ELIXIR Cloud Service Registry][elixir-cloud-registry].

Currently supported features:
- Register git repository.
- Create and publish build.
- Register subscriptions.
- Notify subscription on build update.

![app-schema][diagram]

## Installation

1. Install and setup [kubernetes][kubernetes-install].
2. Install [Helm][helm-install].
3. Modify deployment/values.yaml.
4. Create a namespace. `kubectl create namespace pubgrade`
5. Create deployment using helm. `helm install pubgrade deployment/ -n pubgrade`

## Usage

1. Register git repository.
    ```curl
    curl --location --request POST 'http://{host_url}:{host_port}/repositories' \
--header 'Content-Type: application/json' \
--data-raw '{
    "url": "https://github.com/lvarin/k8s-updater"
}'
    ```
2. Register build. (Generated automatically after completion of CI)
    ```curl
    curl --location --request POST 'http://{host_url}:{host_port}/repositories/{repo_id}/builds' \
--header 'X-Project-Access-Token: {access_token}' \
--header 'Content-Type: application/json' \
--data-raw '{
    "images": [
        {
            "name": "{image_name}",
            "location": "{docker_file_location}"
        }
    ],
    "head_commit": {
        "branch": "{branch_name}"
    },
    "dockerhub_token": "{echo -n USER:PASSWD | base64}"
}'
    ```

## Contributing

This project is a community effort and lives off your contributions, be it in
the form of bug reports, feature requests, discussions, or fixes and other code
changes. Please refer to our
organization's [contribution guidelines][contributing] if you are interested to
contribute. Please mind the [code of conduct][coc] for all interactions with
the community.

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


[badge-build-status]:<https://travis-ci.com/elixir-cloud-aai/Broker.svg?branch=feature_controllers>
[badge-license]:<https://img.shields.io/badge/license-Apache%202.0-blue.svg>
[badge-url-build-status]:<https://travis-ci.com/elixir-cloud-aai/Broker>
[badge-url-coverage]:<https://coveralls.io/github/elixir-cloud-aai/Broker?branch=feature_controllers>
[coverage-badge-svg]:<https://coveralls.io/repos/github/elixir-cloud-aai/Broker/badge.svg?branch=feature_controllers>
[contributing]: <https://github.com/elixir-cloud-aai/elixir-cloud-aai/blob/dev/CONTRIBUTING.md>
[diagram]: app-schema.svg
[elixir-cloud]: <https://github.com/elixir-cloud-aai/elixir-cloud-aai>
[elixir-cloud-registry]:<https://cloud-registry.rahtiapp.fi/ga4gh/registry/v1/ui/>
[helm-install]:<https://helm.sh/docs/intro/install/>
[kubernetes-install]:<https://kubernetes.io/docs/tasks/tools/>
[semver]: <https://semver.org/>
[license-apache]: <https://www.apache.org/licenses/LICENSE-2.0>
[license]: LICENSE
[badge-license]:<https://img.shields.io/badge/license-Apache%202.0-blue.svg>
[badge-url-license]:<http://www.apache.org/licenses/LICENSE-2.0>
[ga4gh]:<https://www.ga4gh.org/>
[coc]: <https://github.com/elixir-cloud-aai/elixir-cloud-aai/blob/dev/CODE_OF_CONDUCT.md>
