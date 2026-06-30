"""WHERE-clause and ORDER BY expression builder.

.. include:: ../../docs/expressions.md
"""

from collections.abc import Iterable
from ipaddress import IPv4Address, IPv4Network
from typing import TYPE_CHECKING



if TYPE_CHECKING:
    from eip_pydantic.models.base import SolidServerModel


def and_all(conditions: Iterable["Condition"]) -> "Condition":
    """AND an iterable of Conditions into a single Condition.

    Raises:
        ValueError: If ``conditions`` is empty.
    """
    it = iter(conditions)
    try:
        result = next(it)
    except StopIteration:
        raise ValueError("and_all requires at least one Condition") from None
    for cond in it:
        result = result & cond
    return result


def _quote(value: object) -> str:
    """Coerce a value to a single-quoted API string, escaping internal single quotes."""
    s = str(value) if value is not None else ""
    return "'" + s.replace("'", "''") + "'"


class Condition:
    """A serialisable WHERE expression produced by ``Model.c.<field>`` operators.

    Instances are created by the comparison operators on ``ColumnExpr`` and
    should not normally be constructed directly.  They are passed to
    ``Session.list(where=...)``; ``Session`` calls ``str()`` on them to obtain
    the raw API ``WHERE`` string and reads ``required_tags`` to auto-inject the
    ``TAGS`` parameter.

    Attributes:
        required_tags: Tags that must be present in the API ``TAGS`` parameter
            for this condition to be evaluated.  Empty for real model fields;
            contains ``"{prefix}.{name}"`` entries for tagged class parameters.

    Combine conditions with ``&`` (``and``) or ``|`` (``or``)::

        cond = (Subnet.c.site_id == '7') & (Subnet.c.subnet_name == 'prod')
        str(cond)           # "(site_id='7') and (subnet_name='prod')"
        cond.required_tags  # frozenset()  — both are real fields

        cond2 = (Subnet.c.site_id == '7') & (Subnet.c.foobar == 'baz')
        str(cond2)           # "(site_id='7') and (tag_network_foobar='baz')"
        cond2.required_tags  # frozenset({'network.foobar'})

    Nested combinations union their ``required_tags`` automatically::

        a = Subnet.c.foo == '1'   # required_tags: {'network.foo'}
        b = Subnet.c.bar == '2'   # required_tags: {'network.bar'}
        c = a & b                 # required_tags: {'network.foo', 'network.bar'}
    """

    def __init__(self, expr: str, required_tags: frozenset[str] = frozenset()) -> None:
        self._expr = expr
        self.required_tags = required_tags

    def __and__(self, other: "Condition") -> "Condition":
        """Combine two conditions with ``and``.

        Parenthesises both sides to preserve precedence::

            (Subnet.c.site_id == '7') & (Subnet.c.subnet_name == 'prod')
            # → (site_id='7') and (subnet_name='prod')
        """
        return Condition(
            f"({self._expr}) and ({other._expr})",
            self.required_tags | other.required_tags,
        )

    def __or__(self, other: "Condition") -> "Condition":
        """Combine two conditions with ``or``.

        Parenthesises both sides to preserve precedence::

            (Space.c.site_name == 'prod') | (Space.c.site_name == 'staging')
            # → (site_name='prod') or (site_name='staging')
        """
        return Condition(
            f"({self._expr}) or ({other._expr})",
            self.required_tags | other.required_tags,
        )

    def __str__(self) -> str:
        """Return the raw API WHERE string."""
        return self._expr

    def __repr__(self) -> str:
        return f"Condition({self._expr!r})"


class OrderByExpr:
    """A serialisable ORDER BY expression produced by ``ColumnExpr.asc()`` / ``.desc()``.

    Instances are created by ``.asc()`` / ``.desc()`` on ``ColumnExpr`` and
    should not normally be constructed directly.  They are passed to
    ``Session.list(orderby=...)``; ``Session`` calls ``str()`` on them to obtain
    the raw API ``ORDERBY`` string and reads ``required_tags`` to auto-inject
    the ``TAGS`` parameter.

    Attributes:
        required_tags: Tags that must be present in the API ``TAGS`` parameter
            for this expression to be evaluated.  Empty for real model fields;
            contains ``"{prefix}.{name}"`` for tagged class parameters.

    Examples::

        Subnet.c.subnet_name.asc()   # ORDERBY=subnet_name ASC  (no TAGS)
        Subnet.c.priority.desc()     # ORDERBY=tag_network_priority DESC
                                     # TAGS=network.priority  (auto-injected)
    """

    def __init__(self, expr: str, required_tags: frozenset[str] = frozenset()) -> None:
        self._expr = expr
        self.required_tags = required_tags

    def __str__(self) -> str:
        """Return the raw API ORDERBY string."""
        return self._expr

    def __repr__(self) -> str:
        return f"OrderByExpr({self._expr!r})"


