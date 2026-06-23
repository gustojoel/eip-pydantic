"""DnsZone model (``dns_zone_list`` / ``dns_zone_info``)."""
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class DnsZone(SolidServerModel):
    """A DNS zone (``dns_zone_list`` / ``dns_zone_info``).

    A zone belongs to a :class:`DnsServer` (and optionally a :class:`DnsView`).
    ``dnszone_name`` is immutable after creation (API restriction).

    Required at creation: ``dns_id`` or ``dns_name``, ``dnszone_name``, ``dnszone_type``.

    Mutable fields (writable via ``Session.flush()``):
        ``dnszone_type``, ``dnszone_masters``, ``dnszone_forwarders``,
        ``dnszone_forward``, ``dnszone_allow_transfer``, ``dnszone_allow_query``,
        ``dnszone_allow_update``, ``dnszone_also_notify``, ``dnszone_notify``,
        ``dnszone_class_name``, ``dnszone_ad_integrated``, ``dnszone_is_rpz``,
        ``dnszone_response_policy``, ``dnszone_rpz_log``,
        ``dnszone_rpz_recursive_only``, ``dnszone_rpz_max_policy_ttl``,
        ``use_update_policy``, ``dnszone_order``, ``ddns_scavenging``,
        ``row_enabled``, ``class_params``.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="dnszone_id",
        class_param_prefix="dnszone",
        tags_prefix="dnszone",
        create_fields=frozenset({
            "dns_id",
            "dns_name",
            "dnszone_name",
            "dnszone_type",
            "dnsview_id",
            "dnsview_name",
            "dnszone_site_id",
            "dnszone_site_name",
            "dnszone_masters",
            "dnszone_forwarders",
            "dnszone_forward",
            "dnszone_allow_transfer",
            "dnszone_allow_query",
            "dnszone_allow_update",
            "dnszone_also_notify",
            "dnszone_notify",
            "dnszone_class_name",
            "dnszone_ad_integrated",
            "dnszone_is_rpz",
            "dnszone_response_policy",
            "dnszone_rpz_log",
            "dnszone_rpz_recursive_only",
            "dnszone_rpz_max_policy_ttl",
            "row_enabled",
            "use_update_policy",
            "dnszone_order",
            "ddns_scavenging",
            "class_params",
        }),
        paths=MappingProxyType({
            "list":   "rest/dns_zone_list",
            "info":   "rest/dns_zone_info",
            "count":  "rest/dns_zone_count",
            "add":    "rest/dns_zone_add",
            "delete": "rest/dns_zone_delete",
        }),
        parent_fields=MappingProxyType({
            "dns_id":     "dns_id",
            "dnsview_id": "dnsview_id",
        }),
    )

    dnszone_id: int | None = Field(None, frozen=True)
    dnszone_name: str | None = Field(None, frozen=True)
    dnszone_name_utf: str | None = None
    dnszone_type: str | None = None

    dnszone_masters: str | None = None
    dnszone_forwarders: str | None = None
    dnszone_forward: str | None = None
    dnszone_allow_transfer: str | None = None
    dnszone_allow_query: str | None = None
    dnszone_allow_update: str | None = None
    dnszone_also_notify: str | None = None
    dnszone_notify: str | None = None
    dnszone_class_name: str | None = None
    dnszone_response_policy: str | None = None

    dnszone_ad_integrated: bool | None = None
    dnszone_is_rpz: bool | None = None
    dnszone_rpz_log: bool | None = None
    dnszone_rpz_recursive_only: bool | None = None
    dnszone_rpz_max_policy_ttl: int | None = None
    dnszone_is_reverse: bool | None = None

    use_update_policy: bool | None = None
    dnszone_order: int | None = None
    ddns_scavenging: bool | None = None

    num_keys: int | None = None
    gss_enabled: bool | None = None
    gss_keytab_id: int | None = None
    dnszone_synching: int | None = None

    dns_state: str | None = None
    vdns_parent_id: int | None = None
    vdns_parent_name: str | None = None

    delayed_delete_time: int | None = None
    delayed_create_time: int | None = None

    dnszone_site_name: str | None = None
    dnszone_site_id: int | None = None

    dnsview_id: int | None = None
    dnsview_name: str | None = None
    dnsview_class_name: str | None = None

    dns_id: int | None = None
    dns_name: str | None = None
    dns_type: str | None = None
    dns_comment: str | None = None
    dns_version: str | None = None
    dns_class_name: str | None = None

    ds: str | None = None
    ip_addr: IPv4Address | None = Field(None, frozen=True)
    ip6_addr: str | None = None
    hostaddr: str | None = None

    dns_vpc_list: str | None = None
    aws_delegation_set: str | None = None
    multistatus: str | None = None
    ipmdns_type: str | None = None

    row_enabled: RowEnabled | None = Field(None, frozen=True)
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)

    def write_params(self) -> dict[str, str]:  # noqa: D102
        out = super().write_params()
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            match field:
                case (
                    "dnszone_ad_integrated" | "dnszone_is_rpz" | "dnszone_rpz_log" |
                    "dnszone_rpz_recursive_only" | "use_update_policy" | "ddns_scavenging" |
                    "gss_enabled"
                ):
                    out[field] = "" if val is None else self._to_bool_str(val)
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
            "dnszone_class_parameters",
            "dnszone_class_parameters_properties",
            "dnszone_class_parameters_inheritance_source",
            "dnsview_class_parameters",
            "dnsview_class_parameters_properties",
            "dns_class_parameters",
            "dns_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "dnszone_id" | "dns_id" | "row_enabled" |
                    "dnszone_order" | "dnszone_rpz_max_policy_ttl" |
                    "num_keys" | "dnszone_synching" |
                    "delayed_delete_time" | "delayed_create_time"
                ):
                    out[key] = cls._as_int(val)
                case (
                    "vdns_parent_id" | "gss_keytab_id" |
                    "dnsview_id" | "dnszone_site_id"
                ):
                    out[key] = cls._as_nz_int(val)
                case (
                    "dnszone_ad_integrated" | "dnszone_is_rpz" | "dnszone_rpz_log" |
                    "dnszone_rpz_recursive_only" | "dnszone_is_reverse" |
                    "use_update_policy" | "ddns_scavenging" | "gss_enabled"
                ):
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
                cls._as_str(v.get("dnszone_class_parameters")),
                cls._as_str(v.get("dnszone_class_parameters_properties")),
                cls._as_str(v.get("dnszone_class_parameters_inheritance_source")),
                api_prefix="dnszone",
            )

        return out
