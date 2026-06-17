"""Tests for the write layer: dirty tracking, frozen enforcement, serialisation, Session."""

from ipaddress import IPv4Address, IPv4Network

import httpx
import pytest
import respx
from pydantic import ValidationError

from eip_pydantic import AsyncSession, Session, and_all
from eip_pydantic.expressions import Condition
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
        sn.subnet = IPv4Network("192.168.0.0/24")  # type: ignore[misc]


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
# id property, assign_id, and id_filter
# ---------------------------------------------------------------------------


def test_subnet_id() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    assert sn.id == 1


def test_space_id() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    assert sp.id == 7


def test_assign_id_bypasses_frozen() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.assign_id(99)
    assert sn.subnet_id == 99


def test_assign_id_does_not_dirty() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.assign_id(99)
    assert not sn.is_dirty


def test_id_filter_subnet() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    assert str(sn.id_filter) == "subnet_id='1'"


def test_id_filter_space() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    assert str(sp.id_filter) == "site_id='7'"


def test_id_filter_no_id_raises() -> None:
    class Bare(SolidServerModel):
        pass

    with pytest.raises(ValueError, match="no id"):
        _ = Bare().id_filter


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
    verb, path, params = Space.build_class_request("info", id=7)
    assert verb == "GET"
    assert path == "rest/ip_site_info"
    assert params == {"site_id": "7"}


def test_build_class_request_info_unknown_raises() -> None:
    class Unknown(SolidServerModel):
        pass

    with pytest.raises(TypeError, match="No fetch support"):
        Unknown.build_class_request("info", id=1)


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
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        spaces = s.list(Space)
    assert len(spaces) == 1
    assert isinstance(spaces[0], Space)
    assert spaces[0].site_id == 7


@respx.mock
def test_session_list_passes_where_and_limit() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Subnet, where="site_id='7'", limit=5)
    assert route.calls.last.request.url.params["WHERE"] == "site_id='7'"
    assert route.calls.last.request.url.params["limit"] == "5"


@respx.mock
def test_session_list_where_list_of_conditions() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Subnet, where=[Subnet.c.site_id == "7", Subnet.c.subnet_name == "test"])
    assert route.calls.last.request.url.params["WHERE"] == "(site_id='7') and (subnet_name='test')"


def test_and_all_single() -> None:
    c = Condition("x='1'")
    assert str(and_all([c])) == "x='1'"


def test_and_all_multiple() -> None:
    result = and_all([Condition("a='1'"), Condition("b='2'"), Condition("c='3'")])
    assert str(result) == "((a='1') and (b='2')) and (c='3')"


def test_and_all_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        and_all([])


@respx.mock
def test_session_list_auto_tracks_for_flush() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    route = respx.put(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    with Session(HOST, *CREDS) as s:
        spaces = s.list(Space)
        spaces[0].site_name = "renamed"
    assert route.called
    assert route.calls.last.request.url.params["site_name"] == "renamed"


# ---------------------------------------------------------------------------
# Session.one / Session.one_or_none
# ---------------------------------------------------------------------------


@respx.mock
def test_session_one_returns_single_object() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        sp = s.one(Space)
    assert isinstance(sp, Space)
    assert sp.site_id == 7


@respx.mock
def test_session_one_raises_on_empty() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[]),
    )
    with Session(HOST, *CREDS) as s, pytest.raises(ValueError, match="expected exactly 1 Space, got 0"):
        s.one(Space)


@respx.mock
def test_session_one_raises_on_multiple() -> None:
    second = {**_SPACE_ROW, "site_id": "8", "site_name": "other"}
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW, second]),
    )
    with Session(HOST, *CREDS) as s, pytest.raises(ValueError, match="expected exactly 1 Space, got 2"):
        s.one(Space)


@respx.mock
def test_session_one_or_none_returns_single_object() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        sp = s.one_or_none(Space)
    assert sp is not None
    assert sp.site_id == 7


@respx.mock
def test_session_one_or_none_returns_none_on_empty() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[]),
    )
    with Session(HOST, *CREDS) as s:
        assert s.one_or_none(Space) is None


