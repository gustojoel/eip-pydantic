"""Tests for the write layer: dirty tracking, frozen enforcement, serialisation, Session."""

from ipaddress import IPv4Address

import httpx
import pytest
import respx
from pydantic import ValidationError

from eip_pydantic import AsyncSession, Session
from eip_pydantic.models.base import RowEnabled, SolidServerModel
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet

BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

_SPACE_ROW: dict[str, str] = {
    "errno": "0",
    "site_id": "7",
    "site_name": "global",
    "site_description": "Global address space",
    "site_is_template": "0",
    "site_class_name": "",
    "parent_site_id": "0",
    "row_enabled": "1",
    "multistatus": "",
    "tree_level": "0",
    "tree_path": "global#",
    "tree_id_path": "#7#",
    "site_class_parameters": "",
    "site_class_parameters_properties": "",
    "site_class_parameters_inheritance_source": "",
}

_SUBNET_ROW: dict[str, str] = {
    "errno": "0",
    "subnet_id": "1",
    "subnet_name": "test-net",
    "site_id": "7",
    "start_hostaddr": "10.0.0.0",
    "start_ip_addr": "0a000000",
    "subnet_size": "256",
    "row_enabled": "1",
    "is_terminal": "0",
    "lock_network_broadcast": "0",
    "is_in_orphan": "0",
    "subnet_class_name": "",
    "subnet_class_parameters": "",
    "subnet_class_parameters_properties": "",
}

_ADD_RESPONSE: list[dict[str, str]] = [{"ret_oid": "42", "errno": "0"}]

# ---------------------------------------------------------------------------
# Dirty tracking
# ---------------------------------------------------------------------------


def test_newly_loaded_object_is_clean() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    assert not sn.is_dirty


def test_setting_mutable_field_marks_dirty() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.subnet_name = "renamed"
    assert sn.is_dirty
    assert "subnet_name" in sn._dirty


def test_mark_clean_clears_dirty() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.subnet_name = "renamed"
    sn.mark_clean()
    assert not sn.is_dirty


def test_multiple_dirty_fields_tracked() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.subnet_name = "renamed"
    sn.row_enabled = RowEnabled.UNMANAGED
    assert sn._dirty == {"subnet_name", "row_enabled"}


def test_space_mutable_field_marks_dirty() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    sp.site_description = "updated"
    assert sp.is_dirty
    assert "site_description" in sp._dirty


# ---------------------------------------------------------------------------
# Frozen field enforcement
# ---------------------------------------------------------------------------


def test_frozen_subnet_pk_raises() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    with pytest.raises(ValidationError):
        sn.subnet_id = 99  # type: ignore[misc]


def test_frozen_ip_address_raises() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    with pytest.raises(ValidationError):
        sn.start_hostaddr = IPv4Address("10.0.0.1")  # type: ignore[misc]


def test_frozen_site_linkage_on_subnet_raises() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    with pytest.raises(ValidationError):
        sn.site_id = 99  # type: ignore[misc]


def test_frozen_errno_raises() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    with pytest.raises(ValidationError):
        sn.errno = 1  # type: ignore[misc]


def test_frozen_space_pk_raises() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    with pytest.raises(ValidationError):
        sp.site_id = 99  # type: ignore[misc]


def test_frozen_tree_path_raises() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    with pytest.raises(ValidationError):
        sp.tree_path = "bad/"  # type: ignore[misc]


def test_mutable_subnet_name_does_not_raise() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.subnet_name = "ok"


def test_mutable_space_name_does_not_raise() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    sp.site_name = "ok"


# ---------------------------------------------------------------------------
# pk property and assign_pk
# ---------------------------------------------------------------------------


def test_subnet_pk() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    assert sn.pk == 1


def test_space_pk() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    assert sp.pk == 7


def test_assign_pk_bypasses_frozen() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.assign_pk(99)
    assert sn.subnet_id == 99


def test_assign_pk_does_not_dirty() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.assign_pk(99)
    assert not sn.is_dirty


# ---------------------------------------------------------------------------
# write_params
# ---------------------------------------------------------------------------


def test_empty_dirty_returns_empty_params() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    assert sn.write_params() == {}


