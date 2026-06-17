"""Vlan model (``vlmvlan_list`` / ``vlmvlan_info``)."""
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class Vlan(SolidServerModel):
    """A VLAN entry (``vlmvlan_list`` / ``vlmvlan_info``).

    Represents a single VLAN ID assignment within a domain/range.  The ``type``
    field distinguishes used VLANs (``"used"``) from free spans (``"free"``).

    Mutable fields (writable via ``Session.flush()``):
        ``vlmvlan_name``, ``vlmvlan_class_name``, ``class_params``.

    The VLAN identifier ``vlmvlan_vlan_id`` is frozen after creation.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="vlmvlan_id",
        class_param_prefix="vlmvlan",
        tags_prefix="vlmvlan",
        create_fields=frozenset({
            # Either vlmdomain_id or vlmdomain_name is required to define the parent domain.
            "vlmdomain_id", "vlmdomain_name",
            # vlan_id is required as the VLAN ID (field name is vlmvlan_vlan_id)
            "vlan_id",
            "vlmrange_id", "vlmrange_name",
            "vlmvlan_name",
            "vlmvlan_class_name",
            "class_params",
        }),
        paths=MappingProxyType({
            "list": "rest/vlmvlan_list",
            "info": "rest/vlmvlan_info",
            "count": "rest/vlmvlan_count",
            "add": "rest/vlm_vlan_add",
            "delete": "rest/vlm_vlan_delete",
        }),
    )

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------
    vlmvlan_id: int | None = Field(None, frozen=True)
    vlan_id: int = Field(frozen=True, alias="vlmvlan_vlan_id")
    vlmvlan_name: str | None = None

    @property
    def vlmvlan_vlan_id(self) -> int:
        """Backward-compatible accessor for the actual field name."""
        return self.vlan_id

    # ------------------------------------------------------------------
    # Record type (free / used)
    # ------------------------------------------------------------------
    type: str | None = Field(None, frozen=True)
    free_start_vlan_id: int | None = Field(None, frozen=True)
    free_end_vlan_id: int | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Class system
    # ------------------------------------------------------------------
    vlmvlan_class_name: str | None = None
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)

    # ------------------------------------------------------------------
    # Parent range (frozen — linkage is read-only)
    # ------------------------------------------------------------------
    vlmrange_id: int | None = Field(None, frozen=True)
    vlmrange_name: str | None = Field(None, frozen=True)
    vlmrange_start_vlan_id: int | None = Field(None, frozen=True)
    vlmrange_end_vlan_id: int | None = Field(None, frozen=True)
    vlmrange_class_name: str | None = Field(None, frozen=True)
    vlmrange_description: str | None = Field(None, frozen=True)
    vlmrange_row_enabled: str | None = Field(None, frozen=True)  # internal, undocumented
    vlmrange_class_params: ClassParamDict | None = Field(None, frozen=True)

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
            api_field = type(self).model_fields[field].alias or field
            out[api_field] = "" if val is None else str(val)
        return out

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)

        _BLOB_KEYS = frozenset({  # noqa: N806
            "vlmvlan_class_parameters",
            "vlmvlan_class_parameters_properties",
            "vlmvlan_class_parameters_inheritance_source",
            "vlmrange_class_parameters",
            "vlmrange_class_parameters_properties",
            "vlmdomain_class_parameters",
            "vlmdomain_class_parameters_properties",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case (
                    "errno" | "vlmvlan_id" | "vlmvlan_vlan_id" | "row_enabled" |
                    "free_start_vlan_id" | "free_end_vlan_id" |
                    "vlmrange_start_vlan_id" | "vlmrange_end_vlan_id" |
                    "vlmdomain_start_vlan_id" | "vlmdomain_end_vlan_id"
                ):
                    out[key] = cls._as_int(val)
                case "vlmrange_id" | "vlmdomain_id":
                    out[key] = cls._as_nz_int(val)
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
                cls._as_str(v.get("vlmvlan_class_parameters")),
                cls._as_str(v.get("vlmvlan_class_parameters_properties")),
                cls._as_str(v.get("vlmvlan_class_parameters_inheritance_source")),
                api_prefix="vlmvlan",
            )
        if "vlmrange_class_parameters" in v or "vlmrange_class_parameters_properties" in v:
            out["vlmrange_class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("vlmrange_class_parameters")),
                cls._as_str(v.get("vlmrange_class_parameters_properties")),
                api_prefix="vlmrange",
                frozen=True,
            )
        if "vlmdomain_class_parameters" in v or "vlmdomain_class_parameters_properties" in v:
            out["vlmdomain_class_params"] = ClassParamDict.from_blobs(
                cls._as_str(v.get("vlmdomain_class_parameters")),
                cls._as_str(v.get("vlmdomain_class_parameters_properties")),
                api_prefix="vlmdomain",
                frozen=True,
            )

        return out
