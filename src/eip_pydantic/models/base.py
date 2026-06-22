"""Base model, dirty-tracking machinery, and shared write-layer helpers."""
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from enum import IntEnum
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, NamedTuple, cast

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.expressions import ColumnCollection, ColumnExpr, Condition



_EMPTY_PATHS: MappingProxyType[str, str] = MappingProxyType({})
_MISSING = object()


class SolidServerConfig(NamedTuple):
    """Unit-of-work configuration for a SolidServer model class.

    Set once per model as ``solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(...)``.
    Mirrors the ``model_config = ConfigDict(...)`` pattern used by Pydantic itself.

    Attributes:
        pk_field: Name of the primary-key field (e.g. ``"site_id"``).
        class_param_prefix: API prefix for class-parameter blobs (e.g. ``"site"``).
        tags_prefix: TAGS object-type name for the expression builder (e.g. ``"network"``).
        create_fields: Fields the user may supply to ``Session.create()``; ``None`` = unrestricted.
        paths: Mapping of operation name → REST/RPC path.  Standard keys: ``"list"``,
            ``"info"``, ``"count"``, ``"add"``, ``"delete"``.  Non-standard keys (e.g.
            ``"find_free"``) are used by model-specific ``build_class_request`` overrides.
        parent_fields: Mapping of parent model ``pk_field`` name → child field name.
            Drives the ``parent`` argument of ``Session.create()`` — when a parent object is
            supplied, its PK is injected into the child's field named here.
    """
    pk_field: str = ""
    class_param_prefix: str | None = None
    tags_prefix: str = ""
    create_fields: frozenset[str] | None = None
    paths: MappingProxyType[str, str] = _EMPTY_PATHS
    parent_fields: MappingProxyType[str, str] = _EMPTY_PATHS


def _make_notifier(dirty: set[str], field_name: str) -> Callable[[], None]:
    """Return a zero-arg callable that adds field_name to dirty when called."""
    def _notify() -> None:
        dirty.add(field_name)
    return _notify


class _CDescriptor:
    """Non-data descriptor returning a ``ColumnCollection`` bound to the accessing class."""

    def __get__(self, obj: object, objtype: "type[SolidServerModel] | None" = None) -> ColumnCollection:
        if obj is not None:
            raise AttributeError("c must be accessed on the class, not an instance")  # pragma: no cover
        if objtype is None:
            raise AttributeError("objtype must be set")  # pragma: no cover
        return ColumnCollection(objtype)


class RowEnabled(IntEnum):
    """Enabled/disabled state of any SolidServer object.

    Attributes:
        DELETED: Object is soft-deleted and ignored by most queries.
        ENABLED: Object is active.
        UNMANAGED: Object exists but is excluded from management operations.
    """
    DELETED = 0
    ENABLED = 1
    UNMANAGED = 2


