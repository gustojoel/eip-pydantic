"""Sync and async unit-of-work sessions."""

from types import TracebackType
from typing import Any, Self, TypeVar, cast

import httpx

from eip_pydantic.client import AsyncEipClient, EipClient
from eip_pydantic.expressions import Condition, OrderByExpr
from eip_pydantic.models.base import SolidServerModel

T = TypeVar("T", bound=SolidServerModel)

_Cache = dict[tuple[type[SolidServerModel], int], SolidServerModel]
_DEFAULT_TIMEOUT = httpx.Timeout(30.0)


class BaseSession:
    """Shared state and non-I/O methods for sync and async sessions.

    Holds the tracked-object list and the identity cache.  Subclasses add
    the HTTP transport and implement all I/O methods (``list``, ``get``,
    ``delete``, ``flush``) as sync or async.

    Attributes:
        _tracked: Objects registered via ``add()`` or ``new()`` that will be
            written on ``flush()``.
        _cache: Identity map keyed by ``(type, pk)`` so that repeated
            ``get()`` calls for the same object return the same instance.
    """

    def __init__(self) -> None:
        self._tracked: list[SolidServerModel] = []
        self._cache: _Cache = {}

    def add(self, obj: SolidServerModel) -> None:
        """Track an existing object so that dirty fields are written on ``flush()``.

        Idempotent — adding the same object twice has no effect.

        Args:
            obj: A model instance loaded from the API whose mutable fields
                may be changed before the session exits.
        """
        if obj not in self._tracked:
            self._tracked.append(obj)

    def new(self, obj: SolidServerModel) -> None:
        """Register a new (unsaved) object for creation on ``flush()``.

        Calls ``obj.mark_new()`` and appends to the tracked list.

        Args:
            obj: A freshly constructed model instance that has not yet been
                saved to the server.
        """
        obj.mark_new()
        self._tracked.append(obj)

    def _put_cache(self, obj: SolidServerModel) -> None:
        if (pk := obj.pk) is not None:
            self._cache[(type(obj), pk)] = obj

    def _get_cache(self, cls: type[T], pk: int) -> T | None:
        result = self._cache.get((cls, pk))
        return cast(T, result) if result is not None else None