class ColumnExpr:
    """A column reference used to build ``Condition`` and ``OrderByExpr`` objects.

    Produced by ``Model.c.<field_name>``; should not be constructed directly.
    All comparison operators return a ``Condition``; ``.asc()`` / ``.desc()``
    return an ``OrderByExpr``.

    All values are coerced with ``str()`` and single-quoted.  Integer, bool,
    ``IPv4Address``, and similar types are all handled the same way — the API
    treats every value as a string.  Internal single quotes are escaped by
    doubling them (``O'Brien`` → ``'O''Brien'``).

    Operator summary (``f`` = field name, ``v`` = quoted value):

    - ``Model.c.field == value`` → ``f='v'``
    - ``Model.c.field != value`` → ``f!='v'``
    - ``Model.c.field < value`` → ``f<'v'``
    - ``Model.c.field <= value`` → ``f<='v'``
    - ``Model.c.field > value`` → ``f>'v'``
    - ``Model.c.field >= value`` → ``f>='v'``
    - ``Model.c.field.like('%val%')`` → ``f like '%val%'``
    - ``Model.c.field.in_(['a','b'])`` → ``f in ('a', 'b')``
    - ``Model.c.field.is_null()`` → ``f=''``
    - ``Model.c.field.asc()`` → ``f ASC``
    - ``Model.c.field.desc()`` → ``f DESC``
    """

    def __init__(self, field_name: str, required_tags: frozenset[str] = frozenset()) -> None:
        self._field_name = field_name
        self._required_tags = required_tags

    def __hash__(self) -> int:
        return hash((self._field_name, self._required_tags))

    def __eq__(self, other: object) -> Condition:  # type: ignore[override]
        """Equality: ``field='value'``.

        Example::

            Subnet.c.subnet_name == 'prod-dmz'
            # WHERE: subnet_name='prod-dmz'

            Subnet.c.site_id == 7     # int coerced to str
            # WHERE: site_id='7'
        """
        return Condition(f"{self._field_name}={_quote(other)}", self._required_tags)

    def __ne__(self, other: object) -> Condition:  # type: ignore[override]
        """Inequality: ``field!='value'``.

        Example::

            Subnet.c.subnet_name != 'legacy'
            # WHERE: subnet_name!='legacy'
        """
        return Condition(f"{self._field_name}!={_quote(other)}", self._required_tags)

    def __lt__(self, other: object) -> Condition:
        """Less-than: ``field<'value'``.

        Example::

            Subnet.c.subnet_size < 256
            # WHERE: subnet_size<'256'
        """
        return Condition(f"{self._field_name}<{_quote(other)}", self._required_tags)

    def __le__(self, other: object) -> Condition:
        """Less-than-or-equal: ``field<='value'``.

        Example::

            Subnet.c.subnet_size <= 256
            # WHERE: subnet_size<='256'
        """
        return Condition(f"{self._field_name}<={_quote(other)}", self._required_tags)

    def __gt__(self, other: object) -> Condition:
        """Greater-than: ``field>'value'``.

        Example::

            Subnet.c.subnet_size > 0
            # WHERE: subnet_size>'0'
        """
        return Condition(f"{self._field_name}>{_quote(other)}", self._required_tags)

    def __ge__(self, other: object) -> Condition:
        """Greater-than-or-equal: ``field>='value'``.

        Example::

            Subnet.c.subnet_size >= 128
            # WHERE: subnet_size>='128'
        """
        return Condition(f"{self._field_name}>={_quote(other)}", self._required_tags)

    def like(self, pattern: str) -> Condition:
        """Pattern match: ``field like 'pattern'``.

        ``%`` is the wildcard character (SolidServer uses SQL-style LIKE).

        Example::

            Subnet.c.subnet_name.like('%prod%')
            # WHERE: subnet_name like '%prod%'

            Subnet.c.foobar.like('prefix%')
            # WHERE: tag_network_foobar like 'prefix%'
            # TAGS:  network.foobar  (auto-injected)
        """
        return Condition(f"{self._field_name} like {_quote(pattern)}", self._required_tags)

    def in_(self, values: Iterable[object]) -> Condition:
        """Membership test: ``field in ('a', 'b', ...)``.

        All values are coerced to single-quoted strings.

        Example::

            Subnet.c.site_id.in_(['1', '2', '7'])
            # WHERE: site_id in ('1', '2', '7')

            Subnet.c.env.in_(['prod', 'staging'])
            # WHERE: tag_network_env in ('prod', 'staging')
            # TAGS:  network.env  (auto-injected)
        """
        quoted = ", ".join(_quote(v) for v in values)
        return Condition(f"{self._field_name} in ({quoted})", self._required_tags)

    def is_null(self) -> Condition:
        """Empty/null check: ``field=''``.

        The SolidServer API represents NULL as an empty string.

        Example::

            Subnet.c.subnet_class_name.is_null()
            # WHERE: subnet_class_name=''
        """
        return Condition(f"{self._field_name}=''", self._required_tags)

    def asc(self) -> OrderByExpr:
        """Ascending ORDER BY.

        Example::

            s.list(Subnet, orderby=Subnet.c.subnet_name.asc())
            # ORDERBY: subnet_name ASC

            s.list(Subnet, orderby=Subnet.c.priority.asc())
            # ORDERBY: tag_network_priority ASC
            # TAGS:    network.priority  (auto-injected)
        """
        return OrderByExpr(f"{self._field_name} ASC", self._required_tags)

    def desc(self) -> OrderByExpr:
        """Descending ORDER BY.

        Example::

            s.list(Subnet, orderby=Subnet.c.subnet_name.desc())
            # ORDERBY: subnet_name DESC
        """
        return OrderByExpr(f"{self._field_name} DESC", self._required_tags)


