"""Controllers for broker endpoints"""

from werkzeug.exceptions import NotFound
from broker.ga4gh.broker.endpoints.repositories import (
get_repositories,
get_repository_info,
modify_repository_info,
register_repository,
delete_repository)

import json

from flask import (current_app, request)
from random import choice
from foca.utils.logging import log_traffic
from typing import (Dict)

from broker.errors.exceptions import (
    AccessMethodNotFound,
    InternalServerError,
    URLNotFound,
    BadRequest,
)

from tests.ga4gh.mock_data import (
    MOCK_SUBSCRIPTION,
    MOCK_POST_REPOSITORY,
    MOCK_BUILD_INFO,
    MOCK_REPOSITORY,
    MOCK_SUBSCRIPTION_INFO
)


@log_traffic
def getRepositories():
    return get_repositories()

@log_traffic
def postRepositories():
    return register_repository(request.json)


@log_traffic
def getRepository(id: str):
    return get_repository_info(id)

@log_traffic
def putRepositories(id: str):
    return modify_repository_info(id, request.json)

@log_traffic
def deleteRepository(id: str):
    if delete_repository(id) == 0:
        raise NotFound
    else:
        return {"message": "Repository deleted successfully"}

@log_traffic
def postBuild(id: str):
    return json.loads('{"id": "build_123"}')

@log_traffic
def getBuilds(id: str):
    return [   MOCK_BUILD_INFO,    MOCK_BUILD_INFO ]

@log_traffic
def getBuildInfo(id: str, build_id: str):
    return MOCK_BUILD_INFO


@log_traffic
def postSubscription():
    return MOCK_SUBSCRIPTION

@log_traffic
def getSubscriptions():
    return [MOCK_SUBSCRIPTION]

@log_traffic
def modifySubscription(subscription_id: str):
    return MOCK_SUBSCRIPTION

@log_traffic
def getSubscriptionInfo(subscription_id: str):
    return MOCK_SUBSCRIPTION_INFO

@log_traffic
def deleteSubscription(subscription_id: str):
    return MOCK_SUBSCRIPTION

