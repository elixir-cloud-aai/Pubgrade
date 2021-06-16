"""Controllers for broker endpoints"""

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
    return [{'projectId':'project_12',  'type':'production', 'url':'https://goo.gl', 'dockerfileLocation':'./docker', 'containerRegistryUrl':'gcr.io/my-project/busybox', 'containerRegistryToken':'XXXXXXXXXXXXXXX' }]

@log_traffic
def postRepositories():
    return "Template function: postProjects"

@log_traffic
def postProjects():
    return "Template function: postProjects"

@log_traffic
def getRepository(id: str):
    return "Template function: postBuild"

@log_traffic
def putRepositories(id: str):
    return "Template function: getBuilds"

@log_traffic
def deleteRepository(id: str):
    return "Template function: deleteProject"

@log_traffic
def postBuild(id: str):
    return "Template function: modifyBuild"

@log_traffic
def getBuilds(id: str):
    return "Template function: getBuildInfo"

@log_traffic
def getBuildInfo(id: str, build_id: str):
    return "Template function: deleteBuild"

@log_traffic
def postSubscription():
    return "Template function: postService"

@log_traffic
def getSubscriptions():
    return "Template function: getServices"

@log_traffic
def modifySubscription(subscription_id: str):
    return "Template function: modifyService"

@log_traffic
def getSubscriptionInfo(subscription_id: str):
    return "Template function: getServiceInfo"

@log_traffic
def deleteSubscription(subscription_id: str):
    return "Template function: deleteService"