class HexIpv4ColumnExpr(ColumnExpr):
    """ColumnExpr for hex-encoded IPv4 address wire columns.

    Accepts ``IPv4Address`` objects, dotted-decimal strings (``'10.0.0.1'``),
    or raw 8-char hex strings (``'0a000001'``).  All are normalised to the
    8-character lowercase hex format the SolidServer API uses in ``WHERE``
    clauses.  Unknown formats are passed through as-is.

    All six comparison operators (``==``, ``!=``, ``<``, ``<=``, ``>``,
    ``>=``) and ``in_()`` convert values to hex.  Use for any field decoded
    with ``_as_hex_ipv4`` in the model ``_coerce`` validator.
    """

    __hash__ = ColumnExpr.__hash__

    @staticmethod
    def _to_hex(value: object) -> str:
        if isinstance(value, IPv4Address):
            return f"{int(value):08x}"
        s = str(value)
        if len(s) == 8 and all(c in "0123456789abcdefABCDEF" for c in s):
            return s.lower()
        try:
            return f"{int(IPv4Address(s)):08x}"
        except ValueError:
            return s

    def __eq__(self, other: object) -> Condition:  # type: ignore[override]
        return Condition(f"{self._field_name}={_quote(self._to_hex(other))}", self._required_tags)

    def __ne__(self, other: object) -> Condition:  # type: ignore[override]
        return Condition(f"{self._field_name}!={_quote(self._to_hex(other))}", self._required_tags)

    def __lt__(self, other: object) -> Condition:
        return Condition(f"{self._field_name}<{_quote(self._to_hex(other))}", self._required_tags)

    def __le__(self, other: object) -> Condition:
        return Condition(f"{self._field_name}<={_quote(self._to_hex(other))}", self._required_tags)

    def __gt__(self, other: object) -> Condition:
        return Condition(f"{self._field_name}>{_quote(self._to_hex(other))}", self._required_tags)

    def __ge__(self, other: object) -> Condition:
        return Condition(f"{self._field_name}>={_quote(self._to_hex(other))}", self._required_tags)

    def in_(self, values: Iterable[object]) -> Condition:
        """Membership test with hex conversion for each value."""
        quoted = ", ".join(_quote(self._to_hex(v)) for v in values)
        return Condition(f"{self._field_name} in ({quoted})", self._required_tags)


