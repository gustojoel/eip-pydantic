"""IpAddress model (``ip_address_list`` / ``ip_address_info``)."""
from datetime import datetime
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import SolidServerConfig, SolidServerModel



class IpAddress(SolidServerModel):
    """An EfficientIP IPv4 address record (``ip_address_list`` / ``ip_address_info``).

    Represents a single IPv4 address entry.  The ``type`` field distinguishes
    used addresses (``"ip"``) from free address ranges (``"free"``).  An address
    always belongs to a Subnet and Space; it may optionally belong to a Pool.

    The API uses two paths for write operations: ``ip_add`` (POST to create,
    PUT to update) and ``ip_delete`` (DELETE).

    Mutable fields (writable via ``Session.flush()``):
        ``name``, ``mac_addr``, ``ip_class_name``, ``ip_class_parameters``,
        ``ip_class_parameters_properties``.

    The IP address itself (``hostaddr`` / ``ip_addr``) is frozen.  To
    reallocate an address, delete and recreate the record.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="ip_id",
        class_param_prefix="ip",
        tags_prefix="ip",
        create_fields=frozenset({
            "site_id", "site_name",   # site_name: alternative to site_id per ip_add API
            "hostaddr",
            "subnet_id",
            "name", "mac_addr", "ip_class_name", "class_params",
        }),
        paths=MappingProxyType({
            "list":   "rest/ip_address_list",
            "info":   "rest/ip_address_info",
            "count":  "rest/ip_address_count",
            "add":    "rest/ip_add",
            "delete": "rest/ip_delete",
        }),
    )

    # ------------------------------------------------------------------
    # Record type and free-range fields
    # ------------------------------------------------------------------
    type: str | None = Field(None, frozen=True)                       # "ip" or "free"
    free_start_ip_addr: IPv4Address | None = Field(None, frozen=True) # hex
    free_end_ip_addr: IPv4Address | None = Field(None, frozen=True)   # hex
    free_scope_size: int | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------
    ip_id: int | None = Field(None, frozen=True)
    name: str | None = None
    ip_alias: str | None = Field(None, frozen=True)    # comma-separated aliases

    # ------------------------------------------------------------------
    # IP address (frozen — change requires delete + recreate)
    # ------------------------------------------------------------------
    hostaddr: IPv4Address = Field(frozen=True) # required
    @property
    def ip_addr(self) -> IPv4Address:  # noqa: D102
        return self.hostaddr

    # ------------------------------------------------------------------
    # MAC address (mutable)
    # ------------------------------------------------------------------
    mac_addr: str | None = None

    # ------------------------------------------------------------------
    # Class system
    # ------------------------------------------------------------------
    ip_class_name: str | None = None
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)

    # ------------------------------------------------------------------
    # Containing space (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    site_id: int | None = Field(None, frozen=True)
    site_name: str | None = Field(None, frozen=True)
    site_description: str | None = Field(None, frozen=True)
    site_is_template: bool | None = Field(None, frozen=True)
    site_class_name: str | None = Field(None, frozen=True)
    site_class_params: ClassParamDict | None = Field(None, frozen=True)
    tree_level: int | None = Field(None, frozen=True)
    tree_path: str | None = Field(None, frozen=True)
    tree_id_path: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Parent subnet (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    parent_subnet_id: int | None = Field(None, frozen=True)
    parent_subnet_name: str | None = Field(None, frozen=True)
    parent_subnet_size: int | None = Field(None, frozen=True)
    parent_vlsm_subnet_id: int | None = Field(None, frozen=True)
    parent_subnet_class_name: str | None = Field(None, frozen=True)
    parent_subnet_start_ip_addr: IPv4Address | None = Field(None, frozen=True)    # hex
    parent_subnet_start_hostaddr: IPv4Address | None = Field(None, frozen=True)   # dotted
    parent_subnet_end_ip_addr: IPv4Address | None = Field(None, frozen=True)      # hex
    parent_subnet_end_hostaddr: IPv4Address | None = Field(None, frozen=True)     # dotted

    # ------------------------------------------------------------------
    # Containing subnet (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    subnet_id: int | None = Field(None, frozen=True)
    subnet_name: str | None = Field(None, frozen=True)
    subnet_start_ip_addr: IPv4Address | None = Field(None, frozen=True)    # hex
    subnet_start_hostaddr: IPv4Address | None = Field(None, frozen=True)   # dotted
    subnet_end_ip_addr: IPv4Address | None = Field(None, frozen=True)      # hex
    subnet_end_hostaddr: IPv4Address | None = Field(None, frozen=True)     # dotted
    subnet_size: int | None = Field(None, frozen=True)
    subnet_is_terminal: bool | None = Field(None, frozen=True)
    lock_network_broadcast: bool | None = Field(None, frozen=True)
    subnet_class_name: str | None = Field(None, frozen=True)
    subnet_class_params: ClassParamDict | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Containing pool (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    pool_id: int | None = Field(None, frozen=True)
    pool_name: str | None = Field(None, frozen=True)
    pool_read_only: bool | None = Field(None, frozen=True)
    pool_row_enabled: str | None = Field(None, frozen=True)   # internal, undocumented
    pool_size: int | None = Field(None, frozen=True)
    pool_start_ip_addr: IPv4Address | None = Field(None, frozen=True)   # hex
    pool_end_ip_addr: IPv4Address | None = Field(None, frozen=True)     # hex
    pool_class_name: str | None = Field(None, frozen=True)
    pool_class_params: ClassParamDict | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # NetChange linkage (frozen)
    # ------------------------------------------------------------------
    iplnetdev_name: str | None = Field(None, frozen=True)
    iplnetdev_id: int | None = Field(None, frozen=True)
    iplport_name: str | None = Field(None, frozen=True)
    iplport_slotnumber: str | None = Field(None, frozen=True)
    iplport_portnumber: str | None = Field(None, frozen=True)
    iplport_ifvlan: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Device Manager linkage (frozen)
    # ------------------------------------------------------------------
    hostdev_name: str | None = Field(None, frozen=True)
    hostdev_id: int | None = Field(None, frozen=True)
    hostiface_name: str | None = Field(None, frozen=True)
    hostiface_id: int | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Auto-tagged class params (always returned by ip_address_list)
    # ------------------------------------------------------------------
    tag_pool_dhcprange: str | None = Field(None, frozen=True)
    tag_container_dhcpstatic: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # DHCP linkage (frozen)
    # ------------------------------------------------------------------
    dhcphost_id: int | None = Field(None, frozen=True)
    dhcplease_id: int | None = Field(None, frozen=True)
    last_seen: datetime | None = Field(None, frozen=True)
    dhcplease_end_time: datetime | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
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
        """Serialise dirty mutable fields to the wire format expected by ``ip_add``."""
        out = super().write_params()   # handles class_params → ip_class_parameters etc.
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            out[field] = "" if val is None else str(val)
        return out

    def build_request(
        self,
        operation: str,
        **kwargs: Any,
    ) -> tuple[str, str, dict[str, str]]:
        """Build an HTTP request descriptor, injecting ``hostaddr`` for ``create``.

        Raises:
            ValueError: If ``hostaddr`` or ``site_id`` is ``None`` for a
                ``create`` operation.
        """
        if operation != "create":
            return super().build_request(operation, **kwargs)
        if self.site_id is None and self.site_name is None:
            raise ValueError("site_id or site_name is required to create an IpAddress")
        params = self.write_params()
        params["hostaddr"] = str(self.hostaddr)
        if self.site_id is not None:
            params["site_id"] = str(self.site_id)
        if self.site_name is not None:
            params["site_name"] = self.site_name
        if self.subnet_id is not None:
            params["subnet_id"] = str(self.subnet_id)
        return ("POST", type(self).solid_config.paths["add"], params)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:  # noqa: PLR0912
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)

        _BLOB_KEYS = frozenset({  # noqa: N806
            "ip_class_parameters",
            "ip_class_parameters_properties",
            "ip_class_parameters_inheritance_source",
            "site_class_parameters",
            "site_class_parameters_properties",
            "subnet_class_parameters",
            "subnet_class_parameters_properties",
            "pool_class_parameters",
            "pool_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case ("ip_addr"):
                    pass
                case (
                    "free_start_ip_addr" | "free_end_ip_addr" |
                    "pool_start_ip_addr" | "pool_end_ip_addr" |
                    "subnet_start_ip_addr" | "subnet_end_ip_addr" |
                    "parent_subnet_start_ip_addr" | "parent_subnet_end_ip_addr"
                ):
                    out[key] = cls._as_hex_ipv4(val)
                case (
                    "hostaddr" |
                    "subnet_start_hostaddr" | "subnet_end_hostaddr" |
                    "parent_subnet_start_hostaddr" | "parent_subnet_end_hostaddr"
                ):
                    out[key] = cls._as_dotted_ipv4(val)
                case (
                    "errno" | "ip_id" |
                    "free_scope_size" | "tree_level" |
                    "parent_subnet_size" | "subnet_size" | "pool_size"
                ):
                    out[key] = cls._as_int(val)
                case (
                    "site_id" | "subnet_id" | "pool_id" |
                    "parent_subnet_id" | "parent_vlsm_subnet_id" |
                    "iplnetdev_id" | "dhcphost_id" | "dhcplease_id" |
                    "hostdev_id" | "hostiface_id" |
                    "trace_creation_usr_id" | "trace_creation_origin_usr_id"
                ):
                    out[key] = cls._as_nz_int(val)
                case (
                    "site_is_template" | "subnet_is_terminal" |
                    "lock_network_broadcast" | "pool_read_only"
                ):
                    out[key] = cls._as_bool(val)
                case (
                    "trace_creation_date" | "trace_last_update_date" |
                    "last_seen" | "dhcplease_end_time"
                ):
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
                cls._as_str(v.get("ip_class_parameters")),
                cls._as_str(v.get("ip_class_parameters_properties")),
                cls._as_str(v.get("ip_class_parameters_inheritance_source")),
                api_prefix="ip",
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
        if "pool_class_parameters" in v or "pool_class_parameters_properties" in v:
            out["pool_class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("pool_class_parameters")),
                cls._as_str(v.get("pool_class_parameters_properties")),
                api_prefix="pool",
                frozen=True,
            )

        return out
