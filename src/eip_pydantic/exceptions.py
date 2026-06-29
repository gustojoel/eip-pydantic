"""Exception hierarchy for eip-pydantic."""



class SolidServerError(Exception):
    """Base exception for all eip-pydantic errors."""


class ApiError(SolidServerError):
    """Raised when the SolidServer API returns an error HTTP response.

    Attributes:
        status_code: The HTTP status code returned by the server.
        message: The error message from the response body or reason phrase.
    """

    def __init__(self, status_code: int, message: str) -> None:
        """Create an ApiError.

        Args:
            status_code: HTTP status code (e.g. 500).
            message: Human-readable error detail from the response.
        """
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class AuthenticationError(ApiError):
    """Raised on 401 Unauthorized responses."""


class NotFoundError(ApiError):
    """Raised on 404 Not Found responses."""


class InternalError(SolidServerError):
    """Raised when an internal programming invariant is violated.

    This exception represents a bug in the calling code, not an API or network
    error — e.g. calling an operation on a model class that does not support it.
    """


class InvalidatedError(SolidServerError):
    """Raised when a mutating or I/O method is called on an invalidated instance.

    Instances are invalidated by :meth:`BaseSession.reset` after a failed flush,
    at which point their state is unknown (partially written, partially not).
    Field values remain readable for post-mortem inspection; any attempt to
    mutate the object or build an HTTP request raises this exception.

    Attributes:
        obj: The invalidated model instance that triggered the error.
    """

    def __init__(self, obj: object) -> None:
        self.obj = obj
        super().__init__(
            f"{type(obj).__name__} instance has been invalidated by session.reset()"
        )
