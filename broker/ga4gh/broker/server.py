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
def getProjects():
    return [{'projectId':'project_12',  'type':'production', 'url':'https://goo.gl', 'dockerfileLocation':'./docker', 'containerRegistryUrl':'gcr.io/my-project/busybox', 'containerRegistryToken':'XXXXXXXXXXXXXXX' }]

@log_traffic
def postProjects():
    return "Template function: postProjects"

@log_traffic
def postBuild(projectId: str):
    return "Template function: postBuild"

@log_traffic
def getBuilds(projectId: str):
    return "Template function: getBuilds"

@log_traffic
def deleteProject(projectId: str):
    return "Template function: deleteProject"

@log_traffic
def modifyBuild(projectId: str, buildId: str):
    return "Template function: modifyBuild"

@log_traffic
def getBuildInfo(projectId: str, buildId: str):
    return "Template function: getBuildInfo"

@log_traffic
def deleteBuild(projectId: str, buildId: str):
    return "Template function: deleteBuild"

@log_traffic
def postService():
    return "Template function: postService"

@log_traffic
def getServices():
    return "Template function: getServices"

@log_traffic
def modifyService(subscriptionId: str):
    return "Template function: modifyService"

@log_traffic
def getServiceInfo(subscriptionId: str):
    return "Template function: getServiceInfo"

@log_traffic
def deleteService(subscriptionId: str):
    return "Template function: deleteService"

@log_traffic
def postServiceFromRegistry():
    return "Template function: postServiceFromRegistry"

@log_traffic
def deleteServiceFromRegistry():
    return "Template function: deleteServiceFromRegistry"

