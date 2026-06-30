"""VlanRange model (``vlmrange_list`` / ``vlmrange_info``)."""
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class VlanRange(SolidServerModel):
    """A VLAN manager range (``vlmrange_list`` / ``vlmrange_info``).

    A range is a contiguous sub-span of VLAN IDs within a domain.  It must
    belong to exactly one ``VlanDomain``.

    Mutable fields (writable via ``Session.flush()``):
        ``vlmrange_name``, ``vlmrange_description``, ``vlmrange_start_vlan_id``,
        ``vlmrange_end_vlan_id``, ``vlmrange_disable_overlapping``,
        ``vlmrange_class_name``, ``class_params``.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="vlmrange_id",
        class_param_prefix="vlmrange",
        tags_prefix="vlmrange",
        create_fields=frozenset({
            # vlmdomain_id or vlmdomain_name is required for creation
            "vlmdomain_id", "vlmdomain_name",
            "vlmrange_name",
            "vlmrange_description",
            "vlmrange_start_vlan_id",
            "vlmrange_end_vlan_id",
            "vlmrange_disable_overlapping",
            "vlmrange_class_name",
            "class_params",
        }),
        paths=MappingProxyType({
            "list": "rest/vlmrange_list",
            "info": "rest/vlmrange_info",
            "count": "rest/vlmrange_count",
            "add": "rest/vlm_range_add",
            "delete": "rest/vlm_range_delete",
        }),
        parent_fields=MappingProxyType({
            "vlmdomain_id": "vlmdomain_id",  # VlanDomain parent
        }),
    )

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------
    vlmrange_id: int | None = Field(None, frozen=True)
    vlmrange_name: str # required
    vlmrange_description: str | None = None
    vlmrange_start_vlan_id: int # required
    vlmrange_end_vlan_id: int # required
    vlmrange_disable_overlapping: bool = Field(True)

    # ------------------------------------------------------------------
    # Class system
    # ------------------------------------------------------------------
    vlmrange_class_name: str | None = None
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)

    # ------------------------------------------------------------------
    # Parent domain (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    vlmdomain_id: int | None = Field(None, frozen=True)
    vlmdomain_name: str | None = Field(None, frozen=True)
    vlmdomain_description: str | None = Field(None, frozen=True)
    vlmdomain_start_vlan_id: int | None = Field(None, frozen=True)
    vlmdomain_end_vlan_id: int | None = Field(None, frozen=True)
    vlmdomain_class_name: str | None = Field(None, frozen=True)
    support_vxlan: bool | None = Field(None, frozen=True)
    vlmdomain_class_params: ClassParamDict | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    row_enabled: RowEnabled | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Write serialisation
    # ------------------------------------------------------------------

    def write_params(self) -> dict[str, str]:  # noqa: D102
        out = super().write_params()
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            match field:
                case "vlmrange_disable_overlapping":
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
            "vlmrange_class_parameters",
            "vlmrange_class_parameters_properties",
            "vlmrange_class_parameters_inheritance_source",
            "vlmdomain_class_parameters",
            "vlmdomain_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "vlmrange_id" | "row_enabled" |
                    "vlmrange_start_vlan_id" | "vlmrange_end_vlan_id"
                ):
                    out[key] = cls._as_int(val)
                case "vlmdomain_id":
                    out[key] = cls._as_nz_int(val)
                case (
                    "vlmdomain_start_vlan_id" | "vlmdomain_end_vlan_id"
                ):
                    out[key] = cls._as_int(val)
                case "vlmrange_disable_overlapping" | "support_vxlan":
                    out[key] = cls._as_bool(val)
                case _:
                    if isinstance(val, ClassParamDict):
                        out[key] = val
                    elif key in cls.model_fields:
                        out[key] = cls._as_str(val) if isinstance(val, (str, type(None))) else val
                    else:
                        out[key] = val

        cls._coerce_class_params(out, v)
        if "vlmdomain_class_parameters" in v or "vlmdomain_class_parameters_properties" in v:
            out["vlmdomain_class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("vlmdomain_class_parameters")),
                cls._as_str(v.get("vlmdomain_class_parameters_properties")),
                api_prefix="vlmdomain",
                frozen=True,
            )

        return out
