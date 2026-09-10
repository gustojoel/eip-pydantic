"""Sync and async EfficientIP SolidServer clients."""

import hashlib
import time
from collections.abc import Generator
from types import TracebackType
from typing import Any, Self

import httpx

from eip_pydantic.exceptions import ApiError, AuthenticationError, NotFoundError



_DEFAULT_TIMEOUT = httpx.Timeout(30.0)


class ApiKeyAuth(httpx.Auth):
    """httpx auth flow for SolidServer's API token authentication scheme.

    Computes a fresh ``X-SDS-TS`` / ``Authorization: SDS <id>:<sig>`` pair for
    every request, since the signature is bound to the request's method, full
    URL, and current epoch timestamp. See "Calling SOLIDserver Services" (API
    token authentication) in the SolidServer REST API reference.

    Attributes:
        token_id: The API token's public identifier.
        token_secret: The API token's secret, used to compute the signature.
    """

    def __init__(self, token_id: str, token_secret: str) -> None:
        """Create an API key auth flow.

        Args:
            token_id: The API token's public identifier.
            token_secret: The API token's secret.
        """
        self.token_id = token_id
        self.token_secret = token_secret

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        ts = str(int(time.time()))
        string_to_sign = f"{self.token_secret}\n{ts}\n{request.method}\n{request.url}"
        signature = hashlib.sha3_256(string_to_sign.encode()).hexdigest()
        request.headers["X-SDS-TS"] = ts
        request.headers["Authorization"] = f"SDS {self.token_id}:{signature}"
        yield request


class _BaseEipClient:
    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        message = response.text or response.reason_phrase
        if response.status_code == 401:
            raise AuthenticationError(response.status_code, message)
        if response.status_code == 404:
            raise NotFoundError(response.status_code, message)
        raise ApiError(response.status_code, message)

    @staticmethod
    def _build_auth(
        username: str | None,
        password: str | None,
        token_id: str | None,
        token_secret: str | None,
    ) -> httpx.Auth:
        has_basic = username is not None and password is not None
        has_token = token_id is not None and token_secret is not None
        if has_basic and has_token:
            raise ValueError(
                "Specify either username/password or token_id/token_secret, not both",
            )
        if has_token:
            return ApiKeyAuth(token_id, token_secret)  # type: ignore[arg-type]
        if has_basic:
            return httpx.BasicAuth(username, password)  # type: ignore[arg-type]
        raise ValueError("Must specify either username/password or token_id/token_secret")

    @classmethod
    def _httpx_kwargs(
        cls,
        host: str,
        username: str | None,
        password: str | None,
        *,
        token_id: str | None,
        token_secret: str | None,
        timeout: httpx.Timeout,
        verify: bool | str,
    ) -> dict[str, Any]:
        return {
            "base_url": f"https://{host}/",
            "auth": cls._build_auth(username, password, token_id, token_secret),
            "timeout": timeout,
            "verify": verify,
            "headers": {"Accept": "application/json"},
        }


