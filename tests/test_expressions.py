"""Tests for the WHERE / ORDER BY expression builder."""

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.expressions import ColumnCollection, OrderByExpr
from eip_pydantic.models.base import SolidServerModel
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

_SPACE_ROW = {"errno": "0", "site_id": "7", "site_name": "global",
              "row_enabled": "1", "tree_level": "0"}
_SUBNET_ROW = {"errno": "0", "subnet_id": "1", "subnet_name": "test-net",
               "site_id": "7", "start_hostaddr": "10.0.0.0",
               "start_ip_addr": "0a000000", "subnet_size": "256", "row_enabled": "1"}


# ---------------------------------------------------------------------------
# Condition string serialisation
# ---------------------------------------------------------------------------

def test_eq_real_field() -> None:
    cond = Subnet.c.subnet_name == "prod-dmz"
    assert str(cond) == "subnet_name='prod-dmz'"
    assert cond.required_tags == frozenset()


def test_ne_real_field() -> None:
    cond = Subnet.c.subnet_name != "prod-dmz"
    assert str(cond) == "subnet_name!='prod-dmz'"


def test_lt_real_field() -> None:
    assert str(Subnet.c.subnet_id < 256) == "subnet_id<'256'"


def test_le_real_field() -> None:
    assert str(Subnet.c.subnet_id <= 256) == "subnet_id<='256'"


def test_gt_real_field() -> None:
    assert str(Subnet.c.subnet_id > 0) == "subnet_id>'0'"


def test_ge_real_field() -> None:
    assert str(Subnet.c.subnet_id >= 128) == "subnet_id>='128'"


def test_like() -> None:
    assert str(Subnet.c.subnet_name.like("%prod%")) == "subnet_name like '%prod%'"


def test_in_() -> None:
    assert str(Subnet.c.site_id.in_(["1", "2", "3"])) == "site_id in ('1', '2', '3')"


def test_is_null() -> None:
    assert str(Subnet.c.subnet_name.is_null()) == "subnet_name=''"


def test_asc() -> None:
    expr = Subnet.c.subnet_name.asc()
    assert isinstance(expr, OrderByExpr)
    assert str(expr) == "subnet_name ASC"
    assert expr.required_tags == frozenset()


def test_desc() -> None:
    assert str(Subnet.c.subnet_id.desc()) == "subnet_id DESC"


def test_single_quote_escaping() -> None:
    cond = Subnet.c.subnet_name == "O'Brien"
    assert str(cond) == "subnet_name='O''Brien'"


def test_int_value_becomes_string() -> None:
    assert str(Subnet.c.site_id == 7) == "site_id='7'"


# ---------------------------------------------------------------------------
# AND / OR combining
# ---------------------------------------------------------------------------

def test_and_combines_conditions() -> None:
    cond = (Subnet.c.site_id == "7") & (Subnet.c.subnet_name == "foo")
    assert str(cond) == "(site_id='7') and (subnet_name='foo')"


def test_or_combines_conditions() -> None:
    cond = (Subnet.c.site_id == "7") | (Subnet.c.site_id == "8")
    assert str(cond) == "(site_id='7') or (site_id='8')"


def test_and_unions_required_tags() -> None:
    cond = (Subnet.c.foobar == "baz") & (Subnet.c.priority == "1")
    assert cond.required_tags == frozenset({"network.foobar", "network.priority"})


def test_or_unions_required_tags() -> None:
    cond = (Subnet.c.foobar == "x") | (Space.c.bar == "y")
    assert "network.foobar" in cond.required_tags
    assert "site.bar" in cond.required_tags


# ---------------------------------------------------------------------------
# Tagged class parameters
# ---------------------------------------------------------------------------

def test_unknown_field_on_subnet_uses_network_prefix() -> None:
    cond = Subnet.c.foobar == "baz"
    assert str(cond) == "tag_network_foobar='baz'"
    assert cond.required_tags == frozenset({"network.foobar"})


