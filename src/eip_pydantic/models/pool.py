from datetime import datetime
from ipaddress import IPv4Address
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerModel



class Pool(SolidServerModel):
    """An EfficientIP IPv4 address pool (``ip_pool_list`` / ``ip_pool_info``).

    A pool defines a contiguous range of addresses within a subnet that may be
    reserved for dynamic allocation (e.g. linked to a DHCP scope).  Every pool
    belongs to exactly one Subnet and, transitively, one Space.

    Mutable fields (writable via ``Session.flush()``):
        ``pool_name``, ``pool_read_only``, ``pool_class_name``, ``class_params``.

    All address, audit, and linkage fields are frozen and reflect
    server-managed state.  Changing the address range requires delete + recreate.
    """

    _class_param_prefix: ClassVar[str | None] = "pool"
    tags_prefix: ClassVar[str] = "pool"
    _pk_field: ClassVar[str] = "pool_id"
    _list_path: ClassVar[str] = "rest/ip_pool_list"
    _info_path: ClassVar[str] = "rest/ip_pool_info"
    _count_path: ClassVar[str] = "rest/ip_pool_count"
    _add_path: ClassVar[str] = "rest/ip_pool_add"
    _delete_path: ClassVar[str] = "rest/ip_pool_delete"

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------
    pool_id: int | None = Field(None, frozen=True)
    pool_name: str | None = None
    pool_read_only: bool | None = None     # if True, IPs in pool cannot be assigned

    # ------------------------------------------------------------------
    # Address range (frozen — change requires delete + recreate)
    # ------------------------------------------------------------------
    start_ip_addr: IPv4Address | None = Field(None, frozen=True)       # hex
    start_hostaddr: IPv4Address | None = Field(None, frozen=True)      # dotted
    end_ip_addr: IPv4Address | None = Field(None, frozen=True)         # hex
    end_hostaddr: IPv4Address | None = Field(None, frozen=True)        # dotted
    pool_start_ip_addr: IPv4Address | None = Field(None, frozen=True)  # hex (alias)
    pool_end_ip_addr: IPv4Address | None = Field(None, frozen=True)    # hex (alias)
    pool_size: int | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Class system
    # ------------------------------------------------------------------
    pool_class_name: str | None = None
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)
    site_class_params: ClassParamDict | None = Field(None, frozen=True)
    subnet_class_params: ClassParamDict | None = Field(None, frozen=True)  # _info only

    # ------------------------------------------------------------------
    # Parent subnet (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    parent_subnet_id: int | None = Field(None, frozen=True)
    parent_subnet_name: str | None = Field(None, frozen=True)
    parent_subnet_size: int | None = Field(None, frozen=True)
    parent_subnet_class_name: str | None = Field(None, frozen=True)
    vlsm_subnet_id: int | None = Field(None, frozen=True)
    vlsm_block_id: int | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Containing subnet (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    subnet_id: int | None = Field(None, frozen=True)
    subnet_name: str | None = Field(None, frozen=True)
    subnet_start_ip_addr: IPv4Address | None = Field(None, frozen=True)
    subnet_end_ip_addr: IPv4Address | None = Field(None, frozen=True)
    subnet_size: int | None = Field(None, frozen=True)
    subnet_class_name: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Containing space (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    site_id: int | None = Field(None, frozen=True)
    site_name: str | None = Field(None, frozen=True)
    site_description: str | None = Field(None, frozen=True)
    site_is_template: bool | None = Field(None, frozen=True)
    site_class_name: str | None = Field(None, frozen=True)
    tree_path: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    row_enabled: RowEnabled | None = None
    multistatus: str | None = Field(None, frozen=True)

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
        """Serialise dirty mutable fields to the wire format expected by ``ip_pool_add``."""
        out = super().write_params()   # handles class_params → pool_class_parameters etc.
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            match field:
                case "pool_read_only":
                    out[field] = self._to_bool_str(val)
                case "row_enabled":
                    out[field] = self._to_int_str(int(val) if val is not None else None)
                case _:
                    out[field] = "" if val is None else str(val)
        return out

    def build_request(
        self,
        operation: str,
        **kwargs: Any,
    ) -> tuple[str, str, dict[str, str]]:
        """Build an HTTP request descriptor, injecting address range for ``create``.

        Raises:
            ValueError: If ``start_hostaddr``, ``end_hostaddr``, or ``subnet_id``
                is ``None`` for a ``create`` operation.
        """
        if operation != "create":
            return super().build_request(operation, **kwargs)
        if self.start_hostaddr is None or self.end_hostaddr is None or self.subnet_id is None:
            raise ValueError(
                "start_hostaddr, end_hostaddr, and subnet_id are required to create a Pool",
            )
        params = self.write_params()
        params["start_addr"] = str(self.start_hostaddr)
        params["end_addr"] = str(self.end_hostaddr)
        params["subnet_id"] = str(self.subnet_id)
        return ("POST", type(self)._add_path, params)  # noqa: SLF001

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:  # noqa: PLR0912
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)

        _BLOB_KEYS = frozenset({  # noqa: N806
            "pool_class_parameters",
            "pool_class_parameters_properties",
            "pool_class_parameters_inheritance_source",
            "site_class_parameters",
            "site_class_parameters_properties",
            "subnet_class_parameters",
            "subnet_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "start_ip_addr" | "end_ip_addr" |
                    "pool_start_ip_addr" | "pool_end_ip_addr" |
                    "subnet_start_ip_addr" | "subnet_end_ip_addr"
                ):
                    out[key] = cls._as_hex_ipv4(val)
                case "start_hostaddr" | "end_hostaddr":
                    out[key] = cls._as_dotted_ipv4(val)
                case (
                    "errno" | "pool_id" | "pool_size" |
                    "parent_subnet_size" | "subnet_size"
                ):
                    out[key] = cls._as_int(val)
                case (
                    "subnet_id" | "site_id" |
                    "parent_subnet_id" | "vlsm_subnet_id" | "vlsm_block_id" |
                    "trace_creation_usr_id" | "trace_creation_origin_usr_id"
                ):
                    out[key] = cls._as_nz_int(val)
                case "row_enabled":
                    out[key] = cls._as_int(val)
                case "pool_read_only" | "site_is_template":
                    out[key] = cls._as_bool(val)
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
                cls._as_str(v.get("pool_class_parameters")),
                cls._as_str(v.get("pool_class_parameters_properties")),
                cls._as_str(v.get("pool_class_parameters_inheritance_source")),
                api_prefix="pool",
            )
        if "site_class_parameters" in v or "site_class_parameters_properties" in v:
            out["site_class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("site_class_parameters")),
                cls._as_str(v.get("site_class_parameters_properties")),
                api_prefix="site",
                frozen=True,
            )
        if "subnet_class_parameters" in v or "subnet_class_parameters_properties" in v:
            out["subnet_class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("subnet_class_parameters")),
                cls._as_str(v.get("subnet_class_parameters_properties")),
                api_prefix="subnet",
                frozen=True,
            )

        return out
