"""Exceptions of Pubgrade and their API responses."""

from connexion.exceptions import (
    BadRequestProblem,
    ExtraParameterProblem,
    Forbidden,
    Unauthorized,
)
from git import GitCommandError
from werkzeug.exceptions import (
    BadRequest,
    InternalServerError,
    NotFound,
)


class RepositoryNotFound(NotFound):
    """Raised when object with given repository identifier was not found."""

    pass


class TooManySubscriptions(Forbidden):
    """Raised when a repository has reached its limit of subscriptions."""

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


class NameNotFound(BadRequest):
    """Raised when name for user was not found in request."""

    pass


class UserNotVerified(Forbidden):
    """Raised when user with given identifier was not verified."""

    pass


class BuildsDisabled(Forbidden):
    """Raised when a request needs the build path, which is switched off."""

    pass


class RegistrationDisabled(Forbidden):
    """Raised when registration is closed by configuration."""

    pass


class InvalidImage(BadRequest):
    """Raised when a request doesn't name exactly one image with a tag."""

    pass


class MongoError(InternalServerError):
    """Raised when Mongo operations raise an Unexpected error."""

    pass


class GitCloningError(InternalServerError):
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


# Problem details (RFC 9457) of the exceptions, by class (`exceptions.mapping`
# in the configuration); exceptions that aren't listed get those of their
# closest listed base class
exceptions = {
    Exception: {
        "title": "Internal Server Error",
        "status": 500,
        "detail": "An unexpected error occurred.",
    },
    BadRequestProblem: {
        "title": "Bad Request",
        "status": 400,
        "detail": "The request is malformed.",
    },
    BadRequest: {
        "title": "Bad Request",
        "status": 400,
        "detail": "The request is malformed.",
    },
    ExtraParameterProblem: {
        "title": "Bad Request",
        "status": 400,
        "detail": "The request is malformed.",
    },
    Unauthorized: {
        "title": "Unauthorized",
        "status": 401,
        "detail": "The request is unauthorized.",
    },
    Forbidden: {
        "title": "Forbidden",
        "status": 403,
        "detail": "The requester is not authorized to perform this action.",
    },
    NotFound: {
        "title": "Not Found",
        "status": 404,
        "detail": "The requested resource wasn't found.",
    },
    InternalServerError: {
        "title": "Internal Server Error",
        "status": 500,
        "detail": "An unexpected error occurred.",
    },
    RepositoryNotFound: {
        "title": "Not Found",
        "status": 404,
        "detail": "The requested `Repository` is not found.",
    },
    BuildNotFound: {
        "title": "Not Found",
        "status": 404,
        "detail": "The requested `Build` is not found.",
    },
    UserNotFound: {
        "title": "Not Found",
        "status": 404,
        "detail": "User not found.",
    },
    SubscriptionNotFound: {
        "title": "Not Found",
        "status": 404,
        "detail": "Subscription not found for this user.",
    },
    ValidationError: {
        "title": "Internal Server Error",
        "status": 500,
        "detail": "An unexpected error occurred while reading or writing data.",
    },
    GitCommandError: {
        "title": "Internal Server Error",
        "status": 500,
        "detail": ("An unexpected error occurred while cloning the Git repository."),
    },
    OSError: {
        "title": "Internal Server Error",
        "status": 500,
        "detail": "Input/Output operation failed while creating deployment file.",
    },
    DeletePodError: {
        "title": "Internal Server Error",
        "status": 500,
        "detail": (
            "Unable to delete the pod; check the deployment name and namespace."
        ),
    },
    CreatePodError: {
        "title": "Internal Server Error",
        "status": 500,
        "detail": "Unable to create pod.",
    },
    GitCloningError: {
        "title": "Internal Server Error",
        "status": 500,
        "detail": "The Git repository information is wrong.",
    },
    URLNotFound: {
        "title": "Bad Request",
        "status": 400,
        "detail": "Repository URL not found in the request.",
    },
    NameNotFound: {
        "title": "Bad Request",
        "status": 400,
        "detail": "User name not found in the request.",
    },
    UserNotVerified: {
        "title": "Forbidden",
        "status": 403,
        "detail": "User is not verified by the super user.",
    },
    BuildsDisabled: {
        "title": "Forbidden",
        "status": 403,
        "detail": "Builds are switched off: publish a prebuilt image instead.",
    },
    RegistrationDisabled: {
        "title": "Forbidden",
        "status": 403,
        "detail": "Registration is closed.",
    },
    InvalidImage: {
        "title": "Bad Request",
        "status": 400,
        "detail": "The request must name exactly one image, with a tag.",
    },
    TooManySubscriptions: {
        "title": "Forbidden",
        "status": 403,
        "detail": "The repository has reached its limit of subscriptions.",
    },
}