def test_write_params_string_field() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.subnet_name = "renamed"
    assert sn.write_params() == {"subnet_name": "renamed"}


def test_write_params_row_enabled() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.row_enabled = RowEnabled.UNMANAGED
    assert sn.write_params() == {"row_enabled": "2"}


def test_write_params_bool_true() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.is_terminal = True
    assert sn.write_params() == {"is_terminal": "1"}


def test_write_params_bool_false() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.lock_network_broadcast = False
    assert sn.write_params() == {"lock_network_broadcast": "0"}


def test_write_params_none_becomes_empty_string() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.subnet_class_name = None
    assert sn.write_params() == {"subnet_class_name": ""}


def test_write_params_multiple_fields() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.subnet_name = "x"
    sn.is_terminal = True
    params = sn.write_params()
    assert params["subnet_name"] == "x"
    assert params["is_terminal"] == "1"


def test_space_write_params_string() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    sp.site_name = "renamed"
    assert sp.write_params() == {"site_name": "renamed"}


def test_space_write_params_row_enabled() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    sp.row_enabled = RowEnabled.DELETED
    assert sp.write_params() == {"row_enabled": "0"}


# ---------------------------------------------------------------------------
# Class-parameter helpers
# ---------------------------------------------------------------------------


def test_set_class_parameter_marks_dirty() -> None:
    sn = Subnet.model_validate({**_SUBNET_ROW, "subnet_class_parameters": "foo=1"})
    sn.set_class_parameter("bar", "2")
    assert sn.is_dirty
    assert sn.class_parameters == {"foo": "1", "bar": "2"}


def test_delete_class_parameter_marks_dirty() -> None:
    sn = Subnet.model_validate({**_SUBNET_ROW, "subnet_class_parameters": "foo=1&bar=2"})
    sn.delete_class_parameter("foo")
    assert sn.is_dirty
    assert sn.class_parameters == {"bar": "2"}


def test_set_class_parameter_on_empty_blob() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.set_class_parameter("key", "val")
    assert sn.class_parameters == {"key": "val"}


def test_delete_class_parameter_missing_key_is_noop() -> None:
    sn = Subnet.model_validate({**_SUBNET_ROW, "subnet_class_parameters": "foo=1"})
    sn.delete_class_parameter("nonexistent")
    assert sn.class_parameters == {"foo": "1"}


# ---------------------------------------------------------------------------
# build_class_request
# ---------------------------------------------------------------------------


def test_build_class_request_list_space_no_args() -> None:
    verb, path, params = Space.build_class_request("list")
    assert verb == "GET"
    assert path == "rest/ip_site_list"
    assert params == {}


def test_build_class_request_list_with_where_and_limit() -> None:
    verb, path, params = Subnet.build_class_request("list", where="site_id='7'", limit=10)
    assert verb == "GET"
    assert path == "rest/ip_block_subnet_list"
    assert params["WHERE"] == "site_id='7'"
    assert params["limit"] == "10"


def test_build_class_request_info_space() -> None:
    verb, path, params = Space.build_class_request("info", pk=7)
    assert verb == "GET"
    assert path == "rest/ip_site_info"
    assert params == {"site_id": "7"}


def test_build_class_request_info_unknown_raises() -> None:
    class Unknown(SolidServerModel):
        pass

    with pytest.raises(TypeError, match="No fetch support"):
        Unknown.build_class_request("info", pk=1)


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------


def test_build_request_update_subnet() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.subnet_name = "renamed"
    verb, path, params = sn.build_request("update")
    assert verb == "PUT"
    assert path == "rest/ip_subnet_add"
    assert params["subnet_name"] == "renamed"
    assert params["subnet_id"] == "1"


def test_build_request_update_space() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    sp.site_name = "renamed"
    verb, path, params = sp.build_request("update")
    assert verb == "PUT"
    assert path == "rest/ip_site_add"
    assert params["site_name"] == "renamed"
    assert params["site_id"] == "7"


def test_build_request_create_subnet_injects_addr_and_prefix() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    verb, path, params = sn.build_request("create")
    assert verb == "POST"
    assert path == "rest/ip_subnet_add"
    assert params["subnet_addr"] == "10.0.0.0"
    assert params["subnet_prefix"] == "24"
    assert params["site_id"] == "7"


