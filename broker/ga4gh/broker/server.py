"""Controllers for broker endpoints"""
from flask import request
from foca.utils.logging import log_traffic
from werkzeug.exceptions import NotFound

from broker.ga4gh.broker.endpoints.builds import (
    build_completed,
    get_build_info,
    get_builds,
    register_builds
)
from broker.ga4gh.broker.endpoints.repositories import (
    delete_repository,
    get_repositories,
    get_repository_info,
    modify_repository_info,
    register_repository
)
from broker.ga4gh.broker.endpoints.subscriptions import (
    delete_subscription,
    get_subscription_info,
    get_subscriptions,
    register_subscription,
    test_create_user
)
from tests.ga4gh.mock_data import MOCK_SUBSCRIPTION


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
    return modify_repository_info(id,
                                  request.headers['X-Project-Access-Token'],
                                  request.json)


@log_traffic
def deleteRepository(id: str):
    if delete_repository(id, request.headers['X-Project-Access-Token']) == 0:
        raise NotFound
    else:
        return {"message": "Repository deleted successfully"}


@log_traffic
def postBuild(id: str):
    return register_builds(id, request.headers['X-Project-Access-Token'],
                           request.json)


@log_traffic
def getBuilds(id: str):
    return get_builds(id)


@log_traffic
def getBuildInfo(id: str, build_id: str):
    return get_build_info(build_id)


@log_traffic
def updateBuild(id: str, build_id: str):
    return build_completed(id,
                           build_id, request.headers['X-Project-Access-Token'])


@log_traffic
def postSubscription():
    test_create_user()
    return register_subscription(request.headers['X-User-Id'],
                                 request.headers['X-User-Access-Token'],
                                 request.json)


@log_traffic
def getSubscriptions():
    return get_subscriptions(request.headers['X-User-Id'],
                             request.headers['X-User-Access-Token'])
    # return [MOCK_SUBSCRIPTION]


@log_traffic
def modifySubscription(subscription_id: str):
    return MOCK_SUBSCRIPTION


@log_traffic
def getSubscriptionInfo(subscription_id: str):
    return get_subscription_info(request.headers['X-User-Id'],
                                 request.headers['X-User-Access-Token'],
                                 subscription_id)


@log_traffic
def deleteSubscription(subscription_id: str):
    if delete_subscription(request.headers['X-User-Id'],
                           request.headers['X-User-Access-Token'],
                           subscription_id) == 0:
        raise NotFound
    else:
        MOCK_SUBSCRIPTION['subscription_id'] = subscription_id
        return MOCK_SUBSCRIPTION