class SolidServerModel(BaseModel):
    """Base Pydantic model for all SolidServer API response objects.

    Provides the shared write-layer machinery used by every concrete model:

    * **Dirty tracking** — ``__setattr__`` records which mutable fields have been
      changed since the object was loaded.  ``is_dirty`` and ``mark_clean()`` let
      the API layer flush only what has changed.
    * **Frozen enforcement** — read-only fields declare ``Field(frozen=True)``; any
      attempt to overwrite them raises ``pydantic.ValidationError``.
    * **Primary-key management** — each subclass sets ``_pk_field`` to the name of
      its PK field.  ``id`` reads it uniformly; ``assign_id()`` bypasses the frozen
      guard for server-assigned IDs after a POST.
    * **New-object lifecycle** — ``mark_new()`` flags an object as pending creation;
      ``finalize_creation()`` sets the server-assigned PK, clears the flag, and
      resets dirty tracking in one call.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="allow",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    errno: int | None = Field(None, frozen=True)

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig()

    c: ClassVar[ColumnCollection] = _CDescriptor()  # type: ignore[assignment]

    _dirty: set[str] = PrivateAttr(default_factory=set)
    _is_new: bool = PrivateAttr(default=False)

    # ---- Dirty tracking ------------------------------------------------------

    def __setattr__(self, name: str, value: object) -> None:
        if name not in type(self).model_fields:
            super().__setattr__(name, value)
            return

        previous = getattr(self, name, _MISSING)
        super().__setattr__(name, value)   # raises ValidationError for frozen fields
        # Skip dirty tracking for initial field population and no-op assignments.
        if previous is _MISSING or previous == getattr(self, name):
            return
        self._dirty.add(name)

    def model_post_init(self, __context: Any, /) -> None:
        """Wire dirty-notification callbacks for all non-frozen ClassParamDict fields."""
        prefix = type(self).solid_config.class_param_prefix
        for name in type(self).model_fields:
            val = getattr(self, name)
            if isinstance(val, ClassParamDict) and not val.frozen:
                if not val.api_prefix and prefix is not None:
                    val.api_prefix = prefix
                val.wire_callback(_make_notifier(self._dirty, name))

    def mark_clean(self) -> None:
        """Reset dirty tracking state, as if the object had just been loaded."""
        self._dirty.clear()
        for name in type(self).model_fields:
            val = getattr(self, name)
            if isinstance(val, ClassParamDict) and not val.frozen:
                val.clear_pending_deletes()

    @property
    def is_dirty(self) -> bool:
        """True if any mutable field has been changed since the object was last loaded or flushed."""
        return bool(self._dirty)

    # ---- Primary-key helpers -------------------------------------------------

    @property
    def id(self) -> int | None:
        """The primary-key value for this object, or ``None`` for unsaved objects.

        The concrete field name (e.g. ``subnet_id`` or ``site_id``) is declared
        in each subclass's ``solid_config``.
        """
        pk = type(self).solid_config.pk_field
        if not pk:
            return None
        return getattr(self, pk, None)

    def assign_id(self, value: int) -> None:
        """Set the primary-key field, bypassing the frozen constraint.

        This is called by the API layer after a successful POST to record the
        server-assigned ID.  It uses ``object.__setattr__`` internally so that
        the ``frozen=True`` declaration on the PK field does not block it.

        Args:
            value: The server-assigned primary-key integer.
        """
        object.__setattr__(self, type(self).solid_config.pk_field, value)

    @property
    def id_filter(self) -> Condition:
        """A Condition that identifies this object by its PK field.

        Useful for filtering hierarchically subordinate objects::

            s.list(Subnet, where=space.id_filter)
            # → WHERE=site_id='7'

            s.list(Subnet, where=[space.id_filter, Subnet.c.subnet_name.like('%prod%')])
            # → WHERE=(site_id='7') and (subnet_name like '%prod%')

        Raises:
            ValueError: If this object has no primary key set.
        """
        if (obj_id := self.id) is None:
            raise ValueError(f"{type(self).__name__} has no id set")
        col: ColumnExpr = ColumnCollection(type(self)).__getattr__(type(self).solid_config.pk_field)
        return col == obj_id

    # ---- New-object lifecycle ------------------------------------------------

    @property
    def is_new(self) -> bool:
        """True if this object has been registered for creation but not yet saved."""
        return self._is_new

    def mark_new(self) -> None:
        """Flag this object as pending creation and seed dirty tracking.

        Called by ``Session.new()`` before the object is added to the tracked list.
        Adds every field from ``create_fields`` that has a non-``None`` value to
        ``_dirty`` so that ``write_params()`` serialises them on the first flush.
        """
        self._is_new = True
        if (cf := type(self).solid_config.create_fields) is not None:
            for name in cf:
                if getattr(self, name, None) is not None:
                    self._dirty.add(name)

    def finalize_creation(self, pk: int) -> None:
        """Record a successful server-side creation and reset write-layer state.

        Sets the server-assigned primary key, clears ``is_new``, and resets
        dirty tracking.  Called by ``subnet_create`` / ``space_create`` after a
        successful POST.

        Args:
            pk: The server-assigned primary-key integer from ``ret_oid``.
        """
        self.assign_id(pk)
        self._is_new = False
        self.mark_clean()

    # ---- Write serialisation (override in subclasses) -----------------------

    def write_params(self) -> dict[str, str]:
        """Serialise dirty mutable fields to wire-format query parameters.

        Handles ``ClassParamDict`` fields by emitting the three wire blobs
        (``*_class_parameters``, ``*_class_parameters_properties``, and
        ``class_parameters_to_delete`` when keys have been deleted).
        Concrete models call ``super().write_params()`` and then handle their
        remaining non-ClassParamDict dirty fields.

        Returns:
            Mapping of parameter name → wire-format string for all dirty fields.
        """
        out: dict[str, str] = {}
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                prefix = val.api_prefix
                if blob := val.to_params_blob():
                    out[f"{prefix}_class_parameters"] = blob
                if props := val.to_properties_blob():
                    out[f"{prefix}_class_parameters_properties"] = props
                if val.deleted:
                    out["class_parameters_to_delete"] = urllib.parse.quote(
                        "&".join(sorted(val.deleted)), safe="",
                    )
        return out

    # ---- HTTP request / response dispatch -----------------------------------

    @classmethod
    def build_class_request(
        cls,
        operation: str,
        **kwargs: Any,
    ) -> tuple[str, str, dict[str, str]]:
        """Build an HTTP request descriptor for a class-level operation.

        Called by the Session for operations that do not require an existing
        object instance (``list``, ``info`` by PK).

        Args:
            operation: ``'list'`` or ``'info'``.
            **kwargs: Operation-specific parameters.  For ``'list'``:
                ``where``, ``orderby``, ``select``, ``offset``, ``limit``,
                ``tags``, ``no_parent_class_param``.  For ``'info'``: ``pk``.

        Returns:
            A ``(http_verb, path, params)`` triple ready to pass to the
            transport layer.

        Raises:
            TypeError: If the model has no path configured for the requested
                ``operation``.
            ValueError: If ``operation`` is not recognised.
        """
        paths = cls.solid_config.paths
        match operation:
            case "list":
                params: dict[str, str] = {}
                for kwarg, api_key in (
                    ("where", "WHERE"), ("orderby", "ORDERBY"),
                    ("select", "SELECT"), ("tags", "TAGS"),
                ):
                    if kwarg in kwargs:
                        params[api_key] = str(kwargs[kwarg])
                for key in ("offset", "limit"):
                    if key in kwargs:
                        params[key] = str(kwargs[key])
                if kwargs.get("no_parent_class_param"):
                    params["NO_PARENT_CLASS_PARAM"] = "1"
                return ("GET", paths["list"], params)
            case "info":
                if "info" not in paths:
                    raise TypeError(f"No fetch support for {cls.__name__}")
                return ("GET", paths["info"], {cls.solid_config.pk_field: str(kwargs["id"])})
            case "count":
                if "count" not in paths:
                    raise TypeError(f"No count support for {cls.__name__}")
                params = {}
                if (v := kwargs.get("where")) is not None:
                    params["WHERE"] = str(v)
                if (v := kwargs.get("tags")) is not None:
                    params["TAGS"] = str(v)
                if kwargs.get("no_parent_class_param"):
                    params["NO_PARENT_CLASS_PARAM"] = "1"
                return ("GET", paths["count"], params)
            case _:
                raise ValueError(f"Unknown class operation: {operation!r}")

    def build_request(
        self,
        operation: str,
        **kwargs: Any,  # noqa: ARG002
    ) -> tuple[str, str, dict[str, str]]:
        """Build an HTTP request descriptor for an instance-level operation.

        Called by the Session for operations that act on a specific object
        (``info``, ``create``, ``update``, ``delete``).  Concrete models may
        override this to inject derived parameters (e.g. ``subnet_addr``).

        Args:
            operation: ``'info'``, ``'create'``, ``'update'``, or ``'delete'``.
            **kwargs: Reserved for subclass overrides.

        Returns:
            A ``(http_verb, path, params)`` triple.

        Raises:
            ValueError: If the object has no primary key when ``update`` or
                ``delete`` is requested, or if ``operation`` is unrecognised.
        """
        cfg = type(self).solid_config
        match operation:
            case "info":
                if (obj_id := self.id) is None:
                    raise ValueError(f"Cannot fetch {type(self).__name__}: no id")
                return ("GET", cfg.paths["info"], {cfg.pk_field: str(obj_id)})
            case "create":
                params = self.write_params()
                params['add_flag'] = 'new_only'
                return ("POST", cfg.paths["add"], params)
            case "update":
                if (obj_id := self.id) is None:
                    raise ValueError(f"Cannot update {type(self).__name__}: no id")
                params = self.write_params()
                params['add_flag'] = 'edit_only'
                params[cfg.pk_field] = str(obj_id)
                return ("PUT", cfg.paths["add"], params)
            case "delete":
                if (obj_id := self.id) is None:
                    raise ValueError(f"Cannot delete {type(self).__name__}: no id")
                return ("DELETE", cfg.paths["delete"], {cfg.pk_field: str(obj_id)})
            case _:
                raise ValueError(f"Unknown instance operation: {operation!r}")

    @classmethod
    def parse_response(cls, operation: str, data: Any) -> Any:
        """Parse a JSON response into model instance(s).

        Called by the Session after a successful read operation.

        Args:
            operation: ``'list'`` or ``'info'``.
            data: Raw deserialised JSON from the API response.

        Returns:
            A ``list[Self]`` for ``'list'``, or a single ``Self`` for ``'info'``.

        Raises:
            ValueError: If ``operation`` is not recognised.
        """
        match operation:
            case "list":
                return [cls.model_validate(item) for item in data]
            case "info":
                first = cast(Any, data[0] if isinstance(data, list) else data)
                return cls.model_validate(first)
            case "count":
                return int(data[0]["total"])
            case _:
                raise ValueError(f"Unknown parse operation: {operation!r}")

    def apply_response(self, operation: str, data: Any) -> None:
        """Apply a write-operation API response to this instance.

        For ``create``, extracts ``ret_oid`` and calls ``finalize_creation()``.
        For ``update``, calls ``mark_clean()``.  For ``delete``, no-op.

        Args:
            operation: ``'create'``, ``'update'``, or ``'delete'``.
            data: Raw deserialised JSON from the API response.

        Raises:
            ValueError: If ``operation`` is not recognised.
        """
        match operation:
            case "create":
                result = cast(Any, data[0] if isinstance(data, list) else data)
                self.finalize_creation(int(result["ret_oid"]))
            case "update":
                self.mark_clean()
            case "delete":
                pass
            case _:
                raise ValueError(f"Unknown apply operation: {operation!r}")

    # ---- Reverse-coercion statics (Python → wire format) --------------------

    @staticmethod
    def _to_bool_str(v: bool | None) -> str:
        if v is None:
            return ""
        return "1" if v else "0"

    @staticmethod
    def _to_int_str(v: int | None) -> str:
        return "" if v is None else str(v)

    # ---- Forward-coercion helpers (wire format → Python) --------------------

    @staticmethod
    def _as_str(v: object) -> str | None:
        """'' and '#' (null sentinel) → None."""
        if v is None or v == "" or v == "#":  # noqa: PLR1714
            return None
        return str(v)

    @staticmethod
    def _as_int(v: object) -> int | None:
        if v is None or v == "" or v == "#":  # noqa: PLR1714
            return None
        try:
            return int(str(v))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _as_nz_int(v: object) -> int | None:
        """Like _as_int but treats '0' as None (foreign-key null sentinel)."""
        if v is None or v == "" or v == "#":  # noqa: PLR1714
            return None
        try:
            n = int(str(v))
            return None if n == 0 else n
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _as_float(v: object) -> float | None:
        if v is None or v == "" or v == "#":  # noqa: PLR1714
            return None
        try:
            return float(str(v))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _as_bool(v: object) -> bool | None:
        """'1' → True, '0' → False, '' / None → None.  Native bool passthrough."""
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return v
        try:
            return bool(int(str(v)))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _as_hex_ipv4(v: object) -> IPv4Address | None:
        """Hex-encoded string → IPv4Address ('0a541400' → 10.84.20.0)."""
        if v is None or v == "" or v == "#":  # noqa: PLR1714
            return None
        if isinstance(v, IPv4Address):
            return v
        try:
            return IPv4Address(int(str(v), 16))
        except ValueError:
            return None

    @staticmethod
    def _as_dotted_ipv4(v: object) -> IPv4Address | None:
        """Dotted-decimal string → IPv4Address ('10.84.20.0' → 10.84.20.0)."""
        if v is None or v == "" or v == "#":  # noqa: PLR1714
            return None
        if isinstance(v, IPv4Address):
            return v
        try:
            return IPv4Address(str(v))
        except ValueError:
            return None

    @staticmethod
    def _as_datetime(v: object) -> datetime | None:
        """Unix epoch string → UTC datetime."""
        if v is None or v == "" or v == "#":  # noqa: PLR1714
            return None
        try:
            return datetime.fromtimestamp(int(str(v)), tz=UTC)
        except (ValueError, OSError, TypeError):
            return None

    @property
    def tagged_class_parameters(self) -> dict[str, str]:
        """All tag_* extra fields keyed without the 'tag_' prefix."""
        return {
            k[4:]: v
            for k, v in (self.model_extra or {}).items()
            if k.startswith("tag_") and isinstance(v, str)
        }
