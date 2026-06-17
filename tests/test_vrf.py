"""Unit tests for the Vrf model and vrf_vrfobject_* API methods.

Wire-format fixtures are based on the vrfobject_list / vrfobject_info response
shape described in the SolidServer API reference (Chapter 67).

Key coercion facts verified here:
  - vrfobject_id / errno → int via _as_int
  - row_enabled → RowEnabled int enum ("0"/"1"/"2")
  - trace_creation_origin_usr_id uses "0" as FK-null sentinel (nz_int → None)
  - vrfobject_class_parameters blobs → ClassParamDict
  - "" / "#" sentinel strings on declared str fields → None
"""

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.vrf import Vrf



HOST = "solidserver.example.com"
CREDS = ("admin", "secret")
BASE = "https://solidserver.example.com/"

# ---------------------------------------------------------------------------
# Wire-format fixtures
# ---------------------------------------------------------------------------

_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "vrfobject_id": "7",
    "vrfobject_name": "VRF-PROD",
    "vrfobject_rd_id": "65000:1",
    "vrfobject_comment": "Production VRF",
    "vrfobject_class_name": "corporate",
    "vrfobject_class_parameters": "owner=ops&env=prod",
    "vrfobject_class_parameters_properties": "owner=set,propagate&env=set,propagate",
    "vrfobject_class_parameters_inheritance_source": "owner=real_vrfobject,7&env=real_vrfobject,7",
    "row_enabled": "1",
    "multistatus": "",
    "trace_creation_date": "1700000000",
    "trace_last_update_date": "1700010000",
    "trace_creation_usr_id": "3",
    "trace_creation_origin_usr_id": "0",
    "trace_creation_origin": "",
    "trace_creation_exec_stack": "",
    "trace_creation_usr_login": "admin",
    "trace_creation_origin_usr_login": "#",
}

_MINIMAL_ROW: dict[str, str] = {
    "errno": "0",
    "vrfobject_id": "8",
    "vrfobject_name": "VRF-DEV",
    "vrfobject_rd_id": "",
    "vrfobject_comment": "",
    "vrfobject_class_name": "",
    "vrfobject_class_parameters": "",
    "vrfobject_class_parameters_properties": "",
    "vrfobject_class_parameters_inheritance_source": "",
    "row_enabled": "2",
    "multistatus": "#",
    "trace_creation_date": "0",
    "trace_last_update_date": "0",
    "trace_creation_usr_id": "1",
    "trace_creation_origin_usr_id": "0",
    "trace_creation_origin": "#",
    "trace_creation_exec_stack": "#",
    "trace_creation_usr_login": "root",
    "trace_creation_origin_usr_login": "#",
}

# ---------------------------------------------------------------------------
# Coercion tests
# ---------------------------------------------------------------------------


def test_vrf_int_fields() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert v.vrfobject_id == 7
    assert v.errno == 0


def test_vrf_string_fields_preserved() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert v.vrfobject_name == "VRF-PROD"
    assert v.vrfobject_rd_id == "65000:1"
    assert v.vrfobject_comment == "Production VRF"
    assert v.vrfobject_class_name == "corporate"


def test_vrf_string_sentinel_empty_to_none() -> None:
    v = Vrf.model_validate(_MINIMAL_ROW)
    assert v.vrfobject_rd_id is None        # "" → None
    assert v.vrfobject_comment is None       # "" → None
    assert v.vrfobject_class_name is None    # "" → None
    assert v.multistatus is None             # "#" → None


def test_vrf_row_enabled_enabled() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert v.row_enabled == RowEnabled.ENABLED


def test_vrf_row_enabled_unmanaged() -> None:
    v = Vrf.model_validate(_MINIMAL_ROW)
    assert v.row_enabled == RowEnabled.UNMANAGED


def test_vrf_row_enabled_deleted() -> None:
    v = Vrf.model_validate({**_LIST_ROW, "row_enabled": "0"})
    assert v.row_enabled == RowEnabled.DELETED


def test_vrf_nz_int_trace_origin_absent_when_zero() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert v.trace_creation_origin_usr_id is None


def test_vrf_nz_int_trace_usr_id_present() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert v.trace_creation_usr_id == 3


def test_vrf_class_params_values() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert v.class_params["owner"] == "ops"
    assert v.class_params["env"] == "prod"


def test_vrf_class_params_properties() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert v.class_params.is_set("owner")
    assert v.class_params.is_propagate("owner")


def test_vrf_class_params_sources() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert v.class_params.source("owner") == ("real_vrfobject", "7")
    assert v.class_params.source("env") == ("real_vrfobject", "7")


def test_vrf_class_params_empty_for_minimal_row() -> None:
    v = Vrf.model_validate(_MINIMAL_ROW)
    assert len(v.class_params) == 0


def test_vrf_no_model_extra_on_list_row() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert not v.model_extra


def test_vrf_no_model_extra_on_minimal_row() -> None:
    v = Vrf.model_validate(_MINIMAL_ROW)
    assert not v.model_extra


def test_vrf_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert Vrf._coerce(sentinel) is sentinel


def test_vrf_frozen_id_raises_on_assignment() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    with pytest.raises(Exception):  # ValidationError (frozen field)
        v.vrfobject_id = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# write_params / dirty tracking
# ---------------------------------------------------------------------------


def test_vrf_write_params_name() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    v.vrfobject_name = "VRF-RENAMED"
    assert v.write_params() == {"vrfobject_name": "VRF-RENAMED"}


