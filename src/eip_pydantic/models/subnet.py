"""Subnet and FreeSubnet models (``ip_block_subnet_list`` / ``ip_find_free_subnet``)."""
from datetime import datetime
from ipaddress import IPv4Address, IPv4Network
from types import MappingProxyType
from typing import Any, ClassVar, Literal, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.exceptions import InternalError
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class FreeSubnet(SolidServerModel):
    """One candidate slot returned by ``ip_find_free_subnet``.

    Each row represents an available address range that could hold a new
    subnet of the requested size.  Results are ordered by ``cost`` ascending
    (lowest cost = least fragmentation).
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        paths=MappingProxyType({"find_free": "rpc/ip_find_free_subnet"}),
    )

    start_ip_addr: IPv4Address | None = None
    start_hostaddr: IPv4Address | None = None
    block_name: str | None = None
    cost: int | None = None
    block_id: int | None = None
    site_id: int | None = None

    @classmethod
    def build_class_request(
        cls,
        operation: str,
        **kwargs: Any,
    ) -> tuple[str, str, dict[str, str]]:
        """Build the request descriptor for ``ip_find_free_subnet``.

        Args:
            operation: Must be ``'find_free'``.
            prefix: CIDR prefix length (1 to 32) of the desired subnet.
            size: Number of IP addresses the desired subnet must contain.
            space: Space to search in — an integer ID or a :class:`Space` instance.
            subnet: Parent block to restrict the search — an integer ID or a
                :class:`Subnet` instance.
            max_find: Maximum number of candidates to return (default 10).
            begin_addr: Start of the address range to search within.
            end_addr: End of the address range to search within.
            use_searched_path: If ``True``, also recurse into non-terminal subnets
                within the given block.
            where: SQL-style filter applied server-side.

        Returns:
            ``("OPTIONS", path, params)`` triple ready for :meth:`Session._dispatch`.

        Raises:
            InternalError: If ``operation`` is not ``'find_free'``.
            ValueError: If neither ``prefix`` nor ``size`` is provided.
        """
        if operation != "find_free":
            raise InternalError(
                f"FreeSubnet.build_class_request only supports 'find_free', got {operation!r}",
            )
        prefix = kwargs.get("prefix")
        size = kwargs.get("size")
        if prefix is None and size is None:
            raise ValueError("find_free_subnet requires either 'prefix' or 'size'")
        params: dict[str, str] = {}
        if prefix is not None:
            params["prefix"] = str(prefix)
        if size is not None:
            params["size"] = str(size)
        if (space := kwargs.get("space")) is not None:
            site_id = space if isinstance(space, int) else space.id
            if site_id is not None:
                params["site_id"] = str(site_id)
        if (subnet := kwargs.get("subnet")) is not None:
            block_id = subnet if isinstance(subnet, int) else subnet.id
            if block_id is not None:
                params["block_id"] = str(block_id)
        if (v := kwargs.get("max_find")) is not None:
            params["max_find"] = str(v)
        if (v := kwargs.get("begin_addr")) is not None:
            params["begin_addr"] = str(v)
        if (v := kwargs.get("end_addr")) is not None:
            params["end_addr"] = str(v)
        if (usp := kwargs.get("use_searched_path")) is not None:
            params["use_searched_path"] = "1" if usp else "0"
        if (where := kwargs.get("where")) is not None:
            params["WHERE"] = str(where)
        return ("OPTIONS", cls.solid_config.paths["find_free"], params)

    @classmethod
    def parse_response(cls, operation: str, data: Any) -> "list[FreeSubnet]":
        """Parse the raw JSON rows from ``ip_find_free_subnet`` into model instances.

        Args:
            operation: Must be ``'find_free'``.
            data: Raw list of dicts from the API response.

        Returns:
            List of :class:`FreeSubnet` instances.

        Raises:
            InternalError: If ``operation`` is not ``'find_free'``.
        """
        if operation != "find_free":
            raise InternalError(
                f"FreeSubnet.parse_response only supports 'find_free', got {operation!r}",
            )
        return [cls.model_validate(item) for item in data]

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)
        out: dict[str, Any] = {}
        for key, val in v.items():
            match key:
                case "start_ip_addr":
                    out[key] = cls._as_hex_ipv4(val)
                case "start_hostaddr":
                    out[key] = cls._as_dotted_ipv4(val)
                case "cost" | "block_id" | "site_id" | "errno":
                    out[key] = cls._as_int(val)
                case _:
                    out[key] = cls._as_str(val) if key in cls.model_fields else val
        return out



class Subnet(SolidServerModel):
    """An EfficientIP IPv4 network — either a block or a subnet.

    Returned by ``ip_block_subnet_list`` and ``ip_block_subnet_info``.
    ``type == "block"`` when ``subnet_level == 0``; otherwise ``type == "subnet"``.

    Mutable fields (writable via ``Session.flush()``):
        ``subnet_name``, ``subnet_class_name``, ``subnet_class_parameters``,
        ``subnet_class_parameters_properties``, ``lock_network_broadcast``,
        ``is_terminal``, ``is_in_orphan``, ``row_enabled``.

    All address, usage-statistic, audit, and linkage fields are frozen and
    reflect server-managed state.  Changing the address range requires
    deleting and recreating the network.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="subnet_id",
        class_param_prefix="subnet",
        tags_prefix="network",
        create_fields=frozenset({
            # Either site_id or site_name or parent_subnet_id is required to define the parent Space or Subnet.
            "site_id", "site_name", "parent_subnet_id",
            # Either vlsm_site_id or vlsm_site_name is required to define the VLSM Space.
            "vlsm_site_id", "vlsm_site_name",
            # subnet_name and subnet are required, and must be unique.
            "subnet_name", "subnet",
            "subnet_level",
            "subnet_class_name", "class_params",
            "is_terminal",
            "vlmvlan_id",
            "lock_network_broadcast",
        }),
        paths=MappingProxyType({
            "list":   "rest/ip_block_subnet_list",
            "info":   "rest/ip_block_subnet_info",
            "count":  "rest/ip_block_subnet_count",
            "add":    "rest/ip_subnet_add",
            "delete": "rest/ip_subnet_delete",
        }),
    )

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------
    subnet_id: int | None = Field(None, frozen=True)
    type: Literal["block", "subnet"] | None = Field(None, frozen=True)
    subnet_name: str # required
    subnet_level: int | None = Field(None, frozen=True)   # 0 = block, 1+ = subnet depth
    subnet_path: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # IP addressing (frozen — change of range requires delete + recreate)
    # ------------------------------------------------------------------
    subnet: IPv4Network | None = Field(None, frozen=True)
    @property
    def start_ip_addr(self) -> IPv4Address | None:  # noqa: D102
        return self.subnet.network_address if self.subnet is not None else None
    @property
    def end_ip_addr(self) -> IPv4Address | None:  # noqa: D102
        return self.subnet.broadcast_address if self.subnet is not None else None
    @property
    def subnet_size(self) -> int | None:  # noqa: D102
        return self.subnet.num_addresses if self.subnet is not None else None
    @property
    def subnet_prefix(self) -> int | None:  # noqa: D102
        return self.subnet.prefixlen if self.subnet is not None else None

    subnet_is_valid: bool | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Status flags
    # ------------------------------------------------------------------
    row_enabled: RowEnabled | None = None
    is_terminal: bool | None = None
    is_in_orphan: bool | None = None
    lock_network_broadcast: bool | None = None
    waiting_state: str | None = Field(None, frozen=True)
    waiting_status: int | None = Field(None, frozen=True)
    multistatus: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Usage statistics (server-computed, all frozen)
    # ------------------------------------------------------------------
    subnet_allocated_size: int | None = Field(None, frozen=True)
    subnet_allocated_percent: float | None = Field(None, frozen=True)
    subnet_used_size: int | None = Field(None, frozen=True)
    subnet_used_percent: float | None = Field(None, frozen=True)
    subnet_ip_used_size: int | None = Field(None, frozen=True)
    subnet_ip_used_percent: float | None = Field(None, frozen=True)
    subnet_ip_free_size: int | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Class system
    # ------------------------------------------------------------------
    subnet_class_name: str | None = None
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)
    site_class_params: ClassParamDict | None = Field(None, frozen=True)
    parent_subnet_class_params: ClassParamDict | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Containing space (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    site_id: int | None = Field(None, frozen=True)
    site_name: str | None = Field(None, frozen=True)
    site_description: str | None = Field(None, frozen=True)
    site_is_template: bool | None = Field(None, frozen=True)
    site_class_name: str | None = Field(None, frozen=True)
    site_parent_site_id: int | None = Field(None, frozen=True)
    tree_level: int | None = Field(None, frozen=True)
    tree_path: str | None = Field(None, frozen=True)
    tree_id_path: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Parent network (frozen — hierarchy is read-only)
    # ------------------------------------------------------------------
    parent_subnet_id: int | None = Field(None, frozen=True)
    parent_subnet_name: str | None = Field(None, frozen=True)
    parent_start_ip_addr: IPv4Address | None = Field(None, frozen=True)
    parent_end_ip_addr: IPv4Address | None = Field(None, frozen=True)
    parent_subnet_size: int | None = Field(None, frozen=True)
    parent_subnet_level: int | None = Field(None, frozen=True)
    parent_subnet_path: str | None = Field(None, frozen=True)
    parent_subnet_class_name: str | None = Field(None, frozen=True)
    parent_is_terminal: bool | None = Field(None, frozen=True)
    parent_vlsm_subnet_id: int | None = Field(None, frozen=True)
    parent_site_id: int | None = Field(None, frozen=True)
    parent_site_name: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # VLSM cross-space linkage (frozen)
    # ------------------------------------------------------------------
    vlsm_block_id: int | None = Field(None, frozen=True)
    vlsm_subnet_id: int | None = Field(None, frozen=True)
    vlsm_site_id: int | None = Field(None, frozen=True)
    vlsm_site_name: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # VLAN association (frozen)
    # ------------------------------------------------------------------
    vlmvlan_id: int | None = Field(None, frozen=True)
    vlmvlan_vlan_id: int | None = Field(None, frozen=True)
    vlmvlan_name: str | None = Field(None, frozen=True)
    vlmdomain_id: int | None = Field(None, frozen=True)
    vlmdomain_name: str | None = Field(None, frozen=True)
    vlmrange_id: int | None = Field(None, frozen=True)
    vlmrange_name: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Audit trail (frozen)
    # ------------------------------------------------------------------
    trace_creation_date: datetime | None = Field(None, frozen=True)
    trace_last_update_date: datetime | None = Field(None, frozen=True)
    trace_creation_usr_id: int | None = Field(None, frozen=True)
    trace_creation_origin_usr_id: int | None = Field(None, frozen=True)
    trace_creation_origin: str | None = Field(None, frozen=True)
    trace_creation_exec_stack: str | None = Field(None, frozen=True)
    trace_creation_usr_login: str | None = Field(None, frozen=True)
    trace_creation_origin_usr_login: str | None = Field(None, frozen=True)



    # ------------------------------------------------------------------
    # Write serialisation
    # ------------------------------------------------------------------

    def write_params(self) -> dict[str, str]:
        """Serialise dirty mutable fields to the wire format expected by ``ip_subnet_add``."""
        out = super().write_params()   # handles class_params → subnet_class_parameters etc.
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            match field:
                case "subnet":
                    pass  # emitted as subnet_addr/subnet_prefix in build_request
                case "row_enabled":
                    out[field] = self._to_int_str(int(val) if val is not None else None)
                case "lock_network_broadcast" | "is_terminal" | "is_in_orphan":
                    out[field] = self._to_bool_str(val)
                case _:
                    out[field] = "" if val is None else str(val)
        return out

    def build_request(
        self,
        operation: str,
        **kwargs: Any,
    ) -> tuple[str, str, dict[str, str]]:
        """Build an HTTP request descriptor, injecting ``subnet_addr`` and
        ``subnet_prefix`` for ``create`` operations.

        Args:
            operation: ``'info'``, ``'create'``, ``'update'``, or ``'delete'``.
            **kwargs: Passed through to the base implementation for non-create
                operations.

        Returns:
            A ``(http_verb, path, params)`` triple.

        Raises:
            ValueError: If ``site_id`` is ``None`` for a ``create`` operation.
        """
        if operation != "create":
            return super().build_request(operation, **kwargs)
        if self.site_id is None and self.site_name is None and self.parent_subnet_id is None:
            raise ValueError(
                "site_id, site_name, or parent_subnet_id is required to create a Subnet",
            )
        if self.subnet is None:
            raise ValueError("subnet address is required to create a Subnet")
        params = self.write_params()
        params["subnet_addr"] = str(self.subnet.network_address)
        params["subnet_prefix"] = str(self.subnet.prefixlen)
        if self.site_id is not None:
            params["site_id"] = str(self.site_id)
        if self.site_name is not None:
            params["site_name"] = self.site_name
        if self.parent_subnet_id is not None:
            params["parent_subnet_id"] = str(self.parent_subnet_id)
        return ("POST", type(self).solid_config.paths["add"], params)



    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:  # noqa: PLR0912, PLR0915
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)

        _BLOB_KEYS = frozenset({  # noqa: N806
            "subnet_class_parameters",
            "subnet_class_parameters_properties",
            "subnet_class_parameters_inheritance_source",
            "site_class_parameters",
            "site_class_parameters_properties",
            "parent_subnet_class_parameters",
            "parent_subnet_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                # Consumed below to build subnet — do not write to out
                case (
                    "start_ip_addr" | "end_ip_addr" |
                    "start_hostaddr" | "end_hostaddr" |
                    "subnet_size" | "subnet_prefix"
                ):
                    pass
                # Already-built IPv4Network (e.g. from model_dump() or validate_assignment
                # re-running _coerce) — preserve it; wire-data build below overrides if available
                case "subnet":
                    if isinstance(val, IPv4Network):
                        out[key] = val
                case "parent_start_ip_addr" | "parent_end_ip_addr":
                    out[key] = cls._as_hex_ipv4(val)
                case (
                    "errno" | "subnet_id" | "subnet_level" |
                    "subnet_allocated_size" |
                    "subnet_used_size" | "subnet_ip_used_size" | "subnet_ip_free_size" |
                    "waiting_status" | "row_enabled" |
                    "site_id" | "tree_level" |
                    "parent_subnet_size" | "parent_subnet_level" | "parent_site_id"
                ):
                    out[key] = cls._as_int(val)
                case (
                    "site_parent_site_id" | "parent_subnet_id" | "parent_vlsm_subnet_id" |
                    "vlsm_block_id" | "vlsm_subnet_id" | "vlsm_site_id" |
                    "vlmvlan_id" | "vlmvlan_vlan_id" |
                    "vlmdomain_id" | "vlmrange_id" |
                    "trace_creation_usr_id" | "trace_creation_origin_usr_id"
                ):
                    out[key] = cls._as_nz_int(val)
                case (
                    "subnet_is_valid" | "is_terminal" | "is_in_orphan" |
                    "lock_network_broadcast" | "site_is_template" | "parent_is_terminal"
                ):
                    out[key] = cls._as_bool(val)
                case (
                    "subnet_allocated_percent" | "subnet_used_percent" |
                    "subnet_ip_used_percent"
                ):
                    out[key] = cls._as_float(val)
                case "trace_creation_date" | "trace_last_update_date":
                    out[key] = cls._as_datetime(val)
                case _:
                    if isinstance(val, ClassParamDict):
                        out[key] = val
                    elif key in cls.model_fields:
                        out[key] = cls._as_str(val)
                    else:
                        out[key] = val

        subnet_addr: IPv4Address | None = None
        if (start_ip_addr := v.get("start_ip_addr")) is not None:
            subnet_addr = cls._as_hex_ipv4(start_ip_addr)
        if subnet_addr is None and (start_hostaddr := v.get("start_hostaddr")) is not None:
            subnet_addr = cls._as_dotted_ipv4(start_hostaddr)
        subnet_prefix = cls._as_int(v.get("subnet_prefix"))
        if subnet_prefix is None:
            subnet_size = cls._as_int(v.get("subnet_size"))
            if subnet_size is not None and subnet_size > 0:
                subnet_prefix = 33 - subnet_size.bit_length()
        if subnet_addr is not None and subnet_prefix is not None:
            out["subnet"] = IPv4Network((subnet_addr, subnet_prefix), strict=False)

        if __debug__:
            cls._assert_wire_consistency(v, out)

        if not isinstance(out.get("class_params"), ClassParamDict):
            out["class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("subnet_class_parameters")),
                cls._as_str(v.get("subnet_class_parameters_properties")),
                cls._as_str(v.get("subnet_class_parameters_inheritance_source")),
                api_prefix="subnet",
            )
        if "site_class_parameters" in v or "site_class_parameters_properties" in v:
            out["site_class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("site_class_parameters")),
                cls._as_str(v.get("site_class_parameters_properties")),
                api_prefix="site",
                frozen=True,
            )
        if "parent_subnet_class_parameters" in v or "parent_subnet_class_parameters_properties" in v:
            out["parent_subnet_class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("parent_subnet_class_parameters")),
                cls._as_str(v.get("parent_subnet_class_parameters_properties")),
                api_prefix="subnet",
                frozen=True,
            )

        return out



    @staticmethod
    def _assert_wire_consistency(v: dict[str, Any], out: dict[str, Any]) -> None:
        """Assert internal consistency of decoded wire fields.

        Called only under ``__debug__`` (i.e. skipped with ``python -O``).
        All conditions should be invariants that the server never violates.
        """
        subnet_size    = SolidServerModel._as_int(v.get("subnet_size"))  # noqa: SLF001
        start_addr_hex = SolidServerModel._as_hex_ipv4(v.get("start_ip_addr"))  # noqa: SLF001
        start_addr_dot = SolidServerModel._as_dotted_ipv4(v.get("start_hostaddr"))  # noqa: SLF001
        end_addr_hex   = SolidServerModel._as_hex_ipv4(v.get("end_ip_addr"))  # noqa: SLF001
        end_addr_dot   = SolidServerModel._as_dotted_ipv4(v.get("end_hostaddr"))  # noqa: SLF001

        if start_addr_hex is not None and start_addr_dot is not None:
            assert start_addr_hex == start_addr_dot, (
                f"start_ip_addr {start_addr_hex} disagrees with start_hostaddr {start_addr_dot}"
            )
        if end_addr_hex is not None and end_addr_dot is not None:
            assert end_addr_hex == end_addr_dot, (
                f"end_ip_addr {end_addr_hex} disagrees with end_hostaddr {end_addr_dot}"
            )
        if start_addr_hex is not None and subnet_size is not None and subnet_size > 0:
            end_addr = end_addr_dot if end_addr_dot is not None else end_addr_hex
            if end_addr is not None:
                expected_end = IPv4Address(int(start_addr_hex) + subnet_size - 1)
                assert end_addr == expected_end, (
                    f"end address {end_addr} != start {start_addr_hex} + size {subnet_size} - 1 = {expected_end}"
                )
        explicit_prefix = SolidServerModel._as_int(v.get("subnet_prefix"))  # noqa: SLF001
        if explicit_prefix is not None and subnet_size is not None and subnet_size > 0:
            expected_size = 2 ** (32 - explicit_prefix)
            assert subnet_size == expected_size, (
                f"subnet_size {subnet_size} inconsistent with subnet_prefix {explicit_prefix} "
                f"(expected {expected_size})"
            )
        parent_start: object = out.get("parent_start_ip_addr")
        parent_end:   object = out.get("parent_end_ip_addr")
        parent_size:  object = out.get("parent_subnet_size")
        if (
            isinstance(parent_start, IPv4Address) and int(parent_start) != 0 and
            isinstance(parent_end,   IPv4Address) and
            isinstance(parent_size,  int)         and parent_size > 0
        ):
            expected_parent_end = IPv4Address(int(parent_start) + parent_size - 1)
            assert parent_end == expected_parent_end, (
                f"parent_end_ip_addr {parent_end} != parent_start {parent_start} "
                f"+ size {parent_size} - 1 = {expected_parent_end}"
            )
