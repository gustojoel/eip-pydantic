"""DnsServer model (``dns_server_list`` / ``dns_server_info``) — read-only."""
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class DnsServer(SolidServerModel):
    """A DNS server managed by SolidServer (``dns_server_list`` / ``dns_server_info``).

    DNS servers are discovered/managed externally and are read-only from the SDK
    perspective — there is no ``dns_server_add`` or ``dns_server_delete`` service.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="dns_id",
        class_param_prefix="dns",
        tags_prefix="dns",
        paths=MappingProxyType({
            "list":  "rest/dns_server_list",
            "info":  "rest/dns_server_info",
            "count": "rest/dns_server_count",
        }),
        hex_ip_columns=frozenset({"ip_addr"}),
    )

    dns_id: int | None = Field(None, frozen=True)
    dns_name: str | None = None
    dns_type: str | None = None
    dns_comment: str | None = None
    dns_version: str | None = None
    dns_state: str | None = None
    dns_class_name: str | None = None
    dns_role: str | None = None

    dns_notify: str | None = None
    dns_also_notify: str | None = None
    dns_allow_query: str | None = None
    dns_allow_query_cache: str | None = None
    dns_allow_transfer: str | None = None
    dns_allow_recursion: str | None = None
    dns_recursion: str | None = None
    dns_forwarders: str | None = None
    dns_forward: str | None = None

    dns_rpz_recursive_only: bool | None = None
    dns_rpz_break_dnssec: bool | None = None
    dns_rpz_qname_wait_recurse: bool | None = None
    dns_rpz_max_policy_ttl: int | None = None
    dns_rpz_min_ns_dots: int | None = None

    dns_key_name: str | None = None
    dns_key_value: str | None = None
    dns_key_proto: str | None = None

    gss_keytab_id: int | None = None
    gss_enabled: bool | None = None

    tree_level: int | None = Field(None, frozen=True)
    tree_path: str | None = Field(None, frozen=True)
    total_vdns_members: int | None = None
    vdns_members_name: str | None = None
    vdns_arch: str | None = None
    vdns_parent_id: int | None = None
    vdns_parent_name: str | None = None
    vdns_parent_arch: str | None = None
    vdns_public_ns_list: str | None = None

    ip_addr: IPv4Address | None = Field(None, frozen=True)
    ip6_addr: str | None = None
    hostaddr: str | None = None

    connectionprofile_name: str | None = None
    ipmdns_type: str | None = None
    ipmdns_is_package: str | None = None
    ldap_user: str | None = None
    ldap_domain: str | None = None
    isolated: bool | None = None
    reverse_proxy_conf: str | None = None

    aws_keyid: str | None = None
    aws_use_role: bool | None = None
    aws_role_arn: str | None = None
    aws_role_external_id: str | None = None
    aws_role_session_name: str | None = None
    aws_delegation_set: str | None = None
    dns_cloud_private: bool | None = None
    az_tenantid: str | None = None
    az_keyid: str | None = None
    az_subscriptionid: str | None = None
    az_group: str | None = None

    dnsblast_enabled: bool | None = None
    dnsblast_status: int | None = None
    dnssec_validation: str | None = None
    dnsgslb_supported: bool | None = None
    dnsguardian_supported: bool | None = None
    guardian_stats_only_supported: bool | None = None
    dns_vpc_list: str | None = None
    querylog_state: bool | None = None
    dns_synching: bool | None = None
    multistatus: str | None = Field(None, frozen=True)

    row_enabled: RowEnabled | None = Field(None, frozen=True)
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)

        _BLOB_KEYS = frozenset({  # noqa: N806
            "dns_class_parameters",
            "dns_class_parameters_properties",
            "dns_class_parameters_inheritance_source",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "dns_id" | "row_enabled" |
                    "tree_level" | "total_vdns_members" |
                    "dns_rpz_max_policy_ttl" | "dns_rpz_min_ns_dots" |
                    "dnsblast_status"
                ):
                    out[key] = cls._as_int(val)
                case "vdns_parent_id" | "gss_keytab_id":
                    out[key] = cls._as_nz_int(val)
                case (
                    "dns_rpz_recursive_only" | "dns_rpz_break_dnssec" |
                    "dns_rpz_qname_wait_recurse" | "gss_enabled" |
                    "isolated" | "aws_use_role" | "dns_cloud_private" |
                    "dnsblast_enabled" | "dnsgslb_supported" | "dnsguardian_supported" |
                    "guardian_stats_only_supported" | "querylog_state" | "dns_synching"
                ):
                    out[key] = cls._as_bool(val)
                case "ip_addr":
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
