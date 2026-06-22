"""DnsView model (``dns_view_list`` / ``dns_view_info``)."""
from ipaddress import IPv4Address
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel


class DnsView(SolidServerModel):
    """A DNS view (``dns_view_list`` / ``dns_view_info``).

    Views partition the DNS namespace of a server so that different clients
    see different answers.  A view belongs to exactly one :class:`DnsServer`.

    Required at creation: ``dnsview_name``, plus one of ``dns_id`` / ``dns_name``.

    Mutable fields (writable via ``Session.flush()``):
        ``dnsview_name``, ``dnsview_order``, ``dnsview_match_clients``,
        ``dnsview_match_to``, ``dnsview_allow_transfer``, ``dnsview_allow_query``,
        ``dnsview_allow_recursion``, ``dnsview_recursion``, ``dnsview_class_name``,
        ``class_params``.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="dnsview_id",
        class_param_prefix="dnsview",
        tags_prefix="dnsview",
        create_fields=frozenset({
            "dns_id",
            "dns_name",
            "dnsview_name",
            "dnsview_order",
            "dnsview_match_clients",
            "dnsview_match_to",
            "dnsview_allow_transfer",
            "dnsview_allow_query",
            "dnsview_allow_recursion",
            "dnsview_recursion",
            "dnsview_class_name",
            "class_params",
        }),
        paths=MappingProxyType({
            "list":   "rest/dns_view_list",
            "info":   "rest/dns_view_info",
            "count":  "rest/dns_view_count",
            "add":    "rest/dns_view_add",
            "delete": "rest/dns_view_delete",
        }),
        parent_fields=MappingProxyType({
            "dns_id": "dns_id",
        }),
    )

    dnsview_id: int | None = Field(None, frozen=True)
    dnsview_name: str | None = None
    dnsview_order: int | None = None
    dnsview_recursion: str | None = None
    dnsview_match_clients: str | None = None
    dnsview_match_to: str | None = None
    dnsview_allow_recursion: str | None = None
    dnsview_allow_query: str | None = None
    dnsview_allow_transfer: str | None = None
    dnsview_key_name: str | None = None
    dnsview_class_name: str | None = None

    dns_id: int | None = None
    dns_name: str | None = None
    dns_type: str | None = None
    dns_class_name: str | None = None
    dns_comment: str | None = None
    dns_version: str | None = None

    vdns_parent_id: int | None = None
    vdns_parent_name: str | None = None

    gss_keytab_id: int | None = None
    delayed_create_time: int | None = None
    delayed_delete_time: int | None = None

    ip_addr: IPv4Address | None = Field(None, frozen=True)
    ip6_addr: str | None = None
    hostaddr: str | None = None

    multistatus: str | None = None
    row_enabled: RowEnabled | None = Field(None, frozen=True)
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)

    def write_params(self) -> dict[str, str]:  # noqa: D102
        out = super().write_params()
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            out[field] = "" if val is None else str(val)
        return out

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)

        _BLOB_KEYS = frozenset({  # noqa: N806
            "dnsview_class_parameters",
            "dnsview_class_parameters_properties",
            "dnsview_class_parameters_inheritance_source",
            "dns_class_parameters",
            "dns_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "dnsview_id" | "dns_id" | "row_enabled" |
                    "dnsview_order" | "delayed_create_time" | "delayed_delete_time"
                ):
                    out[key] = cls._as_int(val)
                case "vdns_parent_id" | "gss_keytab_id":
                    out[key] = cls._as_nz_int(val)
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
                cls._as_str(v.get("dnsview_class_parameters")),
                cls._as_str(v.get("dnsview_class_parameters_properties")),
                cls._as_str(v.get("dnsview_class_parameters_inheritance_source")),
                api_prefix="dnsview",
            )

        return out
