"""DhcpServer model (``dhcp_server_list`` / ``dhcp_server_info``) — read-only."""
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class DhcpServer(SolidServerModel):
    """A DHCPv4 server managed by SolidServer (``dhcp_server_list`` / ``dhcp_server_info``).

    DHCP servers are discovered/managed externally and are read-only from the SDK
    perspective — there is no ``dhcp_server_add`` or ``dhcp_server_delete`` service.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="dhcp_id",
        class_param_prefix="dhcp",
        tags_prefix="dhcp",
        paths=MappingProxyType({
            "list":  "rest/dhcp_server_list",
            "info":  "rest/dhcp_server_info",
            "count": "rest/dhcp_server_count",
        }),
    )

    dhcp_id: int | None = Field(None, frozen=True)
    dhcp_name: str | None = None
    dhcp_type: str | None = None
    dhcp_state: str | None = None
    dhcp_comment: str | None = None
    dhcp_version: str | None = None
    dhcp_class_name: str | None = None
    dhcp_synching: bool | None = None

    ip_addr: IPv4Address | None = Field(None, frozen=True)
    ip6_addr: str | None = None
    hostaddr: str | None = None

    isolated: bool | None = None
    tree_level: int | None = None
    tree_path: str | None = None
    total_vdhcp_members: int | None = None
    vdhcp_members_name: str | None = None
    vdhcp_arch: str | None = None
    vdhcp_parent_id: int | None = None
    vdhcp_parent_name: str | None = None
    vdhcp_parent_arch: str | None = None

    connectionprofile_name: str | None = None
    ipmdhcp_type: str | None = None
    ipmdhcp_is_package: str | None = None
    reverse_proxy_conf: str | None = None

    cluster_role: str | None = None
    cluster_peer_dhcp_id: int | None = None
    cluster_hb_hostaddr: str | None = None
    cluster_ssh_keyring_id: int | None = None

    multistatus: str | None = None
    row_enabled: RowEnabled | None = Field(None, frozen=True)
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)

        _BLOB_KEYS = frozenset({  # noqa: N806
            "dhcp_class_parameters",
            "dhcp_class_parameters_properties",
            "dhcp_class_parameters_inheritance_source",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "dhcp_id" | "row_enabled" |
                    "tree_level" | "total_vdhcp_members"
                ):
                    out[key] = cls._as_int(val)
                case "vdhcp_parent_id" | "cluster_peer_dhcp_id" | "cluster_ssh_keyring_id":
                    out[key] = cls._as_nz_int(val)
                case "dhcp_synching" | "isolated":
                    out[key] = cls._as_bool(val)
                case "ip_addr":
                    out[key] = cls._as_hex_ipv4(val)
                case _:
                    if isinstance(val, ClassParamDict):
                        out[key] = val
                    elif key in cls.model_fields:
                        out[key] = cls._as_str(val)
                    else:
                        out[key] = val

        if not isinstance(out.get("class_params"), ClassParamDict):
            out["class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("dhcp_class_parameters")),
                cls._as_str(v.get("dhcp_class_parameters_properties")),
                cls._as_str(v.get("dhcp_class_parameters_inheritance_source")),
                api_prefix="dhcp",
            )

        return out
