<!-- markdownlint-disable MD033 MD041 -- logo first; <picture> for dark mode -->
<a href="https://elixir-on.cloud/">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo_elixir_on_cloud_night.png">
    <img src="docs/images/logo_elixir_on_cloud.png" alt="ELIXIR On-Cloud">
  </picture>
</a>
<!-- markdownlint-enable MD033 MD041 -->

# Pubgrade

[![License][badge-license]][badge-url-license]
[![Build_status][badge-build-status]][badge-url-build-status]
[![Docs][badge-docs]][badge-url-docs]
[![Coverage][badge-coverage]][badge-url-coverage]
[![GitHub_tag][badge-github-tag]][badge-url-github-tag]
[![Docker_image][badge-docker]][badge-url-docker]

<!-- --8<-- [start:synopsis] -->
**Pubgrade** (**Pub**lish-Up**grade**) is a publish-subscribe service that
notifies deployments of new images of the software they run, brought to you
by [ELIXIR On-Cloud](https://elixir-on.cloud/). A repository's CI publishes a
new image to Pubgrade; Pubgrade notifies all deployments that subscribed to
the repository's tag or branch at the same time, and records the result per
subscriber. Each deployment decides what to do with a notification:
[Pubgrade-Sidecar](https://github.com/elixir-cloud-aai/Pubgrade-Sidecar), next
to a Kubernetes Deployment, updates its image. Deploy Pubgrade to Kubernetes
or OpenShift with its Helm chart.
<!-- --8<-- [end:synopsis] -->

**Read the [documentation][docs]** for using the API, the deployment with the
Helm chart in [`helm/`][helm], development, and Pubgrade-Sidecar.

## Quick start

<!-- --8<-- [start:quick-start] -->
Install Pubgrade and a MongoDB into a namespace of a Kubernetes or OpenShift
cluster with [Helm](https://helm.sh/docs/intro/install/), from a checkout of
this repository, with your copy of the configuration (`pubgrade/config.yaml`,
with your admin users) in a Secret. Keep that copy outside the checkout, so
that its tokens don't end up in Git or in images you build:

```bash
git clone https://github.com/elixir-cloud-aai/Pubgrade.git && cd Pubgrade
cp pubgrade/config.yaml ~/pubgrade-config.yaml  # then add your admin users
kubectl create namespace pubgrade
kubectl create secret generic pubgrade-config -n pubgrade \
  --from-file=config.yaml="${HOME}/pubgrade-config.yaml"
helm install pubgrade helm/ -n pubgrade \
  --set pubgrade.configSecret=pubgrade-config --set hostName=<host name>
```

Then open the API's web interface at `https://<host name>/ui/`.
<!-- --8<-- [end:quick-start] -->

## Contributing

Contributions are welcome! See [Development][docs-development] in the
documentation and the organisation's [contributing guide][contributing], and
mind our [code of conduct][code-of-conduct].

## License

This project is covered by the [Apache License 2.0][badge-url-license], also
[shipped with this repository](LICENSE).

[badge-build-status]: <https://github.com/elixir-cloud-aai/Pubgrade/actions/workflows/ci.yml/badge.svg?branch=dev>
[badge-coverage]: <https://codecov.io/gh/elixir-cloud-aai/Pubgrade/branch/dev/graph/badge.svg?branch=dev>
[badge-docker]: <https://img.shields.io/docker/v/elixircloud/pubgrade?sort=date&label=image&color=C39BD3>
[badge-docs]: <https://img.shields.io/readthedocs/pubgrade>
[badge-github-tag]: <https://img.shields.io/github/v/tag/elixir-cloud-aai/Pubgrade?color=C39BD3>
[badge-license]: <https://img.shields.io/badge/license-Apache%202.0-blue.svg>
[badge-url-build-status]: <https://github.com/elixir-cloud-aai/Pubgrade/actions/workflows/ci.yml?query=branch%3Adev>
[badge-url-coverage]: <https://codecov.io/gh/elixir-cloud-aai/Pubgrade?branch=dev>
[badge-url-docker]: <https://hub.docker.com/r/elixircloud/pubgrade/tags>
[badge-url-docs]: <https://pubgrade.readthedocs.io/en/latest/>
[badge-url-github-tag]: <https://github.com/elixir-cloud-aai/Pubgrade/releases>
[badge-url-license]: <https://www.apache.org/licenses/LICENSE-2.0>
[code-of-conduct]: <https://github.com/elixir-cloud-aai/.github/blob/main/CODE_OF_CONDUCT.md>
[contributing]: <https://github.com/elixir-cloud-aai/.github/blob/main/CONTRIBUTING.md>
[docs]: <https://pubgrade.readthedocs.io/en/latest/>
[docs-development]: <https://pubgrade.readthedocs.io/en/latest/development/>
[helm]: helm/
