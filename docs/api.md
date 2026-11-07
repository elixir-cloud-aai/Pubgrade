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
PUT     /repositories/{id}/builds/{build_id}    internal: build pods report completion
DELETE  /repositories/{id}/builds/{build_id}    the repository: cancel a build
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

`PUT /repositories/{id}` changes only the repository's URL. `DELETE
/repositories/{id}` also deletes the repository's builds and subscriptions
(see [Usage](usage.md#change-or-delete-a-repository)).

`DELETE /repositories/{id}/builds/{build_id}` withdraws a build: it is kept,
with the status `CANCELED` (see [Usage](usage.md#cancel-a-build)); a
repeated request gets `409 Conflict`. Builds can't be changed: a changed
build is a new `POST /repositories/{id}/builds`. `PUT
/repositories/{id}/builds/{build_id}` is the internal callback with which
build pods report their completion (with builds switched on only, else
`403`); for a canceled build, it gets a `409`.

Registrations are open until they are closed in the
[configuration](deployment.md#configuration). The specification is the
reference for the request and response bodies and the headers that carry the
tokens. See [Usage](usage.md) for the typical flow.

Since version 2.0.0 of the API, errors are
[problem details](https://www.rfc-editor.org/rfc/rfc9457)
(`application/problem+json`), with `title`, `status` (an integer) and
`detail`, e.g.:

```json
{
  "title": "Not Found",
  "status": 404,
  "detail": "The requested `Repository` is not found."
}
```

For invalid requests, `detail` tells what is wrong. Before, errors had `msg`
and `status_code` (a string) instead. Request bodies larger than 1 MiB are
rejected with `413`. Timestamps (`started_at`, `finished_at` and
`updated_at`) are in UTC with time zone (e.g.,
`2026-11-06T14:04:04.619000+00:00`), and `finished_at` of a build is `null`
until it has finished (before: `"NULL"`).
