# Broker

[![License][badge-license]][badge-url-license]

## Synopsis

Broker leverages the publish-subscribe (pub/sub) pattern to effectively decouple
continuous integration (CI) from continuous deilivery (CD): developers can call
Broker in their CI pipelines to notify deployments of available updates
("publish"), while deployments can listen to update notifications ("subscribe")
and trigger specific CD pipelines set up by administrators.

Broker is particularly useful wherever deployments are managed by different
entities than those managing the underlying code bases, such as in federated
networks, in which services are deployed at multiple locations by different
organizations.

![Screenshot from 2021-05-29 15-33-18](banner-image)

## Contributing

This project is a community effort and lives off your contributions, be it in 
the form of bug reports, feature requests, discussions, or fixes and other code
changes. Please refer to our organization's 
[contribution guidelines][contributing] if you are interested to contribute. 
Please mind the [code of conduct][coc] for all interactions with the community.

## Versioning

The project adopts the [semantic versioning][semver] scheme for versioning. 
Currently the service is in beta stage, so the API may change without further
notice.

## License

This project is covered by the [Apache License 2.0][license-apache] also 
[shipped with this repository][license].

## Contact

The project is a collaborative effort under the umbrella of 
[ELIXIR Cloud & AAI][elixir-cloud]. Follow the link to get in touch with us via 
chat or email. Please mention the name of this service for any inquiry, 
proposal, question etc.


[badge-license]:<https://img.shields.io/badge/license-Apache%202.0-blue.svg>
[badge-url-license]:<http://www.apache.org/licenses/LICENSE-2.0>
[banner-image]:<https://user-images.githubusercontent.com/46739435/120494133-2c17aa00-c3d9-11eb-80b9-b8c03c76e1cb.png>
[contributing]: <https://github.com/elixir-cloud-aai/elixir-cloud-aai/blob/dev/CONTRIBUTING.md>
[elixir-cloud]: <https://github.com/elixir-cloud-aai/elixir-cloud-aai>
[elixir-cloud-registry]:<https://cloud-registry.rahtiapp.fi/ga4gh/registry/v1/ui/>
[semver]: <https://semver.org/>
[license-apache]: <https://www.apache.org/licenses/LICENSE-2.0>
[license]: LICENSE
[ga4gh]:<https://www.ga4gh.org/>
[coc]: <https://github.com/elixir-cloud-aai/elixir-cloud-aai/blob/dev/CODE_OF_CONDUCT.md>

