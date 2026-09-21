"""DhcpRange model (``dhcp_range_list`` / ``dhcp_range_info``)."""
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class DhcpRange(SolidServerModel):
    """A DHCPv4 address range within a scope (``dhcp_range_list`` / ``dhcp_range_info``).

    Mutable fields (writable via ``Session.flush()``):
        ``dhcprange_start_addr``, ``dhcprange_end_addr``, ``dhcprange_name``,
        ``dhcprange_class_name``, ``dhcprange_acl``, ``row_enabled``, ``class_params``.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="dhcprange_id",
        class_param_prefix="dhcprange",
        tags_prefix="dhcprange",
        create_fields=frozenset({
            "dhcpscope_id",
            "dhcp_id",
            "dhcp_name",
            "dhcprange_start_addr",
            "dhcprange_end_addr",
            "dhcprange_name",
            "dhcprange_class_name",
            "dhcprange_acl",
            "class_params",
        }),
        paths=MappingProxyType({
            "list":   "rest/dhcp_range_list",
            "info":   "rest/dhcp_range_info",
            "count":  "rest/dhcp_range_count",
            "add":    "rest/dhcp_range_add",
            "delete": "rest/dhcp_range_delete",
        }),
        parent_fields=MappingProxyType({"dhcpscope_id": "dhcpscope_id"}),
        hex_ip_columns=frozenset({"dhcprange_start_ip_addr", "dhcprange_end_ip_addr", "ip_addr"}),
    )

    dhcprange_id: int | None = Field(None, frozen=True)
    dhcpscope_id: int | None = None
    dhcp_id: int | None = None
    dhcp_name: str | None = None
    dhcp_type: str | None = None
    dhcp_class_name: str | None = None
    dhcp_version: str | None = None

    dhcprange_start_addr: IPv4Address | None = None
    dhcprange_end_addr: IPv4Address | None = None
    dhcprange_start_ip_addr: IPv4Address | None = None
    dhcprange_end_ip_addr: IPv4Address | None = None
    dhcprange_size: int | None = None
    dhcprange_name: str | None = None
    dhcprange_class_name: str | None = None
    dhcprange_acl: str | None = None
    dhcprange_lease_count: int | None = None
    dhcprange_lease_percent: float | None = None

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
            "dhcprange_class_parameters",
            "dhcprange_class_parameters_properties",
            "dhcprange_class_parameters_inheritance_source",
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
                    "errno" | "dhcprange_id" | "dhcpscope_id" | "dhcp_id" | "row_enabled" |
                    "dhcprange_size" | "dhcprange_lease_count" |
                    "delayed_create_time" | "delayed_delete_time"
                ):
                    out[key] = cls._as_int(val)
                case "dhcpscope_site_id" | "dhcpsn_id" | "vdhcp_parent_id":
                    out[key] = cls._as_nz_int(val)
                case "dhcprange_lease_percent":
                    out[key] = cls._as_float(val)
                case "dhcprange_start_ip_addr" | "dhcprange_end_ip_addr" | "ip_addr":
                    out[key] = cls._as_hex_ipv4(val)
                case "dhcprange_start_addr" | "dhcprange_end_addr" | "dhcpscope_net_addr" | "dhcpscope_net_mask":
                    out[key] = cls._as_dotted_ipv4(val)
                case _:
                    if isinstance(val, ClassParamDict):
                        out[key] = val
                    elif key in cls.model_fields:
                        out[key] = cls._as_str(val) if isinstance(val, (str, type(None))) else val
                    else:
                        out[key] = val

        cls._coerce_class_params(out, v)

        return out