class NetworkColumnExpr(ColumnExpr):
    """ColumnExpr for IPv4 network columns (e.g. ``Subnet.c.subnet``).

    ``== IPv4Network(...)`` or ``== '10.0.0.0/24'`` produces a compound
    ``(start_ip_addr='<hex>') and (end_ip_addr='<hex>')`` condition matching
    the hex wire format used by ``ip_block_subnet_list``.  Any other value
    falls back to a plain equality condition on the declared field name.
    """

    __hash__ = ColumnExpr.__hash__

    def __eq__(self, other: object) -> Condition:  # type: ignore[override]
        try:
            net = other if isinstance(other, IPv4Network) else IPv4Network(str(other), strict=False)
        except ValueError:
            return super().__eq__(other)
        start_hex = f"{int(net.network_address):08x}"
        end_hex = f"{int(net.broadcast_address):08x}"
        return (
            Condition(f"start_ip_addr={_quote(start_hex)}") &
            Condition(f"end_ip_addr={_quote(end_hex)}")
        )


class ColumnCollection:
    """Attribute namespace that produces ``ColumnExpr`` instances for a model class.

    Accessed as ``Model.c``; do not instantiate directly.

    The dispatch logic is:

    1. ``Model.column_expr_for(name)`` — model-specific override (e.g.
       ``Subnet.c.subnet`` returns a :class:`NetworkColumnExpr`).
    2. ``Model.solid_config.hex_ip_columns`` — hex-encoded IPv4 wire columns
       → :class:`HexIpv4ColumnExpr` (auto-converts ``IPv4Address`` / dotted
       strings to 8-char hex before quoting).
    3. ``Model.model_fields`` — declared Pydantic fields → plain ``ColumnExpr``.
    4. ``Model.solid_config.virtual_columns`` — Python properties that map
       directly to same-named wire columns → plain ``ColumnExpr``.
    4. Tagged class parameter fallback → ``ColumnExpr('tag_{prefix}_{name}',
       required_tags={'{prefix}.{name}'})``.

    Examples::

        # Real field — no TAGS involvement
        Subnet.c.subnet_name          # ColumnExpr('subnet_name')
        Subnet.c.site_id == '7'       # Condition("site_id='7'", required_tags=frozenset())

        # Virtual column (property, not in model_fields) — no TAGS
        Subnet.c.subnet_size >= 256   # Condition("subnet_size>='256'")
        Subnet.c.start_ip_addr == '0a000000'  # Condition("start_ip_addr='0a000000'")

        # Network virtual column — compound hex condition
        Subnet.c.subnet == '10.0.0.0/24'
        # → (start_ip_addr='0a000000') and (end_ip_addr='0a0000ff')

        # Tagged class parameter — TAGS auto-injected by Session.list()
        Subnet.c.foobar               # ColumnExpr('tag_network_foobar',
                                      #             required_tags={'network.foobar'})
        Subnet.c.foobar == 'baz'      # Condition("tag_network_foobar='baz'",
                                      #            required_tags={'network.foobar'})

        Space.c.rank.desc()           # OrderByExpr('tag_site_rank DESC',
                                      #              required_tags={'site.rank'})
    """

    def __init__(self, model_cls: "type[SolidServerModel]") -> None:
        self._model_cls = model_cls

    def __dir__(self) -> list[str]:
        return list(self._model_cls.model_fields.keys())

    def __getattr__(self, name: str) -> ColumnExpr:
        if name.startswith("_"):
            raise AttributeError(name)
        model_cls = self._model_cls
        custom = model_cls.column_expr_for(name)
        if custom is not None:
            return custom
        if name in model_cls.solid_config.hex_ip_columns:
            return HexIpv4ColumnExpr(name)
        if name in model_cls.model_fields:
            return ColumnExpr(name)
        if name in model_cls.solid_config.virtual_columns:
            return ColumnExpr(name)
        prefix = model_cls.solid_config.tags_prefix
        if not prefix:
            return ColumnExpr(name)
        return ColumnExpr(f"tag_{prefix}_{name}", frozenset({f"{prefix}.{name}"}))
