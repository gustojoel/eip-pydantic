"""DhcpFailoverChannel model (``dhcp_failover_list`` / ``dhcp_failover_info``) — read-only."""
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.models.base import SolidServerConfig, SolidServerModel



# dhcp_failover_set_partner_down is intentionally omitted: it is an emergency
# state-change operation (forcing a channel into PARTNER-DOWN mode) that should
# not be called programmatically without safeguards that go beyond this SDK's
# scope.  Use the SolidServer GUI for that operation.


class DhcpFailoverChannel(SolidServerModel):
    """A DHCPv4 failover channel (``dhcp_failover_list`` / ``dhcp_failover_info``).

    Failover channels are read-only from the SDK perspective — there is no
    ``dhcp_failover_add`` or ``dhcp_failover_delete`` service.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="dhcpfailover_id",
        class_param_prefix=None,
        tags_prefix="dhcpfailover",
        paths=MappingProxyType({
            "list":  "rest/dhcp_failover_list",
            "info":  "rest/dhcp_failover_info",
            "count": "rest/dhcp_failover_count",
        }),
    )

    dhcpfailover_id: int | None = Field(None, frozen=True)

    dhcp_id: int | None = None
    dhcp_name: str | None = None
    dhcp_type: str | None = None
    dhcp_state: str | None = None
    vdhcp_parent_id: int | None = None
    cluster_role: str | None = None

    dhcpfailover_name: str | None = None
    dhcpfailover_addr: IPv4Address | None = None
    dhcpfailover_port: int | None = None
    peer_dhcp_id: int | None = None
    dhcpfailover_peer_addr: IPv4Address | None = None
    dhcpfailover_peer_port: int | None = None
    dhcpfailover_split: str | None = None  # internal use, not documented by API
    dhcpfailover_state: str | None = None
    dhcpfailover_type: str | None = None
    dhcpfailover_auto_partner_down: int | None = None
    dhcpfailover_mclt: int | None = None

    delayed_create_time: int | None = None
    delayed_delete_time: int | None = None

    ip_addr: IPv4Address | None = Field(None, frozen=True)
    ip6_addr: str | None = None
    hostaddr: str | None = None
    multistatus: str | None = Field(None, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)
        out: dict[str, Any] = {}
        for key, val in v.items():
            match key:
                case (
                    "errno" | "dhcpfailover_id" | "dhcp_id" |
                    "dhcpfailover_port" | "dhcpfailover_peer_port" |
                    "dhcpfailover_auto_partner_down" | "dhcpfailover_mclt" |
                    "delayed_create_time" | "delayed_delete_time"
                ):
                    out[key] = cls._as_int(val)
                case "vdhcp_parent_id" | "peer_dhcp_id":
                    out[key] = cls._as_nz_int(val)
                case "ip_addr":
                    out[key] = cls._as_hex_ipv4(val)
                case "dhcpfailover_addr" | "dhcpfailover_peer_addr":
                    out[key] = cls._as_dotted_ipv4(val)
                case _:
                    if key in cls.model_fields:
                        out[key] = cls._as_str(val)
                    else:
                        out[key] = val
        return out
