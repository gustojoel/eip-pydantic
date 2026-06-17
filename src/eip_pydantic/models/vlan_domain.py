"""VlanDomain model (``vlmdomain_list`` / ``vlmdomain_info``)."""
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class VlanDomain(SolidServerModel):
    """A VLAN manager domain (``vlmdomain_list`` / ``vlmdomain_info``).

    A domain is the top-level VLAN namespace.  It spans a range of VLAN IDs
    and contains one or more :class:`VlanRange` objects.  ``support_vxlan``
    is immutable after creation (API restriction).

    Required at creation: ``vlmdomain_name``, ``vlmdomain_start_vlan_id``,
    ``vlmdomain_end_vlan_id``.

    Mutable fields (writable via ``Session.flush()``):
        ``vlmdomain_name``, ``vlmdomain_description``,
        ``vlmdomain_class_name``, ``class_params``.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="vlmdomain_id",
        class_param_prefix="vlmdomain",
        tags_prefix="vlmdomain",
        create_fields=frozenset({
            "vlmdomain_name",
            "vlmdomain_description",
            "vlmdomain_start_vlan_id",
            "vlmdomain_end_vlan_id",
            "support_vxlan",
            "vlmdomain_class_name",
            "class_params",
        }),
        paths=MappingProxyType({
            "list": "rest/vlmdomain_list",
            "info": "rest/vlmdomain_info",
            "count": "rest/vlmdomain_count",
            "add": "rest/vlm_domain_add",
            "delete": "rest/vlm_domain_delete",
        }),
    )

    vlmdomain_id: int | None = Field(None, frozen=True)
    vlmdomain_name: str # required
    vlmdomain_description: str | None = None
    vlmdomain_start_vlan_id: int = Field(frozen=True) # required
    vlmdomain_end_vlan_id: int = Field(frozen=True) # required
    support_vxlan: bool = Field(False, frozen=True)

    vlmdomain_class_name: str | None = None
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)
    row_enabled: RowEnabled | None = Field(None, frozen=True)

    def write_params(self) -> dict[str, str]:  # noqa: D102
        out = super().write_params()
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            match field:
                case "support_vxlan":
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
            "vlmdomain_class_parameters",
            "vlmdomain_class_parameters_properties",
            "vlmdomain_class_parameters_inheritance_source",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "vlmdomain_id" |
                    "vlmdomain_start_vlan_id" | "vlmdomain_end_vlan_id" |
                    "row_enabled"
                ):
                    out[key] = cls._as_int(val)
                case "support_vxlan":
                    out[key] = cls._as_bool(val)
                case _:
                    if isinstance(val, ClassParamDict):
                        out[key] = val
                    elif key in cls.model_fields:
                        out[key] = cls._as_str(val)
                    else:
                        out[key] = val

        if not isinstance(out.get("class_params"), ClassParamDict):
            out["class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("vlmdomain_class_parameters")),
                cls._as_str(v.get("vlmdomain_class_parameters_properties")),
                cls._as_str(v.get("vlmdomain_class_parameters_inheritance_source")),
                api_prefix="vlmdomain",
            )

        return out
