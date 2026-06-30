"""DnsRr model (``dns_rr_list`` / ``dns_rr_info``)."""
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class DnsRr(SolidServerModel):
    """A DNS resource record (``dns_rr_list`` / ``dns_rr_info``).

    RRs belong to a :class:`DnsZone`.  The ``ttl`` field on output uses the
    wire name ``ttl``; the create input uses ``rr_ttl`` — both are listed in
    ``create_fields`` for clarity, though the model field is ``ttl``.

    Required at creation: ``dns_id`` or ``dns_name``, ``dnszone_id`` or
    ``dnszone_name``, ``rr_type``, ``rr_name`` (or ``rr_glue`` for
    short-name form), plus the type-specific ``value*`` field(s).
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="rr_id",
        class_param_prefix="rr",
        tags_prefix="",
        create_fields=frozenset({
            "dns_id",
            "dns_name",
            "dnszone_id",
            "dnszone_name",
            "dnsview_id",
            "dnsview_name",
            "rr_type",
            "rr_name",
            "rr_glue",
            "value1",
            "value2",
            "value3",
            "value4",
            "value5",
            "value6",
            "value7",
            "rr_ttl",
            "rr_class_name",
            "class_params",
        }),
        paths=MappingProxyType({
            "list":   "rest/dns_rr_list",
            "info":   "rest/dns_rr_info",
            "count":  "rest/dns_rr_count",
            "add":    "rest/dns_rr_add",
            "delete": "rest/dns_rr_delete",
        }),
        parent_fields=MappingProxyType({
            "dnszone_id": "dnszone_id",
            "dns_id":     "dns_id",
            "dnsview_id": "dnsview_id",
        }),
    )

    rr_id: int | None = Field(None, frozen=True)
    rr_type: str | None = None
    rr_name: str | None = None
    rr_full_name: str | None = None
    rr_full_name_utf: str | None = None
    rr_glue: str | None = None
    rr_all_value: str | None = None
    rr_class_name: str | None = None

    value1: str | None = None
    value2: str | None = None
    value3: str | None = None
    value4: str | None = None
    value5: str | None = None
    value6: str | None = None
    value7: str | None = None

    ttl: int | None = None
    delayed_time: int | None = None
    delayed_create_time: int | None = None
    delayed_delete_time: int | None = None

    dnszone_id: int | None = None
    dns_id: int | None = None
    dnszone_name: str | None = None
    dnszone_name_utf: str | None = None
    dns_name: str | None = None
    dns_type: str | None = None

    vdns_parent_id: int | None = None
    vdns_parent_name: str | None = None

    dnsview_id: int | None = None
    dnsview_name: str | None = None
    dnsview_class_name: str | None = None

    dnszone_site_name: str | None = None
    dnszone_site_id: int | None = None
    dnszone_is_reverse: bool | None = None
    dnszone_masters: str | None = None
    dnszone_forwarders: str | None = None
    dnszone_type: str | None = None
    dnszone_is_rpz: bool | None = None
    dnszone_class_name: str | None = None

    dns_class_name: str | None = None
    dns_version: str | None = None
    dns_comment: str | None = None

    multistatus: str | None = Field(None, frozen=True)
    rr_auth_gsstsig: bool | None = None
    rr_last_update_days: int | None = None

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
            "rr_class_parameters",
            "rr_class_parameters_properties",
            "rr_class_parameters_inheritance_source",
            "dnsview_class_parameters",
            "dnsview_class_parameters_properties",
            "dnsview_class_parameters_inheritance_source",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "rr_id" | "row_enabled" |
                    "ttl" | "delayed_time" | "delayed_create_time" | "delayed_delete_time" |
                    "dnszone_id" | "dns_id" | "rr_last_update_days"
                ):
                    out[key] = cls._as_int(val)
                case (
                    "vdns_parent_id" | "dnsview_id" | "dnszone_site_id"
                ):
                    out[key] = cls._as_nz_int(val)
                case (
                    "dnszone_is_reverse" | "dnszone_is_rpz" | "rr_auth_gsstsig"
                ):
                    out[key] = cls._as_bool(val)
                case _:
                    if isinstance(val, ClassParamDict):
                        out[key] = val
                    elif key in cls.model_fields:
                        out[key] = cls._as_str(val) if isinstance(val, (str, type(None))) else val
                    else:
                        out[key] = val

        cls._coerce_class_params(out, v)

        return out
