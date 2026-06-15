"""Sync and async EfficientIP SolidServer clients."""

from types import TracebackType
from typing import Any, Self

import httpx

from eip_pydantic.exceptions import ApiError, AuthenticationError, NotFoundError



_DEFAULT_TIMEOUT = httpx.Timeout(30.0)


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

    @classmethod
    def _httpx_kwargs(
        cls,
        host: str,
        username: str,
        password: str,
        *,
        timeout: httpx.Timeout,
        verify: bool | str,
    ) -> dict[str, Any]:
        return {
            "base_url": f"https://{host}/",
            "auth": httpx.BasicAuth(username, password),
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
        username: str,
        password: str,
        *,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        verify: bool | str = True,
    ) -> None:
        """Create a synchronous SolidServer client.

        Args:
            host: SolidServer hostname or IP address (no scheme, no trailing slash).
            username: API username for HTTP Basic Auth.
            password: API password for HTTP Basic Auth.
            timeout: httpx timeout configuration applied to every request.
            verify: TLS certificate verification.  Pass ``False`` to skip
                verification or a path string to a custom CA bundle.
        """
        self._http = httpx.Client(**self._httpx_kwargs(host, username, password, timeout=timeout, verify=verify))

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
        return response.json()

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
        return response.json()

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
        return response.json()

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
        username: str,
        password: str,
        *,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        verify: bool | str = True,
    ) -> None:
        """Create an asynchronous SolidServer client.

        Args:
            host: SolidServer hostname or IP address (no scheme, no trailing slash).
            username: API username for HTTP Basic Auth.
            password: API password for HTTP Basic Auth.
            timeout: httpx timeout configuration applied to every request.
            verify: TLS certificate verification.  Pass ``False`` to skip
                verification or a path string to a custom CA bundle.
        """
        self._http = httpx.AsyncClient(**self._httpx_kwargs(host, username, password, timeout=timeout, verify=verify))

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
        return response.json()

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
        return response.json()

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
        return response.json()

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
