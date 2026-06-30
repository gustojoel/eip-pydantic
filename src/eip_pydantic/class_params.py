"""ClassParamDict — dict-like container for EfficientIP class parameters.

Wire format: three parallel URL-encoded blobs on each API object:
  *_class_parameters            = key=value&...
  *_class_parameters_properties = key=inheritance,propagation&...
  *_class_parameters_inheritance_source = key=container_type,container_id&...
"""
import urllib.parse
from collections.abc import Callable, ItemsView, Iterator



class ClassParamDict:
    """Mutable dict-like container for EfficientIP class parameters.

    Stores the three parallel class-parameter blobs as typed internal dicts
    and exposes a mapping interface plus inheritance/propagation query methods.
    Mutations notify the owning model so that ``Session.flush()`` produces a
    correct, complete API payload (including ``class_parameters_to_delete``).

    Use ``from_blobs()`` to construct from wire data.  The ``empty()`` factory
    creates an instance with no parameters (used as the default for new objects).
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

    # ---- Mapping interface -----------------------------------------------

    def __getitem__(self, k: str) -> str:
        return self._params[k]

    def get(self, k: str, default: str | None = None) -> str | None:
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