@respx.mock
def test_session_one_or_none_raises_on_multiple() -> None:
    second = {**_SPACE_ROW, "site_id": "8", "site_name": "other"}
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW, second]),
    )
    with Session(HOST, *CREDS) as s, pytest.raises(ValueError, match="expected at most 1 Space, got 2"):
        s.one_or_none(Space)


@respx.mock
async def test_async_session_one_returns_single_object() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        sp = await s.one(Space)
    assert sp.site_id == 7


@respx.mock
async def test_async_session_one_or_none_returns_none_on_empty() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[]),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        assert await s.one_or_none(Space) is None


# ---------------------------------------------------------------------------
# Session.get — cache behaviour
# ---------------------------------------------------------------------------


@respx.mock
def test_session_get_returns_correct_object() -> None:
    respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        sp = s.get(Space, 7)
    assert isinstance(sp, Space)
    assert sp.site_id == 7


@respx.mock
def test_session_get_fetches_at_most_once() -> None:
    route = respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
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

    with Session(HOST, *CREDS) as s, pytest.raises(TypeError, match="No fetch support"):
        s.get(Unknown, 1)


@respx.mock
def test_session_list_returns_cached_instance_on_overlap() -> None:
    """If an object from list() is already in the cache, the cached instance is returned."""
    respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        sp_from_get = s.get(Space, 7)
        spaces = s.list(Space)
    assert spaces[0] is sp_from_get


@respx.mock
def test_session_list_preserves_dirty_state_on_overlap() -> None:
    """A dirty cached object is not overwritten when the same PK appears in list()."""
    respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    route = respx.put(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    with Session(HOST, *CREDS) as s:
        sp = s.get(Space, 7)
        sp.site_name = "mutated"
        spaces = s.list(Space)
        assert spaces[0] is sp
        assert spaces[0].site_name == "mutated"
    assert route.called
    assert route.calls.last.request.url.params["site_name"] == "mutated"


@respx.mock
def test_session_list_does_not_double_track() -> None:
    """Listing the same objects twice does not add them to the cache twice."""
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Space)
        s.list(Space)
        assert len(s._cache) == 1


@respx.mock
def test_session_list_then_get_uses_cache() -> None:
    route = respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    info_route = respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        spaces = s.list(Space)
        sp = s.get(Space, 7)
    assert route.call_count == 1
    assert info_route.call_count == 0   # served from cache populated by list()
    assert spaces[0] is sp


