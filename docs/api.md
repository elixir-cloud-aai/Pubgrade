# API

The API is described by its OpenAPI specification,
[`pubgrade/api/pubgrade.yaml`](https://github.com/elixir-cloud-aai/Pubgrade/blob/dev/pubgrade/api/pubgrade.yaml).
A running Pubgrade serves it at `/openapi.json`, with a web interface to try
the endpoints at `/ui/`. Pubgrade validates requests and responses against it.

```text
Endpoint                                        Who
GET     /repositories                           anyone
POST    /repositories                           anyone, while registration is open
GET     /repositories/{id}                      anyone
PUT     /repositories/{id}                      the repository (its access token)
DELETE  /repositories/{id}                      the repository
GET     /repositories/{id}/builds               anyone
POST    /repositories/{id}/builds               the repository: publish an image
GET     /repositories/{id}/builds/{build_id}    anyone
PUT     /repositories/{id}/builds/{build_id}    the repository, with builds on only
POST    /users/register                         anyone, while registration is open
DELETE  /users/register                         the user
GET     /users                                  admins
PUT     /users/{uid}/verify                     admins
PUT     /users/{uid}/unverify                   admins
GET     /subscriptions                          verified users: their subscriptions
POST    /subscriptions                          verified users, while registration is open
GET     /subscriptions/{subscription_id}        the subscription's user
DELETE  /subscriptions/{subscription_id}        the subscription's user
```

Registrations are open until they are closed in the
[configuration](deployment.md#configuration). The specification is the
reference for the request and response bodies and the headers that carry the
tokens. See [Usage](usage.md) for the typical flow.
