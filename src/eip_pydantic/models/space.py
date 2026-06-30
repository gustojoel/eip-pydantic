"""Space model (``ip_site_list`` / ``ip_site_info``)."""
from datetime import datetime
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class Space(SolidServerModel):
    """An EfficientIP IPAM space (``ip_site_list`` / ``ip_site_info``).

    A space is the top-level container in the IPAM hierarchy.  Spaces may be
    nested (parent/child) and can contain IPv4 and IPv6 networks.

    Mutable fields (writable via ``Session.flush()``):
        ``site_name``, ``site_description``, ``site_class_name``,
        ``class_params``, ``row_enabled``.

    All other fields are frozen and reflect server-managed state.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="site_id",
        class_param_prefix="site",
        tags_prefix="site",
        create_fields=frozenset({
            "site_name", "site_description", "site_class_name",
            "class_params", "row_enabled", "parent_site_id",
            "parent_site_name", "site_is_template",
        }),
        paths=MappingProxyType({
            "list":   "rest/ip_site_list",
            "info":   "rest/ip_site_info",
            "count":  "rest/ip_site_count",
            "add":    "rest/ip_site_add",
            "delete": "rest/ip_site_delete",
        }),
        parent_fields=MappingProxyType({
            "site_id": "parent_site_id",  # Space nested in Space
        }),
    )

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------
    site_id: int | None = Field(None, frozen=True)
    site_name: str # required
    site_description: str | None = None
    site_is_template: bool | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Class system
    # ------------------------------------------------------------------
    site_class_name: str | None = None
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)
    parent_site_class_params: ClassParamDict | None = Field(None, frozen=True)  # _info only

    # ------------------------------------------------------------------
    # Hierarchy
    # ------------------------------------------------------------------
    parent_site_id: int | None = Field(None, frozen=True)
    parent_site_name: str | None = Field(None, frozen=True)
    parent_site_class_name: str | None = Field(None, frozen=True)
    tree_level: int | None = Field(None, frozen=True)
    tree_path: str | None = Field(None, frozen=True)
    tree_id_path: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # VLSM cross-space linkage
    # ------------------------------------------------------------------
    vlsm_site_id: int | None = Field(None, frozen=True)
    vlsm_site_name: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    row_enabled: RowEnabled | None = None
    multistatus: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Audit trail
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
        """Serialise dirty mutable fields to the wire format expected by ``ip_site_add``."""
        out = super().write_params()   # handles class_params → site_class_parameters etc.
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            match field:
                case "row_enabled":
                    out[field] = self._to_int_str(int(val) if val is not None else None)
                case "site_is_template":
                    out[field] = self._to_bool_str(val)
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
            "site_class_parameters",
            "site_class_parameters_properties",
            "site_class_parameters_inheritance_source",
            "parent_site_class_parameters",
            "parent_site_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case "errno" | "site_id" | "tree_level" | "row_enabled":
                    out[key] = cls._as_int(val)
                case (
                    "parent_site_id" |
                    "vlsm_site_id" |
                    "trace_creation_usr_id" | "trace_creation_origin_usr_id"
                ):
                    out[key] = cls._as_nz_int(val)
                case "site_is_template":
                    out[key] = cls._as_bool(val)
                case "trace_creation_date" | "trace_last_update_date":
                    out[key] = cls._as_datetime(val)
                case _:
                    if isinstance(val, ClassParamDict):
                        out[key] = val
                    elif key in cls.model_fields:
                        out[key] = cls._as_str(val) if isinstance(val, (str, type(None))) else val
                    else:
                        out[key] = val

        cls._coerce_class_params(out, v)
        if "parent_site_class_parameters" in v or "parent_site_class_parameters_properties" in v:
            out["parent_site_class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("parent_site_class_parameters")),
                cls._as_str(v.get("parent_site_class_parameters_properties")),
                api_prefix="site",
                frozen=True,
            )

        return out