@respx.mock
def test_session_get_auto_flushes_on_mutation() -> None:
    """get() puts the object in cache; mutating it is flushed on exit without calling add()."""
    respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    route = respx.put(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    with Session(HOST, *CREDS) as s:
        sp = s.get(Space, 7)
        sp.site_name = "renamed"
    assert route.called
    assert route.calls.last.request.url.params["site_name"] == "renamed"


# ---------------------------------------------------------------------------
# Session.flush — update (PUT)
# ---------------------------------------------------------------------------


@respx.mock
def test_session_flush_subnet_update_sends_put() -> None:
    respx.get(f"{BASE}rest/ip_block_subnet_info").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    route = respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    with Session(HOST, *CREDS) as s:
        sn = s.get(Subnet, 1)
        sn.subnet_name = "renamed"
    assert route.called
    assert route.calls.last.request.url.params["subnet_name"] == "renamed"
    assert route.calls.last.request.url.params["subnet_id"] == "1"


@respx.mock
def test_session_flush_skips_clean_object() -> None:
    respx.get(f"{BASE}rest/ip_block_subnet_info").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    route = respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    with Session(HOST, *CREDS) as s:
        s.get(Subnet, 1)
    assert not route.called


@respx.mock
def test_session_flush_space_update_sends_put() -> None:
    respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    route = respx.put(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    with Session(HOST, *CREDS) as s:
        sp = s.get(Space, 7)
        sp.site_name = "renamed"
    assert route.called
    assert route.calls.last.request.url.params["site_name"] == "renamed"
    assert route.calls.last.request.url.params["site_id"] == "7"


@respx.mock
def test_session_flush_marks_object_clean_after_update() -> None:
    respx.get(f"{BASE}rest/ip_block_subnet_info").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    with Session(HOST, *CREDS) as s:
        sn = s.get(Subnet, 1)
        sn.subnet_name = "renamed"
    assert not sn.is_dirty


@respx.mock
def test_session_flush_no_flush_on_exception() -> None:
    respx.get(f"{BASE}rest/ip_block_subnet_info").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    route = respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    with pytest.raises(RuntimeError), Session(HOST, *CREDS) as s:  # noqa: PT012
        sn = s.get(Subnet, 1)
        sn.subnet_name = "renamed"
        raise RuntimeError("abort")
    assert not route.called


# ---------------------------------------------------------------------------
# Session.flush — create (POST)
# ---------------------------------------------------------------------------


@respx.mock
def test_session_flush_subnet_create_sends_post() -> None:
    route = respx.post(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    sn = Subnet.model_validate({**_SUBNET_ROW, "subnet_id": "0"})
    with Session(HOST, *CREDS) as s:
        s.new(sn)
        sn.subnet_name = "brand-new"
    assert route.called
    assert route.calls.last.request.url.params["subnet_addr"] == "10.0.0.0"
    assert route.calls.last.request.url.params["subnet_prefix"] == "24"


@respx.mock
def test_session_flush_subnet_create_assigns_pk() -> None:
    respx.post(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    sn = Subnet.model_validate({**_SUBNET_ROW, "subnet_id": "0"})
    with Session(HOST, *CREDS) as s:
        s.new(sn)
    assert sn.subnet_id == 42


@respx.mock
def test_session_flush_space_create_sends_post() -> None:
    route = respx.post(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
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
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    sp = Space.model_validate(_SPACE_ROW)
    with Session(HOST, *CREDS) as s:
        s.delete(sp)
    assert route.called
    assert route.calls.last.request.url.params["site_id"] == "7"


@respx.mock
def test_session_delete_removes_from_cache() -> None:
    route = respx.get(f"{BASE}rest/ip_site_info").mock(side_effect=[
        httpx.Response(200, json=[_SPACE_ROW]),
        httpx.Response(200, json=[_SPACE_ROW]),
    ])
    respx.delete(f"{BASE}rest/ip_site_delete").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
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
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        spaces = await s.list(Space)
    assert len(spaces) == 1
    assert spaces[0].site_id == 7


@respx.mock
async def test_async_session_get_fetches_once() -> None:
    route = respx.get(f"{BASE}rest/ip_site_info").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        sp1 = await s.get(Space, 7)
        sp2 = await s.get(Space, 7)
    assert route.call_count == 1
    assert sp1 is sp2


@respx.mock
async def test_async_session_flush_update_sends_put() -> None:
    respx.get(f"{BASE}rest/ip_block_subnet_info").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    route = respx.put(f"{BASE}rest/ip_subnet_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        sn = await s.get(Subnet, 1)
        sn.subnet_name = "renamed"
    assert route.called
    assert route.calls.last.request.url.params["subnet_name"] == "renamed"


@respx.mock
async def test_async_session_flush_create_sends_post() -> None:
    route = respx.post(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    sp = Space.model_validate({**_SPACE_ROW, "site_id": "0"})
    async with AsyncSession(HOST, *CREDS) as s:
        s.new(sp)
        sp.site_name = "brand-new"
    assert route.called
    assert sp.site_id == 42


@respx.mock
async def test_async_session_delete() -> None:
    route = respx.delete(f"{BASE}rest/ip_site_delete").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    sp = Space.model_validate(_SPACE_ROW)
    async with AsyncSession(HOST, *CREDS) as s:
        await s.delete(sp)
    assert route.called
    assert route.calls.last.request.url.params["site_id"] == "7"


# ---------------------------------------------------------------------------
# Session.list — select / offset / no_parent_class_param
# ---------------------------------------------------------------------------


@respx.mock
def test_session_list_select_offset_no_parent_class_param() -> None:
    route = respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Space, select="site_id,site_name", offset=5, no_parent_class_param=True)
    params = dict(route.calls.last.request.url.params)
    assert params["SELECT"] == "site_id,site_name"
    assert params["offset"] == "5"
    assert params["NO_PARENT_CLASS_PARAM"] == "1"


# ---------------------------------------------------------------------------
# Session / AsyncSession — unknown HTTP verb
# ---------------------------------------------------------------------------


def test_session_dispatch_unknown_verb_raises() -> None:
    with Session(HOST, *CREDS) as s, pytest.raises(ValueError, match="Unsupported"):
        s._dispatch("PATCH", "rest/ip_site_list", {})


@respx.mock
async def test_async_session_dispatch_unknown_verb_raises() -> None:
    async with AsyncSession(HOST, *CREDS) as s:
        with pytest.raises(ValueError, match="Unsupported"):
            await s._dispatch("PATCH", "rest/ip_site_list", {})


# ---------------------------------------------------------------------------
# build_class_request / build_request / parse_response / apply_response
# ---------------------------------------------------------------------------


def test_build_class_request_no_parent_class_param() -> None:
    _, _, params = Space.build_class_request("list", no_parent_class_param=True)
    assert params["NO_PARENT_CLASS_PARAM"] == "1"


def test_build_request_info_success() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    verb, path, params = sp.build_request("info")
    assert verb == "GET"
    assert path == "rest/ip_site_info"
    assert params == {"site_id": "7"}


def test_apply_response_update_clears_dirty() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    sp.site_name = "changed"
    assert sp.is_dirty
    sp.apply_response("update", {})
    assert not sp.is_dirty


def test_apply_response_delete_noop() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    sp.apply_response("delete", {})


# ---------------------------------------------------------------------------
# BaseSession.create — write_params seeded from create_fields on mark_new
# ---------------------------------------------------------------------------


def test_create_space_write_params_has_name() -> None:
    sp = Space(site_name="new-space")
    sp.mark_new()
    params = sp.write_params()
    assert params["site_name"] == "new-space"


def test_create_space_write_params_excludes_none() -> None:
    sp = Space(site_name="new-space")
    sp.mark_new()
    params = sp.write_params()
    assert "site_description" not in params


def test_create_space_write_params_bool_field() -> None:
    sp = Space(site_name="tmpl", site_is_template=True)
    sp.mark_new()
    params = sp.write_params()
    assert params["site_is_template"] == "1"


def test_create_subnet_write_params_excludes_renamed_fields() -> None:
    sn = Subnet(site_id=7, subnet=IPv4Network("10.0.0.0/24"), subnet_name="test-net")
    sn.mark_new()
    params = sn.write_params()
    # subnet is not directly emitted; build_request injects subnet_addr/subnet_prefix
    assert "subnet" not in params
    # placement fields reach the request via build_request
    _, _, req_params = sn.build_request("create")
    assert req_params["subnet_addr"] == "10.0.0.0"
    assert req_params["subnet_prefix"] == "24"
    assert req_params["site_id"] == "7"


def test_create_subnet_write_params_mutable_fields() -> None:
    sn = Subnet(site_id=7, start_hostaddr=IPv4Address("10.0.0.0"), subnet_size=256,
                subnet_name="my-net", subnet_level=1)
    sn.mark_new()
    params = sn.write_params()
    assert params["subnet_name"] == "my-net"
    assert params["subnet_level"] == "1"


@respx.mock
def test_session_create_space_sends_post() -> None:
    route = respx.post(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(200, json=_ADD_RESPONSE),
    )
    with Session(HOST, *CREDS) as s:
        sp = s.create(Space, site_name="new-space", site_description="Created via SDK")
    assert route.called
    params = route.calls.last.request.url.params
    assert params["site_name"] == "new-space"
    assert params["site_description"] == "Created via SDK"
    assert sp.site_id == 42


@respx.mock
def test_session_create_rejects_unknown_fields() -> None:
    with Session(HOST, *CREDS) as s:
        with pytest.raises(TypeError, match="not allowed at creation"):
            s.create(Space, site_id=99)  # type: ignore[call-arg]