def test_build_request_delete_subnet() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    verb, path, params = sn.build_request("delete")
    assert verb == "DELETE"
    assert path == "rest/ip_block_subnet_delete"
    assert params == {"subnet_id": "1"}


# ---------------------------------------------------------------------------
# Session.list — auto-tracks and dispatches GET
# ---------------------------------------------------------------------------


@respx.mock
def test_session_list_returns_objects() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW])
    )
    with Session(HOST, *CREDS) as s:
        spaces = s.list(Space)
    assert len(spaces) == 1
    assert isinstance(spaces[0], Space)
    assert spaces[0].site_id == 7


@respx.mock
def test_session_list_passes_where_and_limit() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW])
    )
    with Session(HOST, *CREDS) as s:
        s.list(Subnet, where="site_id='7'", limit=5)
    assert route.calls[0].request.url.params["WHERE"] == "site_id='7'"
    assert route.calls[0].request.url.params["limit"] == "5"


@respx.mock
def test_session_list_auto_tracks_for_flush() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW])
    )
    route = respx.put(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    with Session(HOST, *CREDS) as s:
        spaces = s.list(Space)
        spaces[0].site_name = "renamed"
    assert route.called
    assert route.calls[0].request.url.params["site_name"] == "renamed"


# ---------------------------------------------------------------------------
# Session.get — cache behaviour
# ---------------------------------------------------------------------------


@respx.mock
def test_session_get_returns_correct_object() -> None:
    respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW])
    )
    with Session(HOST, *CREDS) as s:
        sp = s.get(Space, 7)
    assert isinstance(sp, Space)
    assert sp.site_id == 7


@respx.mock
def test_session_get_fetches_at_most_once() -> None:
    route = respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW])
    )
    with Session(HOST, *CREDS) as s:
        sp1 = s.get(Space, 7)
        sp2 = s.get(Space, 7)
        sp3 = s.get(Space, 7)
    assert route.call_count == 1
    assert sp1 is sp2 is sp3


@respx.mock
def test_session_get_different_pks_fetch_separately() -> None:
    child_row = {**_SPACE_ROW, "site_id": "12", "site_name": "child"}
    route = respx.get(f"{BASE}rest/ip_site_info").mock(side_effect=[
        httpx.Response(200, json=[_SPACE_ROW]),
        httpx.Response(200, json=[child_row]),
    ])
    with Session(HOST, *CREDS) as s:
        sp7 = s.get(Space, 7)
        sp12 = s.get(Space, 12)
    assert route.call_count == 2
    assert sp7.site_id == 7
    assert sp12.site_id == 12
    assert sp7 is not sp12


@respx.mock
def test_session_get_unknown_type_raises() -> None:
    class Unknown(SolidServerModel):
        pass

    with Session(HOST, *CREDS) as s:
        with pytest.raises(TypeError, match="No fetch support"):
            s.get(Unknown, 1)


@respx.mock
def test_session_list_then_get_uses_cache() -> None:
    route = respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW])
    )
    info_route = respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW])
    )
    with Session(HOST, *CREDS) as s:
        spaces = s.list(Space)
        sp = s.get(Space, 7)
    assert route.call_count == 1
    assert info_route.call_count == 0   # served from cache populated by list()
    assert spaces[0] is sp


# ---------------------------------------------------------------------------
# Session.flush — update (PUT)
# ---------------------------------------------------------------------------


@respx.mock
def test_session_flush_subnet_update_sends_put() -> None:
    route = respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sn = Subnet.model_validate(_SUBNET_ROW)
    with Session(HOST, *CREDS) as s:
        s.add(sn)
        sn.subnet_name = "renamed"
    assert route.called
    assert route.calls[0].request.url.params["subnet_name"] == "renamed"
    assert route.calls[0].request.url.params["subnet_id"] == "1"


@respx.mock
def test_session_flush_skips_clean_object() -> None:
    route = respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sn = Subnet.model_validate(_SUBNET_ROW)
    with Session(HOST, *CREDS) as s:
        s.add(sn)
    assert not route.called