class EipClient(_BaseEipClient):
    """Synchronous HTTP transport for the EfficientIP SolidServer REST API.

    Wraps an ``httpx.Client`` and provides low-level ``get`` / ``post`` /
    ``put`` / ``delete`` methods.  Use ``Session`` for the typed, high-level
    API instead of this class directly.
    """

    def __init__(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
        *,
        token_id: str | None = None,
        token_secret: str | None = None,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        verify: bool | str = True,
    ) -> None:
        """Create a synchronous SolidServer client.

        Authenticate with either ``username``/``password`` (HTTP Basic Auth)
        or ``token_id``/``token_secret`` (SolidServer API token auth) — exactly
        one pair must be supplied.

        Args:
            host: SolidServer hostname or IP address (no scheme, no trailing slash).
            username: API username for HTTP Basic Auth.
            password: API password for HTTP Basic Auth.
            token_id: API token's public identifier, for API token auth.
            token_secret: API token's secret, for API token auth.
            timeout: httpx timeout configuration applied to every request.
            verify: TLS certificate verification.  Pass ``False`` to skip
                verification or a path string to a custom CA bundle.

        Raises:
            ValueError: If neither or both of the two credential pairs are supplied.
        """
        self._http = httpx.Client(
            **self._httpx_kwargs(
                host, username, password,
                token_id=token_id, token_secret=token_secret,
                timeout=timeout, verify=verify,
            ),
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def get(self, path: str, **params: Any) -> Any:
        """Send a GET request and return the parsed JSON response.

        Args:
            path: API path relative to the base URL, e.g. ``"rest/ip_site_list"``.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON — typically a ``list[dict]`` for ``*_list`` / ``*_info``
            endpoints or a ``dict`` for ``*_add`` / ``*_delete`` responses.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = self._http.get(path, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []

    def post(self, path: str, body: Any = None, **params: Any) -> Any:
        """Send a POST request and return the parsed JSON response.

        Args:
            path: API path relative to the base URL, e.g. ``"rest/ip_subnet_add"``.
            body: Optional JSON body.  Most SolidServer writes use query params
                instead, so this is rarely needed.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON response, typically containing ``ret_oid`` and ``errno``.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = self._http.post(path, json=body, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []

    def put(self, path: str, body: Any = None, **params: Any) -> Any:
        """Send a PUT request and return the parsed JSON response.

        Args:
            path: API path relative to the base URL, e.g. ``"rest/ip_subnet_add"``.
            body: Optional JSON body.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON response, typically containing ``ret_oid`` and ``errno``.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = self._http.put(path, json=body, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []

    def delete(self, path: str, **params: Any) -> Any:
        """Send a DELETE request and return the parsed JSON response.

        Args:
            path: API path relative to the base URL.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON response.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = self._http.delete(path, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []

    def options(self, path: str, **params: Any) -> Any:
        """Send an OPTIONS request and return the parsed JSON response.

        Used for RPC-style services under ``rpc/`` (e.g. ``ip_find_free_subnet``).

        Args:
            path: API path relative to the base URL, e.g. ``"rpc/ip_find_free_subnet"``.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON — typically a ``list[dict]`` of result rows.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = self._http.options(path, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []


class AsyncEipClient(_BaseEipClient):
    """Asynchronous HTTP transport for the EfficientIP SolidServer REST API.

    Identical contract to ``EipClient`` but all I/O is ``async``.  Use
    ``AsyncSession`` for the typed, high-level API instead.
    """

    def __init__(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
        *,
        token_id: str | None = None,
        token_secret: str | None = None,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        verify: bool | str = True,
    ) -> None:
        """Create an asynchronous SolidServer client.

        Authenticate with either ``username``/``password`` (HTTP Basic Auth)
        or ``token_id``/``token_secret`` (SolidServer API token auth) — exactly
        one pair must be supplied.

        Args:
            host: SolidServer hostname or IP address (no scheme, no trailing slash).
            username: API username for HTTP Basic Auth.
            password: API password for HTTP Basic Auth.
            token_id: API token's public identifier, for API token auth.
            token_secret: API token's secret, for API token auth.
            timeout: httpx timeout configuration applied to every request.
            verify: TLS certificate verification.  Pass ``False`` to skip
                verification or a path string to a custom CA bundle.

        Raises:
            ValueError: If neither or both of the two credential pairs are supplied.
        """
        self._http = httpx.AsyncClient(
            **self._httpx_kwargs(
                host, username, password,
                token_id=token_id, token_secret=token_secret,
                timeout=timeout, verify=verify,
            ),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying async HTTP connection pool."""
        await self._http.aclose()

    async def get(self, path: str, **params: Any) -> Any:
        """Send a GET request and return the parsed JSON response.

        Args:
            path: API path relative to the base URL.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON response.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = await self._http.get(path, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []

    async def post(self, path: str, body: Any = None, **params: Any) -> Any:
        """Send a POST request and return the parsed JSON response.

        Args:
            path: API path relative to the base URL.
            body: Optional JSON body.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON response.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = await self._http.post(path, json=body, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []

    async def put(self, path: str, body: Any = None, **params: Any) -> Any:
        """Send a PUT request and return the parsed JSON response.

        Args:
            path: API path relative to the base URL.
            body: Optional JSON body.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON response.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = await self._http.put(path, json=body, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []

    async def delete(self, path: str, **params: Any) -> Any:
        """Send a DELETE request and return the parsed JSON response.

        Args:
            path: API path relative to the base URL.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON response.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = await self._http.delete(path, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []

    async def options(self, path: str, **params: Any) -> Any:
        """Send an OPTIONS request and return the parsed JSON response.

        Used for RPC-style services under ``rpc/`` (e.g. ``ip_find_free_subnet``).

        Args:
            path: API path relative to the base URL, e.g. ``"rpc/ip_find_free_subnet"``.
            **params: Query-string parameters forwarded to the API.

        Returns:
            Parsed JSON — typically a ``list[dict]`` of result rows.

        Raises:
            AuthenticationError: On 401 responses.
            NotFoundError: On 404 responses.
            ApiError: On other non-2xx responses.
        """
        response = await self._http.options(path, params=params or None)
        self._raise_for_status(response)
        return response.json() if response.content else []