class Session(BaseSession):
    """Synchronous unit-of-work session.

    The primary entry point for all SolidServer API interactions.  Creates
    and owns an ``EipClient`` for the lifetime of the session.  Objects
    loaded via ``list()`` are automatically tracked so that any mutations
    are written on ``flush()``.

    Typical usage::

        with Session("solidserver.example.com", "admin", "secret") as s:
            subnets = s.list(Subnet, where="site_id='7'")
            space = s.get(Space, subnets[0].site_id)   # cached after first call
            subnets[0].subnet_name = "renamed"
        # flush() called on __exit__ — one PUT

    Attributes:
        _client: The underlying ``EipClient`` used for all HTTP calls.
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
        """Create a synchronous session.

        Args:
            host: SolidServer hostname or IP address (no scheme).
            username: API username for HTTP Basic Auth.
            password: API password for HTTP Basic Auth.
            timeout: httpx timeout applied to every request.
            verify: TLS certificate verification — ``False`` to skip, or a
                path to a custom CA bundle.
        """
        super().__init__()
        self._client = EipClient(host, username, password, timeout=timeout, verify=verify)

    # ---- Read ---------------------------------------------------------------

    def list(
        self,
        cls: type[T],
        *,
        where: str | Condition | None = None,
        orderby: str | OrderByExpr | None = None,
        select: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        tags: str | None = None,
        no_parent_class_param: bool = False,
    ) -> list[T]:
        """List objects of ``cls`` from the API and track them for writes.

        All returned objects are added to the tracked list and the identity
        cache.  Because objects are freshly loaded they are clean — only
        mutations made after this call will be written on ``flush()``.

        Args:
            cls: The model class to list (e.g. ``Space``, ``Subnet``).
            where: Filter clause — a raw SQL-style string or a ``Condition``
                built with ``cls.c.<field> == value``.
            orderby: Sort clause — a raw string or an ``OrderByExpr`` built
                with ``cls.c.<field>.asc()`` / ``.desc()``.
            select: Comma-separated list of columns to return.
            offset: Number of rows to skip.
            limit: Maximum number of rows to return.
            tags: Explicit TAGS expression, e.g. ``"site.my_param"``.  When
                ``where`` or ``orderby`` reference tagged class parameters the
                required TAGS are injected automatically; this argument adds
                additional tags on top.
            no_parent_class_param: Exclude parent class parameters from output.

        Returns:
            Validated model instances in the order returned by the API.
        """
        auto_tags: set[str] = set()
        if isinstance(where, Condition):
            auto_tags.update(where.required_tags)
        if isinstance(orderby, OrderByExpr):
            auto_tags.update(orderby.required_tags)
        if auto_tags:
            extra = "&".join(sorted(auto_tags))
            tags = f"{extra}&{tags}" if tags else extra

        kwargs: dict[str, Any] = {}
        if where is not None:
            kwargs["where"] = str(where)
        if orderby is not None:
            kwargs["orderby"] = str(orderby)
        if select is not None:
            kwargs["select"] = select
        if offset is not None:
            kwargs["offset"] = offset
        if limit is not None:
            kwargs["limit"] = limit
        if tags is not None:
            kwargs["tags"] = tags
        if no_parent_class_param:
            kwargs["no_parent_class_param"] = True
        verb, path, params = cls.build_class_request("list", **kwargs)
        raw = self._dispatch(verb, path, params)
        result = cast(list[T], cls.parse_response("list", raw))
        for obj in result:
            self._tracked.append(obj)
            self._put_cache(obj)
        return result

    def get(self, cls: type[T], pk: int) -> T:
        """Return the object for ``(cls, pk)``, fetching from the API at most once.

        Checks the identity cache first.  On a cache miss, calls the
        appropriate ``*_info`` endpoint and caches the result.  The fetched
        object is added to the cache but **not** to the tracked list — call
        ``session.add(obj)`` explicitly if you intend to mutate it.

        Args:
            cls: The model class to fetch (e.g. ``Space``, ``Subnet``).
            pk: The primary-key integer for the object.

        Returns:
            The cached or freshly fetched instance of ``cls``.

        Raises:
            TypeError: If ``cls`` has no ``_info_path`` configured.
        """
        if (cached := self._get_cache(cls, pk)) is not None:
            return cached
        verb, path, params = cls.build_class_request("info", pk=pk)
        raw = self._dispatch(verb, path, params)
        obj = cast(T, cls.parse_response("info", raw))
        self._put_cache(obj)
        return obj

    # ---- Write --------------------------------------------------------------

    def delete(self, obj: SolidServerModel) -> None:
        """Delete the object on the server immediately.

        Issues the DELETE request, removes the object from the identity cache,
        and removes it from the tracked list if present.

        Args:
            obj: The model instance to delete.  Must have a non-``None`` PK.
        """
        verb, path, params = obj.build_request("delete")
        self._dispatch(verb, path, params)
        if (pk := obj.pk) is not None:
            self._cache.pop((type(obj), pk), None)
        try:
            self._tracked.remove(obj)
        except ValueError:
            pass

    def flush(self) -> None:
        """Create or update all tracked objects that are new or dirty.

        Iterates the tracked list in insertion order.  For each object:

        * If ``is_new`` is ``True`` → sends a POST (``create``).
        * If ``is_dirty`` is ``True`` → sends a PUT (``update``).
        * Otherwise → no-op.

        After each successful write the object's state is reset via
        ``apply_response()``.
        """
        for obj in self._tracked:
            if obj.is_new:
                verb, path, params = obj.build_request("create")
                raw = self._dispatch(verb, path, params)
                obj.apply_response("create", raw)
                self._put_cache(obj)
            elif obj.is_dirty:
                verb, path, params = obj.build_request("update")
                raw = self._dispatch(verb, path, params)
                obj.apply_response("update", raw)

    # ---- Context manager ----------------------------------------------------

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                self.flush()
        finally:
            self._client.close()

    # ---- Internal -----------------------------------------------------------

    def _dispatch(self, verb: str, path: str, params: dict[str, str]) -> Any:
        match verb:
            case "GET":
                return self._client.get(path, **params)
            case "POST":
                return self._client.post(path, **params)
            case "PUT":
                return self._client.put(path, **params)
            case "DELETE":
                return self._client.delete(path, **params)
            case _:
                raise ValueError(f"Unsupported HTTP verb: {verb!r}")


class AsyncSession(BaseSession):
    """Asynchronous unit-of-work session.

    Identical contract to ``Session`` but all I/O methods are ``async``::

        async with AsyncSession("solidserver.example.com", "admin", "secret") as s:
            subnets = await s.list(Subnet, where="site_id='7'")
            space = await s.get(Space, subnets[0].site_id)
            subnets[0].subnet_name = "renamed"

    Attributes:
        _client: The underlying ``AsyncEipClient`` used for all HTTP calls.
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
        """Create an asynchronous session.

        Args:
            host: SolidServer hostname or IP address (no scheme).
            username: API username for HTTP Basic Auth.
            password: API password for HTTP Basic Auth.
            timeout: httpx timeout applied to every request.
            verify: TLS certificate verification — ``False`` to skip, or a
                path to a custom CA bundle.
        """
        super().__init__()
        self._client = AsyncEipClient(host, username, password, timeout=timeout, verify=verify)

    # ---- Read ---------------------------------------------------------------

    async def list(
        self,
        cls: type[T],
        *,
        where: str | Condition | None = None,
        orderby: str | OrderByExpr | None = None,
        select: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        tags: str | None = None,
        no_parent_class_param: bool = False,
    ) -> list[T]:
        """List objects of ``cls`` from the API and track them for writes.

        Args:
            cls: The model class to list (e.g. ``Space``, ``Subnet``).
            where: Filter clause — a raw SQL-style string or a ``Condition``
                built with ``cls.c.<field> == value``.
            orderby: Sort clause — a raw string or an ``OrderByExpr`` built
                with ``cls.c.<field>.asc()`` / ``.desc()``.
            select: Comma-separated column list.
            offset: Rows to skip.
            limit: Maximum rows to return.
            tags: Explicit TAGS expression.  Auto-collected tags from
                ``where`` / ``orderby`` expressions are merged in automatically.
            no_parent_class_param: Exclude parent class parameters.

        Returns:
            Validated model instances in the order returned by the API.
        """
        auto_tags: set[str] = set()
        if isinstance(where, Condition):
            auto_tags.update(where.required_tags)
        if isinstance(orderby, OrderByExpr):
            auto_tags.update(orderby.required_tags)
        if auto_tags:
            extra = "&".join(sorted(auto_tags))
            tags = f"{extra}&{tags}" if tags else extra

        kwargs: dict[str, Any] = {}
        if where is not None:
            kwargs["where"] = str(where)
        if orderby is not None:
            kwargs["orderby"] = str(orderby)
        if select is not None:
            kwargs["select"] = select
        if offset is not None:
            kwargs["offset"] = offset
        if limit is not None:
            kwargs["limit"] = limit
        if tags is not None:
            kwargs["tags"] = tags
        if no_parent_class_param:
            kwargs["no_parent_class_param"] = True
        verb, path, params = cls.build_class_request("list", **kwargs)
        raw = await self._dispatch(verb, path, params)
        result = cast(list[T], cls.parse_response("list", raw))
        for obj in result:
            self._tracked.append(obj)
            self._put_cache(obj)
        return result

    async def get(self, cls: type[T], pk: int) -> T:
        """Return the object for ``(cls, pk)``, fetching from the API at most once.

        Args:
            cls: The model class to fetch.
            pk: The primary-key integer.

        Returns:
            The cached or freshly fetched instance of ``cls``.

        Raises:
            TypeError: If ``cls`` has no ``_info_path`` configured.
        """
        if (cached := self._get_cache(cls, pk)) is not None:
            return cached
        verb, path, params = cls.build_class_request("info", pk=pk)
        raw = await self._dispatch(verb, path, params)
        obj = cast(T, cls.parse_response("info", raw))
        self._put_cache(obj)
        return obj

    # ---- Write --------------------------------------------------------------

    async def delete(self, obj: SolidServerModel) -> None:
        """Delete the object on the server immediately.

        Args:
            obj: The model instance to delete.
        """
        verb, path, params = obj.build_request("delete")
        await self._dispatch(verb, path, params)
        if (pk := obj.pk) is not None:
            self._cache.pop((type(obj), pk), None)
        try:
            self._tracked.remove(obj)
        except ValueError:
            pass

    async def flush(self) -> None:
        """Create or update all tracked objects that are new or dirty."""
        for obj in self._tracked:
            if obj.is_new:
                verb, path, params = obj.build_request("create")
                raw = await self._dispatch(verb, path, params)
                obj.apply_response("create", raw)
                self._put_cache(obj)
            elif obj.is_dirty:
                verb, path, params = obj.build_request("update")
                raw = await self._dispatch(verb, path, params)
                obj.apply_response("update", raw)

    # ---- Context manager ----------------------------------------------------

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                await self.flush()
        finally:
            await self._client.aclose()

    # ---- Internal -----------------------------------------------------------

    async def _dispatch(self, verb: str, path: str, params: dict[str, str]) -> Any:
        match verb:
            case "GET":
                return await self._client.get(path, **params)
            case "POST":
                return await self._client.post(path, **params)
            case "PUT":
                return await self._client.put(path, **params)
            case "DELETE":
                return await self._client.delete(path, **params)
            case _:
                raise ValueError(f"Unsupported HTTP verb: {verb!r}")
