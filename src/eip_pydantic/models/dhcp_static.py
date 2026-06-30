"""DhcpStatic model (``dhcp_static_list`` / ``dhcp_static_info``)."""
from datetime import datetime
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class DhcpStatic(SolidServerModel):
    """A DHCPv4 static host reservation (``dhcp_static_list`` / ``dhcp_static_info``).

    Most output fields use the ``dhcphost_*`` prefix despite the services being named
    ``dhcp_static_*``.  The PK field is ``dhcphost_id``.

    Mutable fields (writable via ``Session.flush()``):
        ``dhcp_id``, ``dhcpscope_id``, ``dhcphost_addr``, ``dhcphost_mac_addr``,
        ``dhcphost_name``, ``dhcphost_domain``, ``dhcphost_identifier``,
        ``dhcphost_class_name``, ``dhcpgroup_id``, ``row_enabled``, ``class_params``.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="dhcphost_id",
        class_param_prefix="dhcphost",
        tags_prefix="dhcphost",
        create_fields=frozenset({
            "dhcp_id",
            "dhcpscope_id",
            "dhcphost_addr",
            "dhcphost_mac_addr",
            "dhcphost_identifier",
            "dhcphost_name",
            "dhcphost_domain",
            "dhcphost_class_name",
            "dhcpgroup_id",
            "class_params",
        }),
        paths=MappingProxyType({
            "list":   "rest/dhcp_static_list",
            "info":   "rest/dhcp_static_info",
            "count":  "rest/dhcp_static_count",
            "add":    "rest/dhcp_static_add",
            "delete": "rest/dhcp_static_delete",
        }),
        parent_fields=MappingProxyType({"dhcpscope_id": "dhcpscope_id"}),
        hex_ip_columns=frozenset({"dhcphost_ip_addr", "ip_addr"}),
    )

    dhcphost_id: int | None = Field(None, frozen=True)
    dhcp_id: int | None = None
    dhcpscope_id: int | None = None
    dhcp_name: str | None = None
    dhcp_type: str | None = None
    dhcp_class_name: str | None = None
    dhcp_version: str | None = None

    dhcphost_addr: IPv4Address | None = None
    dhcphost_ip_addr: IPv4Address | None = None
    dhcphost_mac_addr: str | None = None
    dhcphost_name: str | None = None
    dhcphost_domain: str | None = None
    dhcphost_identifier: str | None = None
    dhcphost_class_name: str | None = None
    dhcphost_last_seen: datetime | None = None
    dhcphost_expire_time: datetime | None = None
    mac_vendor: str | None = None

    dhcpgroup_id: int | None = None
    dhcpgroup_name: str | None = None

    dhcpscope_net_addr: IPv4Address | None = None
    dhcpscope_net_mask: IPv4Address | None = None
    dhcpscope_site_id: int | None = None
    dhcpscope_site_name: str | None = None

    dhcpsn_id: int | None = None
    dhcpsn_name: str | None = None

    vdhcp_parent_id: int | None = None
    vdhcp_parent_name: str | None = None
    vdhcp_arch: str | None = None

    delayed_create_time: int | None = None
    delayed_delete_time: int | None = None

    ip_addr: IPv4Address | None = None
    ip6_addr: str | None = None
    hostaddr: str | None = None
    multistatus: str | None = Field(None, frozen=True)

    row_enabled: RowEnabled | None = None
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)

    def write_params(self) -> dict[str, str]:  # noqa: D102
        out = super().write_params()
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            match field:
                case "row_enabled":
                    out[field] = self._to_int_str(int(val) if val is not None else None)
                case _:
                    out[field] = "" if val is None else str(val)
        return out

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)

        _BLOB_KEYS = frozenset({  # noqa: N806
            "dhcphost_class_parameters",
            "dhcphost_class_parameters_properties",
            "dhcphost_class_parameters_inheritance_source",
            "dhcpgroup_class_parameters",
            "dhcpgroup_class_parameters_properties",
            "dhcpscope_class_parameters",
            "dhcpscope_class_parameters_properties",
            "dhcp_class_parameters",
            "dhcp_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "dhcphost_id" | "dhcp_id" | "dhcpscope_id" | "row_enabled" |
                    "delayed_create_time" | "delayed_delete_time"
                ):
                    out[key] = cls._as_int(val)
                case "dhcpscope_site_id" | "dhcpsn_id" | "dhcpgroup_id" | "vdhcp_parent_id":
                    out[key] = cls._as_nz_int(val)
                case "dhcphost_last_seen" | "dhcphost_expire_time":
                    out[key] = cls._as_datetime(val)
                case "dhcphost_addr" | "dhcpscope_net_addr" | "dhcpscope_net_mask":
                    out[key] = cls._as_dotted_ipv4(val)
                case "dhcphost_ip_addr" | "ip_addr":
                    out[key] = cls._as_hex_ipv4(val)
                case _:
                    if isinstance(val, ClassParamDict):
                        out[key] = val
                    elif key in cls.model_fields:
                        out[key] = cls._as_str(val) if isinstance(val, (str, type(None))) else val
                    else:
                        out[key] = val

        cls._coerce_class_params(out, v)

        return out
