"""ClassParamDict — dict-like container for EfficientIP class parameters.

Wire format: three parallel URL-encoded blobs on each API object:
  *_class_parameters            = key=value&...
  *_class_parameters_properties = key=inheritance,propagation&...
  *_class_parameters_inheritance_source = key=container_type,container_id&...
"""
import urllib.parse
from collections.abc import Callable, ItemsView, Iterator
from typing import Any, cast

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema



VALID_INHERITANCE_MODES = frozenset({"set", "inherited", "inherited_or_set"})
VALID_PROPAGATION_MODES = frozenset({"propagate", "restrict"})

_RESERVED_KEYS = frozenset({"$propagation", "$source"})


class ClassParamDict:
    """Mutable dict-like container for EfficientIP class parameters.

    Stores the three parallel class-parameter blobs as typed internal dicts
    and exposes a mapping interface plus inheritance/propagation query methods.
    Mutations notify the owning model so that ``Session.flush()`` produces a
    correct, complete API payload (including ``class_parameters_to_delete``).

    Use ``from_blobs()`` to construct from wire data.  The ``empty()`` factory
    creates an instance with no parameters (used as the default for new objects).

    **Pydantic integration / JSON round-tripping**: this type is not a
    ``pydantic.BaseModel`` — it's a hand-rolled ``Mapping``-like container with
    mutation-notification and per-instance ``frozen`` semantics that don't fit a
    fixed-field schema.  Pydantic v2 validation/serialisation is wired up via
    :meth:`__get_pydantic_core_schema__` instead:

    - ``model_dump()`` (Python mode) returns the ``ClassParamDict`` instance
      unchanged — no conversion happens, so re-``model_validate()``-ing it is a
      lossless round-trip.
    - ``model_dump_json()`` / ``model_dump(mode="json")`` serialise via
      :meth:`to_full_dict`: parameter values sit at the top level exactly like a
      plain ``{key: value}`` dict, with two reserved ``"$"``-prefixed keys added
      alongside them only when there is something to say — ``"$propagation"``
      (per-key inheritance/propagation mode) and ``"$source"`` (per-key
      inheritance source). Parameter names must not themselves start with
      ``"$"``. ``frozen`` is not serialised — like other read-only fields on
      these models, the caller is expected to know which fields are frozen.
      Pending ``delete()`` calls are also **not** serialised: a flush is
      presumed to have already reconciled them, so a round-tripped object
      simply has no memory of keys staged for deletion. See :meth:`to_full_dict`
      / :meth:`from_full_dict`.
    - A plain ``{key: value}`` dict with neither reserved key is also accepted
      for validation, e.g. ``Session.create(cls, class_params={"k": "v"})``.
      Every key defaults to inheritance ``"inherited_or_set"`` / propagation
      ``"propagate"`` (see :meth:`from_dict`) — this path carries no per-key
      inheritance metadata, unlike the full round-trip dict above (which
      defaults an unlisted key to ``"set"`` / ``"propagate"`` instead).
    """

    _params: dict[str, str]
    _props: dict[str, tuple[str, str]]
    _sources: dict[str, tuple[str, str]]
    _deleted: set[str]
    _api_prefix: str
    _frozen: bool
    _on_mutate: Callable[[], None] | None

    def __init__(
        self,
        params: dict[str, str],
        props: dict[str, tuple[str, str]],
        sources: dict[str, tuple[str, str]],
        api_prefix: str = "",
        frozen: bool = False,
    ) -> None:
        self._params = params
        self._props = props
        self._sources = sources
        self._deleted = set()
        self._api_prefix = api_prefix
        self._frozen = frozen
        self._on_mutate = None

    # ---- Pydantic integration ---------------------------------------------

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler,  # noqa: ARG003
    ) -> CoreSchema:
        """Let Pydantic v2 validate and serialise this arbitrary type.

        Validation accepts an existing ``ClassParamDict`` (passthrough, used on
        ``model_dump()`` round-trips and internal construction), a full
        round-trip dict as produced by :meth:`to_full_dict` (used when
        re-validating ``model_dump_json()`` output), or a plain ``{key: value}``
        dict (converted via :meth:`from_dict`). Serialisation to JSON mode emits
        :meth:`to_full_dict`'s output; Python-mode ``model_dump()`` keeps
        returning the ``ClassParamDict`` instance unchanged.
        """
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                cls._serialize,
                return_schema=core_schema.dict_schema(),
                when_used="json",
            ),
        )

    @classmethod
    def _validate(cls, v: object) -> "ClassParamDict":
        return cls.from_any(v)

    @staticmethod
    def _serialize(v: "ClassParamDict") -> dict[str, Any]:
        return v.to_full_dict()

    @classmethod
    def from_any(cls, v: object, api_prefix: str = "") -> "ClassParamDict":
        """Coerce a ``ClassParamDict``, full round-trip dict, or plain dict.

        The single entry point used both by Pydantic field validation (via
        :meth:`__get_pydantic_core_schema__`) and by
        ``SolidServerModel._coerce_class_params`` for a user-supplied
        ``class_params=`` value, so both call sites resolve the plain-dict vs.
        full-round-trip-dict ambiguity identically: a dict containing either of
        the reserved ``"$propagation"`` / ``"$source"`` keys is treated as a
        full round-trip dict (see :meth:`from_full_dict`); otherwise it's a
        plain ``{key: value}`` dict (see :meth:`from_dict`).

        Raises:
            TypeError: If *v* is not a ``ClassParamDict`` or ``dict``.
            ValueError: If *v* is a full round-trip dict with an invalid
                inheritance or propagation mode (see :meth:`from_full_dict`).
        """
        if isinstance(v, ClassParamDict):
            return v
        if isinstance(v, dict):
            d = cast("dict[str, object]", v)
            if _RESERVED_KEYS & d.keys():
                return cls.from_full_dict(d, api_prefix=api_prefix)
            return cls.from_dict(d, api_prefix=api_prefix)
        raise TypeError(f"Cannot construct ClassParamDict from {type(v).__name__}")

    @classmethod
    def empty(cls) -> "ClassParamDict":
        """Return an empty ClassParamDict; api_prefix is set later by model_post_init."""
        return cls({}, {}, {})

    @classmethod
    def from_dict(cls, d: dict[str, object], api_prefix: str = "") -> "ClassParamDict":
        """Build a ClassParamDict from a plain Python dict.

        Each key is set with inheritance ``"inherited_or_set"`` and propagation
        ``"propagate"`` — the same defaults as ``__setitem__``.  Values are
        coerced to ``str``.  Used by ``_coerce_class_params`` to accept user-
        supplied dicts in ``Session.create()`` / ``Vrf(class_params={...})``.
        """
        result = cls({}, {}, {}, api_prefix=api_prefix)
        for k, v in d.items():
            result[k] = str(v)
        return result

    @classmethod
    def from_blobs(
        cls,
        params_blob: str | None,
        props_blob: str | None,
        sources_blob: str | None = None,
        api_prefix: str = "",
        frozen: bool = False,
    ) -> "ClassParamDict":
        """Parse wire-format URL-encoded blobs into a ClassParamDict.

        Args:
            params_blob: ``*_class_parameters`` blob string.
            props_blob: ``*_class_parameters_properties`` blob string.
            sources_blob: ``*_class_parameters_inheritance_source`` blob string (optional).
            api_prefix: Wire field prefix, e.g. ``"subnet"`` or ``"site"``.
            frozen: If ``True``, mutations raise ``TypeError``.
        """
        params: dict[str, str] = {}
        props: dict[str, tuple[str, str]] = {}
        sources: dict[str, tuple[str, str]] = {}

        if params_blob:
            params.update(urllib.parse.parse_qsl(params_blob, keep_blank_values=True))

        if props_blob:
            for k, v in urllib.parse.parse_qsl(props_blob, keep_blank_values=True):
                parts = v.split(",", 1)
                inheritance = parts[0]
                propagation = parts[1] if len(parts) > 1 else "propagate"
                props[k] = (inheritance, propagation)

        for k in params:
            if k not in props:
                props[k] = ("set", "propagate")

        if sources_blob:
            for k, v in urllib.parse.parse_qsl(sources_blob, keep_blank_values=True):
                parts = v.split(",", 1)
                container_type = parts[0]
                container_id = parts[1] if len(parts) > 1 else ""
                sources[k] = (container_type, container_id)

        return cls(params, props, sources, api_prefix=api_prefix, frozen=frozen)

    # ---- Full round-trip (de)serialisation --------------------------------

    def to_full_dict(self) -> dict[str, Any]:
        """Serialise param values and metadata to a plain, JSON-safe dict.

        This is the format used by ``model_dump_json()`` for fields typed
        ``ClassParamDict`` — pass the result to :meth:`from_full_dict` (or just
        re-run it through ``model_validate_json()``) to reconstruct an
        equivalent instance.

        Values sit at the top level exactly like a plain ``{key: value}``
        dict. Two reserved keys are added alongside them, each omitted
        entirely when there's nothing to say:

        - ``"$propagation"`` — ``{key: "inheritance,propagation"}`` for every
          key that has property metadata (the same encoding used by
          :meth:`from_blobs`). Omitted if empty.
        - ``"$source"`` — ``{key: "container_type,container_id"}`` for every
          key with a recorded inheritance source. Omitted if empty.

        ``frozen`` is not serialised — like other read-only fields on these
        models, the caller is expected to know which fields are frozen; a
        reconstructed instance is always mutable. Keys staged for deletion via
        :meth:`delete` are also **not** included — a flush is presumed to have
        already reconciled them with the server, so round-tripping does not
        preserve pending deletions.
        """
        result: dict[str, Any] = dict(self._params)
        if propagation := {
            k: f"{inh},{prop}" for k, (inh, prop) in self._props.items() if k in self._params
        }:
            result["$propagation"] = propagation
        if source := {
            k: f"{ctype},{cid}" for k, (ctype, cid) in self._sources.items() if k in self._params
        }:
            result["$source"] = source
        return result

    @classmethod
    def from_full_dict(cls, d: dict[str, Any], api_prefix: str = "") -> "ClassParamDict":
        """Reconstruct a ``ClassParamDict`` from :meth:`to_full_dict`'s output.

        Every top-level key other than ``"$propagation"`` and ``"$source"`` is
        a parameter value. Both reserved keys may be omitted; a parameter key
        omitted from ``"$propagation"`` entirely defaults to inheritance
        ``"set"`` / propagation ``"propagate"`` (matching :meth:`from_blobs`'s
        default for a key with no properties entry). The result is always
        unfrozen, since ``to_full_dict()`` does not serialise ``frozen``.

        Args:
            d: A dict as produced by :meth:`to_full_dict`.
            api_prefix: Wire field prefix, e.g. ``"subnet"`` or ``"site"``.

        Raises:
            TypeError: If ``"$propagation"`` or ``"$source"`` is present but
                not a dict.
            ValueError: If a ``"$propagation"`` entry names an inheritance mode
                not in ``VALID_INHERITANCE_MODES`` or a propagation mode not in
                ``VALID_PROPAGATION_MODES``.
        """
        params: dict[str, str] = {str(k): str(v) for k, v in d.items() if k not in _RESERVED_KEYS}

        raw_propagation: object = d.get("$propagation") or {}
        if not isinstance(raw_propagation, dict):
            raise TypeError(f"'$propagation' must be a dict, got {type(raw_propagation).__name__}")
        props: dict[str, tuple[str, str]] = {}
        for k, v in cast("dict[str, object]", raw_propagation).items():
            parts = str(v).split(",", 1)
            inheritance = parts[0]
            propagation = parts[1] if len(parts) > 1 else "propagate"
            if inheritance not in VALID_INHERITANCE_MODES:
                raise ValueError(
                    f"Invalid inheritance mode {inheritance!r} for class parameter {k!r}; "
                    f"must be one of {sorted(VALID_INHERITANCE_MODES)}",
                )
            if propagation not in VALID_PROPAGATION_MODES:
                raise ValueError(
                    f"Invalid propagation mode {propagation!r} for class parameter {k!r}; "
                    f"must be one of {sorted(VALID_PROPAGATION_MODES)}",
                )
            props[str(k)] = (inheritance, propagation)
        for k in params:
            if k not in props:
                props[k] = ("set", "propagate")

        raw_source: object = d.get("$source") or {}
        if not isinstance(raw_source, dict):
            raise TypeError(f"'$source' must be a dict, got {type(raw_source).__name__}")
        sources: dict[str, tuple[str, str]] = {}
        for k, v in cast("dict[str, object]", raw_source).items():
            parts = str(v).split(",", 1)
            sources[str(k)] = (parts[0], parts[1] if len(parts) > 1 else "")

        return cls(params, props, sources, api_prefix=api_prefix)

    # ---- Mapping interface -----------------------------------------------

    def __getitem__(self, k: str) -> str:
        return self._params[k]

    def get(self, k: str, default: str | None = None) -> str | None:
        """Return the value for key *k*, or *default* if not present."""
        return self._params.get(k, default)

    def __setitem__(self, k: str, v: str) -> None:
        """Set a parameter using the default ``inherited_or_set`` inheritance mode.

        Existing key: overwrites the value, sets inheritance → ``"inherited_or_set"``,
        leaves propagation unchanged.
        New key: sets value, inheritance → ``"inherited_or_set"``, propagation → ``"propagate"``.

        Use :meth:`set` for explicit control over inheritance and propagation.
        """
        if self._frozen:
            raise TypeError("ClassParamDict is read-only")
        if k in self._props:
            _, propagation = self._props[k]
            self._props[k] = ("inherited_or_set", propagation)
        else:
            self._props[k] = ("inherited_or_set", "propagate")
        self._params[k] = v
        self._deleted.discard(k)
        self._notify()

    def __delitem__(self, k: str) -> None:
        self.delete(k)

    def __iter__(self) -> Iterator[str]:
        return iter(self._params)

    def __len__(self) -> int:
        return len(self._params)

    def __contains__(self, k: object) -> bool:
        return k in self._params

    def __repr__(self) -> str:
        return f"ClassParamDict({self._params!r})"

    def items(self) -> ItemsView[str, str]:
        """Return all key/value pairs as an ItemsView."""
        return self._params.items()

    # ---- Inheritance/propagation query methods ---------------------------
    # All methods raise KeyError if k is not in _props.

    def is_set(self, k: str) -> bool:
        """True if *k* has inheritance mode ``"set"`` (explicitly set on this object)."""
        return self._props[k][0] == "set"

    def is_inherited(self, k: str) -> bool:
        """True if *k* has inheritance mode ``"inherited"`` (value comes from a parent)."""
        return self._props[k][0] == "inherited"

    def is_inherited_or_set(self, k: str) -> bool:
        """True if *k* has inheritance mode ``"inherited_or_set"``."""
        return self._props[k][0] == "inherited_or_set"

    def is_propagate(self, k: str) -> bool:
        """True if *k* propagates its value to child objects."""
        return self._props[k][1] == "propagate"

    def is_restrict(self, k: str) -> bool:
        """True if *k* does NOT propagate to child objects (``"restrict"`` mode)."""
        return self._props[k][1] == "restrict"

    # ---- Mutation methods ------------------------------------------------

    def set(self, k: str, v: str, inherited_or_set: bool = True, restrict: bool = False) -> None:
        """Set a parameter with explicit inheritance and propagation control.

        Args:
            k: Parameter key name.
            v: Parameter value.
            inherited_or_set: If ``True`` (default), sets inheritance to
                ``"inherited_or_set"``.  If ``False``, uses ``"set"``.
            restrict: If ``True``, sets propagation to ``"restrict"``.
                Defaults to ``"propagate"``.
        """
        if self._frozen:
            raise TypeError("ClassParamDict is read-only")
        inheritance = "inherited_or_set" if inherited_or_set else "set"
        propagation = "restrict" if restrict else "propagate"
        self._params[k] = v
        self._props[k] = (inheritance, propagation)
        self._deleted.discard(k)
        self._notify()

    def delete(self, k: str) -> None:
        """Stage a parameter for deletion on next flush.

        Removes the parameter from the local value dict and adds it to the
        ``deleted`` set, which is serialised as ``class_parameters_to_delete``
        in the next PUT request.
        """
        if self._frozen:
            raise TypeError("ClassParamDict is read-only")
        self._params.pop(k, None)
        self._deleted.add(k)
        self._notify()

    @property
    def deleted(self) -> frozenset[str]:
        """Keys staged for deletion via ``class_parameters_to_delete`` on next flush."""
        return frozenset(self._deleted)

    # ---- Wire serialisation ----------------------------------------------

    def to_params_blob(self) -> str:
        """Serialise params to a URL-encoded ``*_class_parameters`` blob."""
        return urllib.parse.urlencode(self._params)

    def to_properties_blob(self) -> str:
        """Serialise props to a URL-encoded ``*_class_parameters_properties`` blob."""
        return urllib.parse.urlencode({
            k: f"{inh},{prop}"
            for k, (inh, prop) in self._props.items()
        })

    # ---- Public lifecycle helpers (used by SolidServerModel) ----------------

    @property
    def frozen(self) -> bool:
        """True if this ClassParamDict is read-only."""
        return self._frozen

    @property
    def api_prefix(self) -> str:
        """Wire field prefix, e.g. ``"subnet"`` or ``"site"``."""
        return self._api_prefix

    @api_prefix.setter
    def api_prefix(self, value: str) -> None:
        self._api_prefix = value

    def wire_callback(self, callback: Callable[[], None]) -> None:
        """Set the dirty-notification callback; called by ``model_post_init``."""
        self._on_mutate = callback

    def clear_pending_deletes(self) -> None:
        """Clear staged deletions; called by ``mark_clean``."""
        self._deleted.clear()

    # ---- Inheritance-source query ----------------------------------------

    def source(self, k: str) -> tuple[str, str]:
        """Return the ``(container_type, container_id)`` source for key *k*.

        Raises:
            KeyError: If *k* has no inheritance source recorded.
        """
        return self._sources[k]

    # ---- Internal --------------------------------------------------------

    def _notify(self) -> None:
        if self._on_mutate is not None:
            self._on_mutate()
