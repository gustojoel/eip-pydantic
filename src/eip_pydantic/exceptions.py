from __future__ import annotations


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
