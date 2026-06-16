"""Unit tests for the Space model and ipam.space_* API methods.

Wire-format fixtures are based on real ip_site_list / ip_site_info responses
with names and IDs anonymised.
"""

import httpx
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.space import Space



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

# ---------------------------------------------------------------------------
# Wire-format fixtures (all values are strings, exactly as the API returns)
# ---------------------------------------------------------------------------

# Typical top-level space from ip_site_list
_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "site_id": "7",
    "site_name": "global",
    "site_description": "Global address space",
    "site_is_template": "0",
    "site_class_name": "",
    "parent_site_id": "0",
    "parent_site_name": "#",
    "parent_site_class_name": "",
    "row_enabled": "1",
    "multistatus": "",
    "tree_level": "0",
    "tree_path": "global#",
    "tree_id_path": "#7#",
    "site_class_parameters": "dns_id=0&rev_dns_id=0&dns_update=0",
    "site_class_parameters_properties": "dns_id=set,propagate&rev_dns_id=set,propagate&dns_update=set,propagate",
    "site_class_parameters_inheritance_source": "dns_id=real_site,7&rev_dns_id=real_site,7&dns_update=real_site,7",
}

# ip_site_info adds two extra class-param blobs not in list
_INFO_ROW: dict[str, str] = {
    **_LIST_ROW,
    "parent_site_class_parameters": "",
    "parent_site_class_parameters_properties": "",
}

# Child space nested under site_id=7
_CHILD_ROW: dict[str, str] = {
    **_LIST_ROW,
    "site_id": "12",
    "site_name": "emea",
    "site_description": "EMEA region",
    "parent_site_id": "7",
    "parent_site_name": "global",
    "tree_level": "1",
    "tree_path": "global#emea#",
    "tree_id_path": "#7#12#",
}

# Template space
_TEMPLATE_ROW: dict[str, str] = {
    **_LIST_ROW,
    "site_id": "99",
    "site_name": "template-standard",
    "site_description": "Standard space template",
    "site_is_template": "1",
    "row_enabled": "2",
}

# ---------------------------------------------------------------------------
# Model coercion tests
# ---------------------------------------------------------------------------


def test_space_int_fields() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.site_id == 7
    assert s.tree_level == 0
    assert s.errno == 0


def test_space_top_level_parent_is_none() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.parent_site_id is None  # "0" via NzInt → None


def test_space_child_has_parent_id() -> None:
    s = Space.model_validate(_CHILD_ROW)
    assert s.parent_site_id == 7
    assert s.parent_site_name == "global"
    assert s.tree_level == 1


def test_space_bool_not_template() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.site_is_template is False


def test_space_bool_is_template() -> None:
    s = Space.model_validate(_TEMPLATE_ROW)
    assert s.site_is_template is True


def test_space_row_enabled_enabled() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.row_enabled == RowEnabled.ENABLED


def test_space_row_enabled_unmanaged() -> None:
    s = Space.model_validate(_TEMPLATE_ROW)
    assert s.row_enabled == RowEnabled.UNMANAGED


def test_space_row_enabled_deleted() -> None:
    s = Space.model_validate({**_LIST_ROW, "row_enabled": "0"})
    assert s.row_enabled == RowEnabled.DELETED


def test_space_string_sentinel_empty_to_none() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.site_class_name is None     # "" → None
    assert s.multistatus is None          # "" → None


def test_space_string_sentinel_hash_to_none() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.parent_site_name is None    # "#" → None


def test_space_string_fields_preserved() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.site_name == "global"
    assert s.site_description == "Global address space"
    assert s.tree_path == "global#"
    assert s.tree_id_path == "#7#"


def test_space_class_params_values() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.class_params["dns_id"] == "0"
    assert s.class_params["rev_dns_id"] == "0"
    assert s.class_params["dns_update"] == "0"


def test_space_class_params_inheritance() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.class_params.is_set("dns_id")
    assert s.class_params.is_propagate("dns_id")


def test_space_class_params_sources() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.class_params.source("dns_id") == ("real_site", "7")
    assert s.class_params.source("rev_dns_id") == ("real_site", "7")


def test_space_parent_class_params_present_in_info() -> None:
    s = Space.model_validate(_INFO_ROW)
    # ip_site_info includes empty parent blobs → ClassParamDict with no keys
    assert s.parent_site_class_params is not None
    assert len(s.parent_site_class_params) == 0


def test_space_parent_class_params_absent_in_list() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert s.parent_site_class_params is None


def test_space_model_extra_tag_passthrough() -> None:
    row = {**_LIST_ROW, "tag_site_owner": "network-team", "tag_site_region": "global"}
    s = Space.model_validate(row)
    assert s.tagged_class_parameters == {
        "site_owner": "network-team",
        "site_region": "global",
    }


def test_space_unknown_extra_fields_captured() -> None:
    row = {**_LIST_ROW, "future_field": "some_value"}
    s = Space.model_validate(row)
    assert s.model_extra is not None
    assert "future_field" in s.model_extra


def test_space_no_model_extra_on_clean_list_row() -> None:
    s = Space.model_validate(_LIST_ROW)
    assert not s.model_extra


def test_space_no_model_extra_on_info_row() -> None:
    s = Space.model_validate(_INFO_ROW)
    assert not s.model_extra


# ---------------------------------------------------------------------------
# API-layer tests (respx)
# ---------------------------------------------------------------------------


@respx.mock
def test_space_list_returns_list_of_spaces() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW, _CHILD_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        spaces = s.list(Space)
    assert len(spaces) == 2
    assert all(isinstance(sp, Space) for sp in spaces)
    assert spaces[0].site_id == 7
    assert spaces[1].site_id == 12


@respx.mock
def test_space_info_returns_single_space() -> None:
    respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_INFO_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        sp = s.get(Space, 7)
    assert isinstance(sp, Space)
    assert sp.site_id == 7
    assert sp.parent_site_class_params is not None  # empty blob present in info response


@respx.mock
def test_space_list_sends_where_param() -> None:
    route = respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Space, where="site_name='global'")
    assert route.called
    assert route.calls.last.request.url.params["WHERE"] == "site_name='global'"


@respx.mock
def test_space_list_sends_limit_param() -> None:
    route = respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Space, limit=5)
    assert route.calls.last.request.url.params["limit"] == "5"


def test_space_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert Space._coerce(sentinel) is sentinel
