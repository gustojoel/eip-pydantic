"""Tests for ip_site_count and ip_block_subnet_count via Session.count()."""

import httpx
import pytest
import respx

from eip_pydantic import AsyncSession, Session
from eip_pydantic.models.base import SolidServerModel
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

_COUNT_7 = [{"total": "7"}]
_COUNT_0 = [{"total": "0"}]


# ---------------------------------------------------------------------------
# build_class_request("count") — model-level
# ---------------------------------------------------------------------------

def test_space_count_request() -> None:
    verb, path, params = Space.build_class_request("count")
    assert verb == "GET"
    assert path == "rest/ip_site_count"
    assert params == {}


def test_subnet_count_request() -> None:
    verb, path, params = Subnet.build_class_request("count")
    assert verb == "GET"
    assert path == "rest/ip_block_subnet_count"
    assert params == {}


def test_count_request_with_where() -> None:
    _, _, params = Space.build_class_request("count", where="site_name='global'")
    assert params["WHERE"] == "site_name='global'"


def test_count_request_with_tags() -> None:
    _, _, params = Space.build_class_request("count", tags="site.owner")
    assert params["TAGS"] == "site.owner"


def test_count_request_with_no_parent_class_param() -> None:
    _, _, params = Space.build_class_request("count", no_parent_class_param=True)
    assert params["NO_PARENT_CLASS_PARAM"] == "1"


def test_count_request_no_count_path_raises() -> None:
    with pytest.raises(TypeError, match="No count support"):
        SolidServerModel.build_class_request("count")


# ---------------------------------------------------------------------------
# parse_response("count") — model-level
# ---------------------------------------------------------------------------

def test_parse_response_count() -> None:
    assert Space.parse_response("count", _COUNT_7) == 7


def test_parse_response_count_zero() -> None:
    assert Subnet.parse_response("count", _COUNT_0) == 0


# ---------------------------------------------------------------------------
# Session.count — sync
# ---------------------------------------------------------------------------

@respx.mock
def test_session_count_space() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    with Session(HOST, *CREDS) as s:
        n = s.count(Space)
    assert route.called
    assert n == 7


@respx.mock
def test_session_count_subnet() -> None:
    _ = respx.get(f"{BASE}rest/ip_block_subnet_count").mock(
        return_value=httpx.Response(200, json=_COUNT_0),
    )
    with Session(HOST, *CREDS) as s:
        n = s.count(Subnet)
    assert n == 0


@respx.mock
def test_session_count_with_where_string() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    with Session(HOST, *CREDS) as s:
        s.count(Space, where="site_name='global'")
    assert route.calls.last.request.url.params["WHERE"] == "site_name='global'"
    assert "TAGS" not in route.calls.last.request.url.params


@respx.mock
def test_session_count_with_condition_no_tags() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    with Session(HOST, *CREDS) as s:
        s.count(Space, where=Space.c.site_name == "global")
    params = route.calls.last.request.url.params
    assert params["WHERE"] == "site_name='global'"
    assert "TAGS" not in params


@respx.mock
def test_session_count_condition_auto_injects_tags() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    with Session(HOST, *CREDS) as s:
        s.count(Space, where=Space.c.owner == "team-a")
    params = route.calls.last.request.url.params
    assert params["WHERE"] == "tag_site_owner='team-a'"
    assert params["TAGS"] == "site.owner"


@respx.mock
def test_session_count_merges_explicit_and_auto_tags() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    with Session(HOST, *CREDS) as s:
        s.count(Space, where=Space.c.owner == "team-a", tags="site.region")
    params = route.calls.last.request.url.params
    assert "site.owner" in params["TAGS"]
    assert "site.region" in params["TAGS"]


@respx.mock
def test_session_count_no_parent_class_param() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    with Session(HOST, *CREDS) as s:
        s.count(Space, no_parent_class_param=True)
    assert route.calls.last.request.url.params["NO_PARENT_CLASS_PARAM"] == "1"


# ---------------------------------------------------------------------------
# AsyncSession.count
# ---------------------------------------------------------------------------

@respx.mock
async def test_async_session_count_space() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        n = await s.count(Space)
    assert route.called
    assert n == 7


@respx.mock
async def test_async_session_count_with_where() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_count").mock(
        return_value=httpx.Response(200, json=_COUNT_0),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        n = await s.count(Subnet, where=Subnet.c.site_id == "7")
    assert n == 0
    assert route.calls.last.request.url.params["WHERE"] == "site_id='7'"


@respx.mock
async def test_async_session_count_condition_auto_injects_tags() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        n = await s.count(Space, where=Space.c.owner == "team-a", tags="site.region")
    params = route.calls.last.request.url.params
    assert "site.owner" in params["TAGS"]
    assert "site.region" in params["TAGS"]
    assert n == 7


@respx.mock
def test_session_count_iterable_conditions() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    conditions = [Space.c.site_name == "prod", Space.c.site_name != "staging"]
    with Session(HOST, *CREDS) as s:
        n = s.count(Space, where=conditions)
    params = route.calls.last.request.url.params
    assert "site_name='prod'" in params["WHERE"]
    assert "site_name!='staging'" in params["WHERE"]
    assert n == 7


@respx.mock
def test_session_count_iterable_with_tags_auto_inject() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    conditions = [Space.c.owner == "team-a", Space.c.site_name == "prod"]
    with Session(HOST, *CREDS) as s:
        s.count(Space, where=conditions)
    params = route.calls.last.request.url.params
    assert "site.owner" in params["TAGS"]


@respx.mock
async def test_async_session_count_iterable_conditions() -> None:
    route = respx.get(f"{BASE}rest/ip_site_count").mock(
        return_value=httpx.Response(200, json=_COUNT_7),
    )
    conditions = [Space.c.site_name == "prod", Space.c.owner == "team-a"]
    async with AsyncSession(HOST, *CREDS) as s:
        n = await s.count(Space, where=conditions)
    params = route.calls.last.request.url.params
    assert "site_name='prod'" in params["WHERE"]
    assert "site.owner" in params["TAGS"]
    assert n == 7