def test_vrf_write_params_rd_id() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    v.vrfobject_rd_id = "65000:2"
    assert v.write_params() == {"vrfobject_rd_id": "65000:2"}


def test_vrf_write_params_rd_id_none_becomes_empty_string() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    v.vrfobject_rd_id = None
    assert v.write_params() == {"vrfobject_rd_id": ""}


def test_vrf_write_params_comment() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    v.vrfobject_comment = "updated description"
    assert v.write_params() == {"vrfobject_comment": "updated description"}


def test_vrf_write_params_row_enabled() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    v.row_enabled = RowEnabled.UNMANAGED
    assert v.write_params() == {"row_enabled": "2"}


def test_vrf_write_params_class_params() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    v.vrfobject_class_name = "new-class"
    v.class_params["ticket"] = "INC001"
    result = v.write_params()
    assert result["vrfobject_class_name"] == "new-class"
    assert "ticket=INC001" in result["vrfobject_class_parameters"]


def test_vrf_not_dirty_initially() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    assert v.write_params() == {}


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------


def test_vrf_build_request_create() -> None:
    v = Vrf(vrfobject_name="VRF-NEW", vrfobject_rd_id="65000:99")
    v.mark_new()
    verb, path, params = v.build_request("create")
    assert verb == "POST"
    assert path == "rest/vrf_vrfobject_add"
    assert params["vrfobject_name"] == "VRF-NEW"
    assert params["vrfobject_rd_id"] == "65000:99"
    assert "add_flag" not in params


def test_vrf_build_request_update() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    v.vrfobject_name = "VRF-UPDATED"
    verb, path, params = v.build_request("update")
    assert verb == "PUT"
    assert path == "rest/vrf_vrfobject_add"
    assert params["vrfobject_id"] == "7"
    assert params["vrfobject_name"] == "VRF-UPDATED"


def test_vrf_build_request_delete() -> None:
    v = Vrf.model_validate(_LIST_ROW)
    verb, path, params = v.build_request("delete")
    assert verb == "DELETE"
    assert path == "rest/vrf_vrfobject_delete"
    assert params["vrfobject_id"] == "7"


# ---------------------------------------------------------------------------
# Session / respx API-layer tests
# ---------------------------------------------------------------------------


@respx.mock
def test_vrf_list_returns_list_of_vrfs() -> None:
    respx.get(f"{BASE}rest/vrfobject_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW, _MINIMAL_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        vrfs = s.list(Vrf)
    assert len(vrfs) == 2
    assert all(isinstance(v, Vrf) for v in vrfs)
    assert vrfs[0].vrfobject_id == 7
    assert vrfs[1].vrfobject_id == 8


@respx.mock
def test_vrf_info_returns_single_vrf() -> None:
    respx.get(f"{BASE}rest/vrfobject_info").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        v = s.get(Vrf, 7)
    assert isinstance(v, Vrf)
    assert v.vrfobject_id == 7
    assert v.vrfobject_rd_id == "65000:1"


@respx.mock
def test_vrf_list_sends_where_param() -> None:
    route = respx.get(f"{BASE}rest/vrfobject_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Vrf, where="vrfobject_name='VRF-PROD'")
    assert route.calls.last.request.url.params["WHERE"] == "vrfobject_name='VRF-PROD'"


@respx.mock
def test_vrf_list_sends_limit_param() -> None:
    route = respx.get(f"{BASE}rest/vrfobject_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Vrf, limit=5)
    assert route.calls.last.request.url.params["limit"] == "5"


@respx.mock
def test_vrf_create_sends_post() -> None:
    route = respx.post(f"{BASE}rest/vrf_vrfobject_add").mock(
        return_value=httpx.Response(200, json=[{"errno": "0", "ret_oid": "9"}]),
    )
    with Session(HOST, *CREDS) as s:
        v = Vrf(vrfobject_name="VRF-NEW", vrfobject_rd_id="65000:50")
        s.new(v)
        s.flush()
    assert route.called
    sent_params = route.calls.last.request.url.params
    assert sent_params["vrfobject_name"] == "VRF-NEW"
    assert sent_params["vrfobject_rd_id"] == "65000:50"
    assert "add_flag" not in sent_params


@respx.mock
def test_vrf_update_sends_put() -> None:
    respx.get(f"{BASE}rest/vrfobject_info").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    route = respx.put(f"{BASE}rest/vrf_vrfobject_add").mock(
        return_value=httpx.Response(200, json=[{"errno": "0", "ret_oid": "7"}]),
    )
    with Session(HOST, *CREDS) as s:
        v = s.get(Vrf, 7)
        v.vrfobject_comment = "edited"
    assert route.called
    sent_params = route.calls.last.request.url.params
    assert sent_params["vrfobject_id"] == "7"
    assert sent_params["vrfobject_comment"] == "edited"


@respx.mock
def test_vrf_delete_sends_delete() -> None:
    respx.get(f"{BASE}rest/vrfobject_info").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    route = respx.delete(f"{BASE}rest/vrf_vrfobject_delete").mock(
        return_value=httpx.Response(200, json=[{"errno": "0"}]),
    )
    with Session(HOST, *CREDS) as s:
        v = s.get(Vrf, 7)
        s.delete(v)
    assert route.called
    sent_params = route.calls.last.request.url.params
    assert sent_params["vrfobject_id"] == "7"


@respx.mock
def test_vrf_expression_builder_where() -> None:
    route = respx.get(f"{BASE}rest/vrfobject_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Vrf, where=Vrf.c.vrfobject_name == "VRF-PROD")
    assert route.calls.last.request.url.params["WHERE"] == "vrfobject_name='VRF-PROD'"
