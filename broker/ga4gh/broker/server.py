"""Controllers for broker endpoints"""

import json

from flask import (current_app, make_response)

from foca.utils.logging import log_traffic

from broker.errors.exceptions import (
    AccessMethodNotFound,
    InternalServerError,
    ObjectNotFound,
    URLNotFound,
    BadRequest,
)

@log_traffic
def getRepositories():
    return json.loads('[{"url":"https", "repository_id": "repo_123"}]')
@log_traffic
def postRepositories():
    return json.loads('{"access_token": "xxxxxxxxxxxxxx","id": "repository_123" }')

# @log_traffic
# def postProjects():
#     return json.loads('')

@log_traffic
def getRepository(id: str):
    return json.loads('{"url":"https://localhost:8080/repositories", "repository_id": "repo_123"}')

@log_traffic
def putRepositories(id: str):
    return json.loads('{  "access_token": "xxxxxxxxxxxxxx",  "id": "repository_123"}')

@log_traffic
def deleteRepository(id: str):
    return json.loads('{"message": "Repository deleted successfully"}')

@log_traffic
def postBuild(id: str):
    return json.loads('{"id": "build_123"}')

@log_traffic
def getBuilds(id: str):
    return json.loads('[   {    "images": [        {            "name": "akash7778/broker:0.0.1",            "location": "./Dockerfile"        },        {            "name": "akash7778/broker:0.0.1",            "location": "./Dockerfile"        }    ],    "head_commit": {        "branch": "development",        "commit_sha": "930fd5"    },    "status": "UNKNOWN",    "started_at" : "2021-06-11T17:32:28Z",    "finished_at": "2021-06-11T17:32:28Z"},    {    "images": [        {            "name": "akash7778/broker:0.0.1",            "location": "./Dockerfile"        },        {            "name": "akash7778/broker:0.0.1",            "location": "./Dockerfile"        }    ],    "head_commit": {        "branch": "development",        "commit_sha": "930fd5"    },    "status": "UNKNOWN",    "started_at" : "2021-06-11T17:32:28Z",    "finished_at": "2021-06-11T17:32:28Z"} ]')

@log_traffic
def getBuildInfo(id: str, build_id: str):
    return json.loads('    {    "images": [        {            "name": "akash7778/broker:0.0.1",            "location": "./Dockerfile"        },        {            "name": "akash7778/broker:0.0.1",            "location": "./Dockerfile"        }    ],    "head_commit": {        "branch": "development",        "commit_sha": "930fd5"    },    "status": "UNKNOWN",    "started_at" : "2021-06-11T17:32:28Z",    "finished_at": "2021-06-11T17:32:28Z"}')



   

@log_traffic
def postSubscription():
    return json.loads('{ "subscription_id": "subscription-xyz"}')

@log_traffic
def getSubscriptions():
    return json.loads('[  { "subscription_id": "subscription-xyz"  }]')

@log_traffic
def modifySubscription(subscription_id: str):
    return json.loads(' { "subscription_id": "subscription-xyz"  }')

@log_traffic
def getSubscriptionInfo(subscription_id: str):
    return json.loads('{  "callback_url": "https://ec2-54-203-145-132.compute-1.amazonaws.com/update",  "repository_id": "respository123",  "build_id": "build_123",  "build_type": "production",  "state": "Active",  "updated_at": "2021-06-11T17:32:28+00:00"}')

@log_traffic
def deleteSubscription(subscription_id: str):
    return json.loads('{ "subscription_id": "subscription-xyz"  }')
