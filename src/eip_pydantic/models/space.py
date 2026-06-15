from datetime import datetime
from typing import Any, ClassVar, cast

from pydantic import Field, model_validator

from eip_pydantic.models.base import RowEnabled, SolidServerModel


class Space(SolidServerModel):
    """An EfficientIP IPAM space (``ip_site_list`` / ``ip_site_info``).

    A space is the top-level container in the IPAM hierarchy.  Spaces may be
    nested (parent/child) and can contain IPv4 and IPv6 networks.

    Mutable fields (writable via ``Session.flush()``):
        ``site_name``, ``site_description``, ``site_class_name``,
        ``site_class_parameters``, ``site_class_parameters_properties``,
        ``row_enabled``.

    All other fields are frozen and reflect server-managed state.
    """

    _class_param_prefix: ClassVar[str | None] = "site"
    tags_prefix: ClassVar[str] = "site"
    _pk_field: ClassVar[str] = "site_id"
    _list_path: ClassVar[str] = "rest/ip_site_list"
    _info_path: ClassVar[str] = "rest/ip_site_info"
    _add_path: ClassVar[str] = "rest/ip_site_add"
    _delete_path: ClassVar[str] = "rest/ip_site_delete"

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------
    site_id: int = Field(frozen=True)
    site_name: str | None = None
    site_description: str | None = None
    site_is_template: bool | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Class system
    # ------------------------------------------------------------------
    site_class_name: str | None = None
    site_class_parameters: str | None = None
    site_class_parameters_properties: str | None = None
    site_class_parameters_inheritance_source: str | None = Field(None, frozen=True)

    # ------------------------------------------------------------------
    # Hierarchy
    # ------------------------------------------------------------------
    parent_site_id: int | None = Field(None, frozen=True)
    parent_site_name: str | None = Field(None, frozen=True)
    parent_site_class_name: str | None = Field(None, frozen=True)
    parent_site_class_parameters: str | None = Field(None, frozen=True)         # _info only
    parent_site_class_parameters_properties: str | None = Field(None, frozen=True)  # _info only
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
        """Serialise dirty mutable fields to the wire format expected by ``ip_site_add``.

        Iterates ``_dirty`` and converts each changed field to its string
        representation.  ``row_enabled`` is serialised as its integer value;
        all other fields use ``str()`` with an empty string for ``None``.

        Returns:
            Mapping of field name → wire-format string, ready to pass as query
            parameters to a PUT or POST request.
        """
        out: dict[str, str] = {}
        for field in self._dirty:
            val = getattr(self, field)
            match field:
                case "row_enabled":
                    out[field] = self._to_int_str(int(val) if val is not None else None)
                case _:
                    out[field] = "" if val is None else str(val)
        return out

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        v = cast(dict[str, Any], data)
        out: dict[str, Any] = {}
        for key, val in v.items():
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
                    out[key] = cls._as_str(val) if key in cls.model_fields else val
        return out
