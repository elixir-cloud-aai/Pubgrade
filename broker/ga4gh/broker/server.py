"""Controllers for broker endpoints"""

from broker.ga4gh.broker.endpoints.builds import (get_build_info, get_builds, register_builds)
from flask.wrappers import Response
from werkzeug.exceptions import NotFound
from broker.ga4gh.broker.endpoints.repositories import (
get_repositories,
get_repository_info,
modify_repository_info,
register_repository,
delete_repository)

import logging
logger = logging.getLogger(__name__)

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
    return modify_repository_info(id,request.headers['X-Project-Access-Token'], request.json)

@log_traffic
def deleteRepository(id: str):
    if delete_repository(id, request.headers['X-Project-Access-Token']) == 0:
        raise NotFound
    else:
        return {"message": "Repository deleted successfully"}

@log_traffic
def postBuild(id: str):
    return register_builds(id, request.headers['X-Project-Access-Token'], request.json)

@log_traffic
def getBuilds(id: str):
    get_builds(id)
    return get_builds(id)

@log_traffic
def getBuildInfo(id: str, build_id: str):
    return get_build_info(id, build_id)


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