@respx.mock
def test_session_flush_space_update_sends_put() -> None:
    route = respx.put(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sp = Space.model_validate(_SPACE_ROW)
    with Session(HOST, *CREDS) as s:
        s.add(sp)
        sp.site_name = "renamed"
    assert route.called
    assert route.calls[0].request.url.params["site_name"] == "renamed"
    assert route.calls[0].request.url.params["site_id"] == "7"


@respx.mock
def test_session_flush_marks_object_clean_after_update() -> None:
    respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sn = Subnet.model_validate(_SUBNET_ROW)
    with Session(HOST, *CREDS) as s:
        s.add(sn)
        sn.subnet_name = "renamed"
    assert not sn.is_dirty


@respx.mock
def test_session_flush_no_flush_on_exception() -> None:
    route = respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sn = Subnet.model_validate(_SUBNET_ROW)
    with pytest.raises(RuntimeError):
        with Session(HOST, *CREDS) as s:
            s.add(sn)
            sn.subnet_name = "renamed"
            raise RuntimeError("abort")
    assert not route.called


# ---------------------------------------------------------------------------
# Session.flush — create (POST)
# ---------------------------------------------------------------------------


@respx.mock
def test_session_flush_subnet_create_sends_post() -> None:
    route = respx.post(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sn = Subnet.model_validate({**_SUBNET_ROW, "subnet_id": "0"})
    with Session(HOST, *CREDS) as s:
        s.new(sn)
        sn.subnet_name = "brand-new"
    assert route.called
    assert route.calls[0].request.url.params["subnet_addr"] == "10.0.0.0"
    assert route.calls[0].request.url.params["subnet_prefix"] == "24"


@respx.mock
def test_session_flush_subnet_create_assigns_pk() -> None:
    respx.post(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sn = Subnet.model_validate({**_SUBNET_ROW, "subnet_id": "0"})
    with Session(HOST, *CREDS) as s:
        s.new(sn)
    assert sn.subnet_id == 42


@respx.mock
def test_session_flush_space_create_sends_post() -> None:
    route = respx.post(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sp = Space.model_validate({**_SPACE_ROW, "site_id": "0"})
    with Session(HOST, *CREDS) as s:
        s.new(sp)
        sp.site_name = "brand-new"
    assert route.called
    assert sp.site_id == 42


# ---------------------------------------------------------------------------
# Session.delete
# ---------------------------------------------------------------------------


@respx.mock
def test_session_delete_sends_delete_request() -> None:
    route = respx.delete(f"{BASE}rest/ip_site_delete").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sp = Space.model_validate(_SPACE_ROW)
    with Session(HOST, *CREDS) as s:
        s.delete(sp)
    assert route.called
    assert route.calls[0].request.url.params["site_id"] == "7"


@respx.mock
def test_session_delete_removes_from_cache() -> None:
    route = respx.get(f"{BASE}rest/ip_site_info").mock(side_effect=[
        httpx.Response(200, json=[_SPACE_ROW]),
        httpx.Response(200, json=[_SPACE_ROW]),
    ])
    respx.delete(f"{BASE}rest/ip_site_delete").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    with Session(HOST, *CREDS) as s:
        sp = s.get(Space, 7)        # call 1 — API hit
        s.delete(sp)
        s.get(Space, 7)             # call 2 — cache cleared, API hit again
    assert route.call_count == 2


# ---------------------------------------------------------------------------
# Async Session
# ---------------------------------------------------------------------------


@respx.mock
async def test_async_session_list_returns_objects() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW])
    )
    async with AsyncSession(HOST, *CREDS) as s:
        spaces = await s.list(Space)
    assert len(spaces) == 1
    assert spaces[0].site_id == 7


@respx.mock
async def test_async_session_get_fetches_once() -> None:
    route = respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW])
    )
    async with AsyncSession(HOST, *CREDS) as s:
        sp1 = await s.get(Space, 7)
        sp2 = await s.get(Space, 7)
    assert route.call_count == 1
    assert sp1 is sp2


@respx.mock
async def test_async_session_flush_update_sends_put() -> None:
    route = respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE)
    )
    sn = Subnet.model_validate(_SUBNET_ROW)
    async with AsyncSession(HOST, *CREDS) as s:
        s.add(sn)
        sn.subnet_name = "renamed"
    assert route.called
    assert route.calls[0].request.url.params["subnet_name"] == "renamed"
