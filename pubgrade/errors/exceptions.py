from connexion.exceptions import (
    ExtraParameterProblem,
    Forbidden,
    Unauthorized,
    BadRequestProblem
)
from git import GitCommandError

from werkzeug.exceptions import (
    BadRequest,
    InternalServerError,
    NotFound,
)


class AccessMethodNotFound(NotFound):
    """Raised when access method of object with given object and access
    identifiers was not found."""
    pass


class RepositoryNotFound(NotFound):
    """Raised when object with given repository identifier was not found."""
    pass


class BuildNotFound(NotFound):
    """Raised when object with given build identifier was not found."""
    pass


class SubscriptionNotFound(NotFound):
    """Raised when object with given subscription identifier was not found."""
    pass


class UserNotFound(NotFound):
    """Raised when user with given identifier was not found."""
    pass


class URLNotFound(BadRequest):
    """Raised when repository URL for object was not found."""
    pass


class MongoError(InternalServerError):
    """Raised when Mongo operations raise an Unexpected error."""
    pass


class RequestNotSent(InternalServerError):
    """Raised when something unexpected happen while requesting side-car
    service for deploying updates."""
    pass


class WrongGitCommand(InternalServerError):
    """Raised when there is problem while cloning repository."""
    pass


class ValidationError(Exception):
    """Value or object is not compatible with required type or schema."""


class CreatePodError(InternalServerError):
    """Raised when encountered error while creating pod."""
    pass


class DeletePodError(InternalServerError):
    """Raised when encountered an error while deleting pod."""
    pass


exceptions = {
    Exception: {
        "msg": "An unexpected error occurred.",
        "status_code": '500',
    },
    BadRequestProblem: {
        "msg": "The request is malformed.",
        "status_code": '400',
    },
    BadRequest: {
        "msg": "The request is malformed.",
        "status_code": '400',
    },
    ExtraParameterProblem: {
        "msg": "The request is malformed.",
        "status_code": '400',
    },
    Unauthorized: {
        "msg": "The request is unauthorized.",
        "status_code": '401',
    },
    Forbidden: {
        "msg": "The requester is not authorized to perform this action.",
        "status_code": '403',
    },
    NotFound: {
        "msg": "The requested resource wasn't found.",
        "status_code": '404',
    },
    InternalServerError: {
        "msg": "An unexpected error occurred",
        "status_code": '500',
    },
    RepositoryNotFound: {
        "msg": "The requested `Repository` is not found.",
        "status_code": '404',
    },
    BuildNotFound: {
        "msg": "The requested `Build` is not found.",
        "status_code": '404',
    },
    UserNotFound: {
        "msg": "User not found.",
        "status_code": '404',
    },
    SubscriptionNotFound: {
        "msg": "Subscription not found for this user.",
        "status_code": '404',
    },
    ValidationError: {
        "msg": "An unexpected error occurred while Mongo read/write/update",
        "status_code": '500',
    },
    GitCommandError: {
        "msg": "GitCommandError: An expected error occurred while cloning git "
               "repository.",
        "status_code": '500'
    },
    OSError: {
        "msg": "Input/Output operation failed while creating deployment file.",
        "status_code": '400'
    },
    DeletePodError: {
        "msg": "Unable to delete pod check deployment name and namespace ENV.",
        "status_code": "500"
    },
    CreatePodError: {
        "msg": "Unable to create pod.",
        "status_code": "500"
    },
    RequestNotSent: {
        "msg": "Unable to update deployment.",
        "status_code": '500'
    },
    WrongGitCommand: {
        "msg": "Git repository information is wrong",
        "status_code": '500'
    },
    # URLNotFound: {
    #     "msg": "Repository URL not found in the request.",
    #     "status_request": '400'
    # }
}
