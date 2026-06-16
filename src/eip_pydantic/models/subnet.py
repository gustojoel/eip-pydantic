import math
from datetime import datetime
from ipaddress import IPv4Address
from typing import Any, ClassVar, Literal, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.exceptions import InternalError
from eip_pydantic.models.base import RowEnabled, SolidServerModel



class FreeSubnet(SolidServerModel):
    """One candidate slot returned by ``ip_find_free_subnet``.

    Each row represents an available address range that could hold a new
    subnet of the requested size.  Results are ordered by ``cost`` ascending
    (lowest cost = least fragmentation).
    """

    _find_free_path: ClassVar[str] = "rpc/ip_find_free_subnet"

    start_ip_addr: IPv4Address | None = None
    start_hostaddr: IPv4Address | None = None
    block_name: str | None = None
    cost: int | None = None
    block_id: int | None = None
    site_id: int | None = None

    @classmethod
    def build_class_request(  # noqa: PLR0912
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
        return ("OPTIONS", cls._find_free_path, params)

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

    _class_param_prefix: ClassVar[str | None] = "subnet"
    tags_prefix: ClassVar[str] = "network"
    _pk_field: ClassVar[str] = "subnet_id"
    _list_path: ClassVar[str] = "rest/ip_block_subnet_list"
    _info_path: ClassVar[str] = "rest/ip_block_subnet_info"
    _count_path: ClassVar[str] = "rest/ip_block_subnet_count"
    _add_path: ClassVar[str] = "rest/ip_subnet_add"
    _delete_path: ClassVar[str] = "rest/ip_block_subnet_delete"

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------
    subnet_id: int | None = Field(None, frozen=True)
    type: Literal["block", "subnet"] | None = Field(None, frozen=True)
    subnet_name: str | None = None
    subnet_level: int | None = Field(None, frozen=True)   # 0 = block, 1+ = subnet depth
    subnet_path: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # IP addressing (frozen — change of range requires delete + recreate)
    # ------------------------------------------------------------------
    start_ip_addr: IPv4Address | None = Field(None, frozen=True)
    start_hostaddr: IPv4Address | None = Field(None, frozen=True)
    end_ip_addr: IPv4Address | None = Field(None, frozen=True)
    end_hostaddr: IPv4Address | None = Field(None, frozen=True)
    subnet_size: int | None = Field(None, frozen=True)
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
            ValueError: If ``start_hostaddr``, ``subnet_size``, or ``site_id``
                is ``None`` for a ``create`` operation.
        """
        if operation != "create":
            return super().build_request(operation, **kwargs)
        if self.start_hostaddr is None or self.subnet_size is None or self.site_id is None:
            raise ValueError(
                "start_hostaddr, subnet_size, and site_id are required to create a Subnet",
            )
        params = self.write_params()
        params["subnet_addr"] = str(self.start_hostaddr)
        params["subnet_prefix"] = str(32 - int(math.log2(self.subnet_size)))
        params["site_id"] = str(self.site_id)
        return ("POST", type(self)._add_path, params)  # noqa: SLF001

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:  # noqa: PLR0912
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
                case "start_ip_addr" | "end_ip_addr" | "parent_start_ip_addr" | "parent_end_ip_addr":
                    out[key] = cls._as_hex_ipv4(val)
                case "start_hostaddr" | "end_hostaddr":
                    out[key] = cls._as_dotted_ipv4(val)
                case (
                    "errno" | "subnet_id" | "subnet_level" |
                    "subnet_size" | "subnet_allocated_size" |
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
