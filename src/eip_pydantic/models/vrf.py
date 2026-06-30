"""Vrf model (``vrfobject_list`` / ``vrfobject_info``)."""
from types import MappingProxyType
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled, SolidServerConfig, SolidServerModel



class Vrf(SolidServerModel):
    """An EfficientIP VRF object (``vrfobject_list`` / ``vrfobject_info``).

    Represents a VRF entry from Chapter 67 (VRF) of the SolidServer REST API
    reference. The model is used for the five key VRF services:

    - ``vrf_vrfobject_add`` for create and update
    - ``vrfobject_list`` for list
    - ``vrfobject_info`` for fetch by ID
    - ``vrfobject_count`` for count
    - ``vrf_vrfobject_delete`` for delete

    Mutable fields (writable via ``Session.flush()``):
        ``vrfobject_name``, ``vrfobject_rd_id``, ``vrfobject_comment``,
        ``vrfobject_class_name``, ``class_params``, ``row_enabled``.

    Frozen fields are server-managed identity/state values and should be treated
    as read-only snapshots from ``*_list`` / ``*_info`` responses.
    """

    solid_config: ClassVar[SolidServerConfig] = SolidServerConfig(
        pk_field="vrfobject_id",
        class_param_prefix="vrfobject",
        tags_prefix="vrfobject",
        create_fields=frozenset({
            "vrfobject_name", "vrfobject_rd_id", "vrfobject_comment",
            "vrfobject_class_name", "class_params", "row_enabled",
        }),
        paths=MappingProxyType({
            "list":   "rest/vrfobject_list",
            "info":   "rest/vrfobject_info",
            "count":  "rest/vrfobject_count",
            "add":    "rest/vrf_vrfobject_add",
            "delete": "rest/vrf_vrfobject_delete",
        }),
    )

    vrfobject_id: int | None = Field(None, frozen=True)
    vrfobject_name: str
    vrfobject_rd_id: str | None = None
    vrfobject_comment: str | None = None
    vrfobject_class_name: str | None = None
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)
    row_enabled: RowEnabled | None = None

    def write_params(self) -> dict[str, str]:  # noqa: D102
        out = super().write_params()
        for field in self._dirty:
            val = getattr(self, field)
            if isinstance(val, ClassParamDict):
                continue
            match field:
                case "row_enabled":
                    out[field] = self._to_int_str(int(val) if val is not None else None)
                case _:
                    out[field] = "" if val is None else str(val)
        return out

    def build_request(self, operation: str, **kwargs: Any) -> tuple[str, str, dict[str, str]]:  # noqa: D102
        if operation != "create":
            return super().build_request(operation, **kwargs)
        params = self.write_params()
        return ("POST", type(self).solid_config.paths["add"], params)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)

        _BLOB_KEYS = frozenset({  # noqa: N806
            "vrfobject_class_parameters",
            "vrfobject_class_parameters_properties",
            "vrfobject_class_parameters_inheritance_source",
        })

        out: dict[str, Any] = {}
        for key, val in v.items():
            if key in _BLOB_KEYS:
                continue
            match key:
                case "errno" | "vrfobject_id" | "row_enabled":
                    out[key] = cls._as_int(val)
                case _:
                    if isinstance(val, ClassParamDict):
                        out[key] = val
                    elif key in cls.model_fields:
                        out[key] = cls._as_str(val) if isinstance(val, (str, type(None))) else val
                    else:
                        out[key] = val

        cls._coerce_class_params(out, v)

        return out
