"""Sync and async unit-of-work sessions."""

import builtins
import contextlib
from collections.abc import Iterable
from ipaddress import IPv4Address
from types import TracebackType
from typing import Any, Self, TypeVar, cast

import httpx

from eip_pydantic.client import AsyncEipClient, EipClient
from eip_pydantic.expressions import Condition, OrderByExpr, and_all
from eip_pydantic.models.base import SolidServerModel
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import FreeSubnet, Subnet



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
        if (obj_id := obj.id) is not None:
            self._cache[(type(obj), obj_id)] = obj

    def _get_cache(self, cls: type[T], pk: int) -> T | None:
        result = self._cache.get((cls, pk))
        return cast(T, result) if result is not None else None

    @staticmethod
    def _build_list_params(
        model_cls: type[SolidServerModel],
        where: str | Condition | Iterable[Condition] | None,
        orderby: str | OrderByExpr | None,
        select: str | None,
        offset: int | None,
        limit: int | None,
        tags: str | None,
        no_parent_class_param: bool,
    ) -> tuple[str, str, dict[str, str]]:
        effective_where: str | Condition | None
        if where is None or isinstance(where, (str, Condition)):
            effective_where = where
        else:
            effective_where = and_all(where)

        auto_tags: set[str] = set()
        if isinstance(effective_where, Condition):
            auto_tags.update(effective_where.required_tags)
        if isinstance(orderby, OrderByExpr):
            auto_tags.update(orderby.required_tags)
        if auto_tags:
            extra = "&".join(sorted(auto_tags))
            tags = f"{extra}&{tags}" if tags else extra

        kwargs: dict[str, Any] = {}
        if effective_where is not None:
            kwargs["where"] = str(effective_where)
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
        return model_cls.build_class_request("list", **kwargs)

    @staticmethod
    def _build_count_params(
        model_cls: type[SolidServerModel],
        where: str | Condition | Iterable[Condition] | None,
        tags: str | None,
        no_parent_class_param: bool,
    ) -> tuple[str, str, dict[str, str]]:
        effective_where: str | Condition | None
        if where is None or isinstance(where, (str, Condition)):
            effective_where = where
        else:
            effective_where = and_all(where)

        if isinstance(effective_where, Condition) and (auto_tags := effective_where.required_tags):
            extra = "&".join(sorted(auto_tags))
            tags = f"{extra}&{tags}" if tags else extra

        kwargs: dict[str, Any] = {}
        if effective_where is not None:
            kwargs["where"] = str(effective_where)
        if tags is not None:
            kwargs["tags"] = tags
        if no_parent_class_param:
            kwargs["no_parent_class_param"] = True
        return model_cls.build_class_request("count", **kwargs)

    def _absorb_list_result(self, cls: type[T], parsed: list[T]) -> list[T]:
        result: list[T] = []
        for obj in parsed:
            if obj.id is not None and (cached := self._get_cache(cls, obj.id)) is not None:
                result.append(cached)
            else:
                self._put_cache(obj)
                self.add(obj)
                result.append(obj)
        return result

    @staticmethod
    def _check_one(result: list[T], model_cls: type[T]) -> T:
        if len(result) != 1:
            raise ValueError(f"expected exactly 1 {model_cls.__name__}, got {len(result)}")
        return result[0]

    @staticmethod
    def _check_one_or_none(result: list[T], model_cls: type[T]) -> T | None:
        if len(result) > 1:
            raise ValueError(f"expected at most 1 {model_cls.__name__}, got {len(result)}")
        return result[0] if result else None


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
        where: str | Condition | Iterable[Condition] | None = None,
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
            where: Filter clause — a raw SQL-style string, a ``Condition``
                built with ``cls.c.<field> == value``, or an iterable of
                ``Condition`` objects that are AND-ed together.
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
        verb, path, params = self._build_list_params(
            cls, where, orderby, select, offset, limit, tags, no_parent_class_param,
        )
        raw = self._dispatch(verb, path, params)
        return self._absorb_list_result(cls, cast(list[T], cls.parse_response("list", raw)))

    def one(
        self,
        cls: type[T],
        *,
        where: str | Condition | Iterable[Condition] | None = None,
        orderby: str | OrderByExpr | None = None,
        select: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        tags: str | None = None,
        no_parent_class_param: bool = False,
    ) -> T:
        """Like ``list()``, but assert exactly one result and return it.

        Raises:
            ValueError: If the result set is not exactly one object.
        """
        return self._check_one(
            self.list(cls, where=where, orderby=orderby, select=select,
                      offset=offset, limit=limit, tags=tags,
                      no_parent_class_param=no_parent_class_param),
            cls,
        )

    def one_or_none(
        self,
        cls: type[T],
        *,
        where: str | Condition | Iterable[Condition] | None = None,
        orderby: str | OrderByExpr | None = None,
        select: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        tags: str | None = None,
        no_parent_class_param: bool = False,
    ) -> T | None:
        """Like ``list()``, but return the single result or ``None`` if empty.

        Raises:
            ValueError: If the result set contains more than one object.
        """
        return self._check_one_or_none(
            self.list(cls, where=where, orderby=orderby, select=select,
                      offset=offset, limit=limit, tags=tags,
                      no_parent_class_param=no_parent_class_param),
            cls,
        )

    def get(self, cls: type[T], id: int) -> T:
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
        if (cached := self._get_cache(cls, id)) is not None:
            return cached
        verb, path, params = cls.build_class_request("info", id=id)
        raw = self._dispatch(verb, path, params)
        obj = cast(T, cls.parse_response("info", raw))
        self._put_cache(obj)
        return obj

    def count(
        self,
        cls: type[T],
        *,
        where: str | Condition | Iterable[Condition] | None = None,
        tags: str | None = None,
        no_parent_class_param: bool = False,
    ) -> int:
        """Return the number of objects of ``cls`` matching the given filter.

        Args:
            cls: The model class to count (e.g. ``Space``, ``Subnet``).
            where: Filter clause — a raw SQL-style string, a ``Condition``
                built with ``cls.c.<field> == value``, or an iterable of
                ``Condition`` objects that are AND-ed together.  Tagged
                class-parameter conditions have their required TAGS injected
                automatically.
            tags: Explicit TAGS expression.  Auto-collected tags from ``where``
                are merged in automatically.
            no_parent_class_param: Exclude parent class parameters from output.

        Returns:
            Integer count of matching objects.

        Raises:
            TypeError: If ``cls`` has no ``_count_path`` configured.
        """
        verb, path, params = self._build_count_params(cls, where, tags, no_parent_class_param)
        raw = self._dispatch(verb, path, params)
        return cast(int, cls.parse_response("count", raw))

    # ---- RPC ----------------------------------------------------------------

    def find_free_subnet(
        self,
        *,
        prefix: int | None = None,
        size: int | None = None,
        space: int | Space | None = None,
        max_find: int | None = None,
        begin_addr: IPv4Address | str | None = None,
        end_addr: IPv4Address | str | None = None,
        subnet: int | Subnet | None = None,
        use_searched_path: bool | None = None,
        where: str | Condition | None = None,
    ) -> builtins.list[FreeSubnet]:
        """Return candidate free subnets of the requested size via ``ip_find_free_subnet``.

        Exactly one of ``prefix`` or ``size`` must be supplied.  Results are
        ordered by ``cost`` ascending (lowest = least fragmentation).

        Args:
            prefix: CIDR prefix length (1 to 32) of the desired subnet.
            size: Number of IP addresses the desired subnet must contain.
            space: Restrict search to this space — an integer ID or a
                :class:`Space` instance.
            max_find: Maximum number of candidates to return (default 10).
            begin_addr: Start of the address range to search within.
            end_addr: End of the address range to search within.
            subnet: Restrict search to within this parent block — an integer ID
                or a :class:`Subnet` instance.
            use_searched_path: If ``True``, also recurse into non-terminal
                subnets within the given block (``use_searched_path=1``).
            where: SQL-style filter applied server-side to the result set.

        Returns:
            List of :class:`FreeSubnet` rows, each describing one available slot.

        Raises:
            ValueError: If neither ``prefix`` nor ``size`` is provided.
        """
        verb, path, params = FreeSubnet.build_class_request(
            "find_free",
            prefix=prefix, size=size, space=space, max_find=max_find,
            begin_addr=begin_addr, end_addr=end_addr, subnet=subnet,
            use_searched_path=use_searched_path, where=where,
        )
        raw = self._dispatch(verb, path, params)
        return FreeSubnet.parse_response("find_free", raw)

    # ---- Write --------------------------------------------------------------

    def delete(self, obj: SolidServerModel) -> None:
        """Delete the object on the server immediately.

        Issues the DELETE request, removes the object from the identity cache,
        and removes it from the tracked list if present.

        Args:
            obj: The model instance to delete.  Must have a non-``None`` id.
        """
        verb, path, params = obj.build_request("delete")
        self._dispatch(verb, path, params)
        if (obj_id := obj.id) is not None:
            self._cache.pop((type(obj), obj_id), None)
        with contextlib.suppress(ValueError):
            self._tracked.remove(obj)

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
            case "OPTIONS":
                return self._client.options(path, **params)
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
        where: str | Condition | Iterable[Condition] | None = None,
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
            where: Filter clause — a raw SQL-style string, a ``Condition``
                built with ``cls.c.<field> == value``, or an iterable of
                ``Condition`` objects that are AND-ed together.
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
        verb, path, params = self._build_list_params(
            cls, where, orderby, select, offset, limit, tags, no_parent_class_param,
        )
        raw = await self._dispatch(verb, path, params)
        return self._absorb_list_result(cls, cast(list[T], cls.parse_response("list", raw)))

    async def one(
        self,
        cls: type[T],
        *,
        where: str | Condition | Iterable[Condition] | None = None,
        orderby: str | OrderByExpr | None = None,
        select: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        tags: str | None = None,
        no_parent_class_param: bool = False,
    ) -> T:
        """Like ``list()``, but assert exactly one result and return it.

        Raises:
            ValueError: If the result set is not exactly one object.
        """
        return self._check_one(
            await self.list(cls, where=where, orderby=orderby, select=select,
                            offset=offset, limit=limit, tags=tags,
                            no_parent_class_param=no_parent_class_param),
            cls,
        )

    async def one_or_none(
        self,
        cls: type[T],
        *,
        where: str | Condition | Iterable[Condition] | None = None,
        orderby: str | OrderByExpr | None = None,
        select: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        tags: str | None = None,
        no_parent_class_param: bool = False,
    ) -> T | None:
        """Like ``list()``, but return the single result or ``None`` if empty.

        Raises:
            ValueError: If the result set contains more than one object.
        """
        return self._check_one_or_none(
            await self.list(cls, where=where, orderby=orderby, select=select,
                            offset=offset, limit=limit, tags=tags,
                            no_parent_class_param=no_parent_class_param),
            cls,
        )

    async def get(self, cls: type[T], id: int) -> T:
        """Return the object for ``(cls, id)``, fetching from the API at most once.

        Args:
            cls: The model class to fetch.
            id: The primary-key integer.

        Returns:
            The cached or freshly fetched instance of ``cls``.

        Raises:
            TypeError: If ``cls`` has no ``_info_path`` configured.
        """
        if (cached := self._get_cache(cls, id)) is not None:
            return cached
        verb, path, params = cls.build_class_request("info", id=id)
        raw = await self._dispatch(verb, path, params)
        obj = cast(T, cls.parse_response("info", raw))
        self._put_cache(obj)
        return obj

    async def count(
        self,
        cls: type[T],
        *,
        where: str | Condition | Iterable[Condition] | None = None,
        tags: str | None = None,
        no_parent_class_param: bool = False,
    ) -> int:
        """Return the number of objects of ``cls`` matching the given filter.

        Args:
            cls: The model class to count (e.g. ``Space``, ``Subnet``).
            where: Filter clause — a raw SQL-style string, a ``Condition``
                built with ``cls.c.<field> == value``, or an iterable of
                ``Condition`` objects that are AND-ed together.  Tagged
                class-parameter conditions have their required TAGS injected
                automatically.
            tags: Explicit TAGS expression.  Auto-collected tags from ``where``
                are merged in automatically.
            no_parent_class_param: Exclude parent class parameters from output.

        Returns:
            Integer count of matching objects.

        Raises:
            TypeError: If ``cls`` has no ``_count_path`` configured.
        """
        verb, path, params = self._build_count_params(cls, where, tags, no_parent_class_param)
        raw = await self._dispatch(verb, path, params)
        return cast(int, cls.parse_response("count", raw))

    # ---- RPC ----------------------------------------------------------------

    async def find_free_subnet(
        self,
        *,
        prefix: int | None = None,
        size: int | None = None,
        space: int | Space | None = None,
        max_find: int | None = None,
        begin_addr: IPv4Address | str | None = None,
        end_addr: IPv4Address | str | None = None,
        subnet: int | Subnet | None = None,
        use_searched_path: bool | None = None,
        where: str | Condition | None = None,
    ) -> builtins.list[FreeSubnet]:
        """Return candidate free subnets of the requested size via ``ip_find_free_subnet``.

        Exactly one of ``prefix`` or ``size`` must be supplied.  Results are
        ordered by ``cost`` ascending (lowest = least fragmentation).

        Args:
            prefix: CIDR prefix length (1 to 32) of the desired subnet.
            size: Number of IP addresses the desired subnet must contain.
            space: Restrict search to this space — an integer ID or a
                :class:`Space` instance.
            max_find: Maximum number of candidates to return (default 10).
            begin_addr: Start of the address range to search within.
            end_addr: End of the address range to search within.
            subnet: Restrict search to within this parent block — an integer ID
                or a :class:`Subnet` instance.
            use_searched_path: If ``True``, also recurse into non-terminal
                subnets within the given block (``use_searched_path=1``).
            where: SQL-style filter applied server-side to the result set.

        Returns:
            List of :class:`FreeSubnet` rows, each describing one available slot.

        Raises:
            ValueError: If neither ``prefix`` nor ``size`` is provided.
        """
        verb, path, params = FreeSubnet.build_class_request(
            "find_free",
            prefix=prefix, size=size, space=space, max_find=max_find,
            begin_addr=begin_addr, end_addr=end_addr, subnet=subnet,
            use_searched_path=use_searched_path, where=where,
        )
        raw = await self._dispatch(verb, path, params)
        return FreeSubnet.parse_response("find_free", raw)

    # ---- Write --------------------------------------------------------------

    async def delete(self, obj: SolidServerModel) -> None:
        """Delete the object on the server immediately.

        Args:
            obj: The model instance to delete.
        """
        verb, path, params = obj.build_request("delete")
        await self._dispatch(verb, path, params)
        if (obj_id := obj.id) is not None:
            self._cache.pop((type(obj), obj_id), None)
        with contextlib.suppress(ValueError):
            self._tracked.remove(obj)

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
            case "OPTIONS":
                return await self._client.options(path, **params)
            case _:
                raise ValueError(f"Unsupported HTTP verb: {verb!r}")
