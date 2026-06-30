"""DhcpScope model (``dhcp_scope_list`` / ``dhcp_scope_info``)."""
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class DhcpScope(SolidServerModel):
    """A DHCPv4 scope (subnet) managed by SolidServer (``dhcp_scope_list`` / ``dhcp_scope_info``).

    Mutable fields (writable via ``Session.flush()``):
        ``dhcp_id``, ``dhcpscope_name``, ``dhcpscope_class_name``,
        ``dhcpfailover_id``, ``dhcpsn_id``, ``row_enabled``, ``class_params``.

    ``dhcpscope_net_addr`` and ``dhcpscope_net_mask`` are "Can be edited: No" and are
    frozen after creation, but are included in ``create_fields`` for the initial POST.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="dhcpscope_id",
        class_param_prefix="dhcpscope",
        tags_prefix="dhcpscope",
        create_fields=frozenset({
            "dhcp_id",
            "dhcpscope_net_addr",
            "dhcpscope_net_mask",
            "dhcpscope_name",
            "dhcpscope_class_name",
            "dhcpfailover_id",
            "dhcpsn_id",
            "class_params",
        }),
        paths=MappingProxyType({
            "list":   "rest/dhcp_scope_list",
            "info":   "rest/dhcp_scope_info",
            "count":  "rest/dhcp_scope_count",
            "add":    "rest/dhcp_scope_add",
            "delete": "rest/dhcp_scope_delete",
        }),
        parent_fields=MappingProxyType({"dhcp_id": "dhcp_id"}),
        hex_ip_columns=frozenset({"dhcpscope_start_ip_addr", "dhcpscope_end_ip_addr", "ip_addr"}),
    )

    dhcpscope_id: int | None = Field(None, frozen=True)
    dhcp_id: int | None = None
    dhcp_name: str | None = None
    dhcp_type: str | None = None
    dhcp_class_name: str | None = None
    dhcp_version: str | None = None

    dhcpscope_net_addr: IPv4Address | None = Field(None, frozen=True)
    dhcpscope_net_mask: IPv4Address | None = Field(None, frozen=True)
    dhcpscope_start_ip_addr: IPv4Address | None = None
    dhcpscope_end_ip_addr: IPv4Address | None = None
    dhcpscope_size: int | None = None
    dhcpscope_name: str | None = None
    dhcpscope_class_name: str | None = None
    dhcpscope_site_id: int | None = None
    dhcpscope_site_name: str | None = None

    dhcpsn_id: int | None = None
    dhcpsn_name: str | None = None
    dhcpfailover_id: int | None = None
    dhcpfailover_name: str | None = None

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
            "dhcpscope_class_parameters",
            "dhcpscope_class_parameters_properties",
            "dhcpscope_class_parameters_inheritance_source",
            "dhcp_class_parameters",
            "dhcp_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "dhcpscope_id" | "dhcp_id" | "row_enabled" |
                    "dhcpscope_size" | "delayed_create_time" | "delayed_delete_time"
                ):
                    out[key] = cls._as_int(val)
                case "dhcpscope_site_id" | "dhcpsn_id" | "dhcpfailover_id" | "vdhcp_parent_id":
                    out[key] = cls._as_nz_int(val)
                case "dhcpscope_start_ip_addr" | "dhcpscope_end_ip_addr" | "ip_addr":
                    out[key] = cls._as_hex_ipv4(val)
                case "dhcpscope_net_addr" | "dhcpscope_net_mask":
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