def test_unknown_field_on_space_uses_site_prefix() -> None:
    cond = Space.c.mykey == "val"
    assert str(cond) == "tag_site_mykey='val'"
    assert cond.required_tags == frozenset({"site.mykey"})


def test_tagged_orderby_asc() -> None:
    expr = Subnet.c.priority.asc()
    assert str(expr) == "tag_network_priority ASC"
    assert expr.required_tags == frozenset({"network.priority"})


def test_tagged_orderby_desc() -> None:
    expr = Space.c.rank.desc()
    assert str(expr) == "tag_site_rank DESC"
    assert expr.required_tags == frozenset({"site.rank"})


def test_tagged_like() -> None:
    cond = Subnet.c.description.like("%prod%")
    assert str(cond) == "tag_network_description like '%prod%'"
    assert cond.required_tags == frozenset({"network.description"})


def test_tagged_in_() -> None:
    cond = Subnet.c.env.in_(["prod", "staging"])
    assert str(cond) == "tag_network_env in ('prod', 'staging')"
    assert cond.required_tags == frozenset({"network.env"})


# ---------------------------------------------------------------------------
# Session.list TAGS auto-injection
# ---------------------------------------------------------------------------

@respx.mock
def test_session_list_auto_injects_tags_from_where() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Subnet, where=Subnet.c.foobar == "baz")
    params = route.calls.last.request.url.params
    assert params["WHERE"] == "tag_network_foobar='baz'"
    assert params["TAGS"] == "network.foobar"


@respx.mock
def test_session_list_auto_injects_tags_from_orderby() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Subnet, orderby=Subnet.c.priority.asc())
    params = route.calls.last.request.url.params
    assert params["ORDERBY"] == "tag_network_priority ASC"
    assert params["TAGS"] == "network.priority"


@respx.mock
def test_session_list_merges_auto_and_explicit_tags() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Subnet, where=Subnet.c.foobar == "baz", tags="network.other")
    params = route.calls.last.request.url.params
    assert "network.foobar" in params["TAGS"]
    assert "network.other" in params["TAGS"]


@respx.mock
def test_session_list_real_field_no_tags_injected() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Subnet, where=Subnet.c.subnet_name == "foo")
    params = route.calls.last.request.url.params
    assert params["WHERE"] == "subnet_name='foo'"
    assert "TAGS" not in params


@respx.mock
def test_session_list_condition_where_with_str_orderby() -> None:
    route = respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Space, where=Space.c.site_name == "global", orderby="site_name ASC")
    params = route.calls.last.request.url.params
    assert params["WHERE"] == "site_name='global'"
    assert params["ORDERBY"] == "site_name ASC"
    assert "TAGS" not in params


# ---------------------------------------------------------------------------
# ColumnExpr hashability
# ---------------------------------------------------------------------------

def test_column_expr_is_hashable() -> None:
    expr = Subnet.c.subnet_name
    s = {expr}
    assert expr in s


# ---------------------------------------------------------------------------
# Repr
# ---------------------------------------------------------------------------

def test_condition_repr() -> None:
    cond = Subnet.c.subnet_name == "foo"
    assert repr(cond) == "Condition(\"subnet_name='foo'\")"


def test_orderby_repr() -> None:
    expr = Subnet.c.subnet_name.asc()
    assert repr(expr) == "OrderByExpr('subnet_name ASC')"


# ---------------------------------------------------------------------------
# ColumnCollection
# ---------------------------------------------------------------------------

def test_column_collection_dir_returns_field_names() -> None:
    names = dir(Subnet.c)
    assert "subnet_id" in names
    assert "subnet_name" in names


def test_column_collection_private_attr_raises() -> None:
    with pytest.raises(AttributeError):
        _ = Subnet.c._private


def test_column_collection_no_prefix_unknown_field() -> None:
    col = ColumnCollection(SolidServerModel)
    cond = col.any_field == "x"
    assert str(cond) == "any_field='x'"
    assert cond.required_tags == frozenset()
