"""Tests for FreeSubnet model methods and Session.find_free_subnet."""

from ipaddress import IPv4Address

import httpx
import pytest
import respx

from eip_pydantic import AsyncSession, InternalError, Session
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import FreeSubnet, Subnet



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

_ROW_A: dict[str, str] = {
    "errno": "0",
    "start_ip_addr": "0a000000",   # 10.0.0.0
    "start_hostaddr": "10.0.0.0",
    "block_name": "root-block",
    "cost": "0",
    "block_id": "3",
    "site_id": "7",
}

_ROW_B: dict[str, str] = {
    "errno": "0",
    "start_ip_addr": "0a000100",   # 10.0.1.0
    "start_hostaddr": "10.0.1.0",
    "block_name": "root-block",
    "cost": "1",
    "block_id": "3",
    "site_id": "7",
}

_SPACE_ROW: dict[str, str] = {
    "errno": "0", "site_id": "7", "site_name": "global",
    "row_enabled": "1", "tree_level": "0",
}
_SUBNET_ROW: dict[str, str] = {
    "errno": "0", "subnet_id": "3", "subnet_name": "root-block",
    "site_id": "7", "start_hostaddr": "10.0.0.0",
    "start_ip_addr": "0a000000", "subnet_size": "256", "row_enabled": "1",
}


# ---------------------------------------------------------------------------
# FreeSubnet model coercion
# ---------------------------------------------------------------------------

def test_free_subnet_hex_ip() -> None:
    s = FreeSubnet.model_validate(_ROW_A)
    assert s.start_ip_addr == IPv4Address("10.0.0.0")


def test_free_subnet_dotted_ip() -> None:
    s = FreeSubnet.model_validate(_ROW_A)
    assert s.start_hostaddr == IPv4Address("10.0.0.0")


def test_free_subnet_int_fields() -> None:
    s = FreeSubnet.model_validate(_ROW_A)
    assert s.cost == 0
    assert s.block_id == 3
    assert s.site_id == 7


def test_free_subnet_string_field() -> None:
    s = FreeSubnet.model_validate(_ROW_A)
    assert s.block_name == "root-block"


def test_free_subnet_no_pk() -> None:
    s = FreeSubnet.model_validate(_ROW_A)
    assert s.id is None


def test_free_subnet_extra_field_captured() -> None:
    row = {**_ROW_A, "future_field": "val"}
    s = FreeSubnet.model_validate(row)
    assert s.model_extra is not None
    assert "future_field" in s.model_extra


def test_free_subnet_non_dict_passthrough() -> None:
    sentinel = object()
    assert FreeSubnet._coerce(sentinel) is sentinel


# ---------------------------------------------------------------------------
# FreeSubnet.build_class_request — model-level tests
# ---------------------------------------------------------------------------

def test_build_class_request_prefix() -> None:
    verb, path, params = FreeSubnet.build_class_request("find_free", prefix=30)
    assert verb == "OPTIONS"
    assert path == "rpc/ip_find_free_subnet"
    assert params["prefix"] == "30"
    assert "size" not in params


def test_build_class_request_size() -> None:
    _, _, params = FreeSubnet.build_class_request("find_free", size=256)
    assert params["size"] == "256"
    assert "prefix" not in params


def test_build_class_request_space_int() -> None:
    _, _, params = FreeSubnet.build_class_request("find_free", prefix=24, space=7)
    assert params["site_id"] == "7"


def test_build_class_request_space_object() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    _, _, params = FreeSubnet.build_class_request("find_free", prefix=24, space=sp)
    assert params["site_id"] == "7"


def test_build_class_request_subnet_int() -> None:
    _, _, params = FreeSubnet.build_class_request("find_free", prefix=30, subnet=3)
    assert params["block_id"] == "3"


def test_build_class_request_subnet_object() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    _, _, params = FreeSubnet.build_class_request("find_free", prefix=30, subnet=sn)
    assert params["block_id"] == "3"


def test_build_class_request_all_params() -> None:
    _, _, params = FreeSubnet.build_class_request(
        "find_free",
        prefix=30, space=7, subnet=3, max_find=20,
        begin_addr="10.0.0.0", end_addr="10.255.255.255",
        use_searched_path=True, where="cost='0'",
    )
    assert params["prefix"] == "30"
    assert params["site_id"] == "7"
    assert params["block_id"] == "3"
    assert params["max_find"] == "20"
    assert params["begin_addr"] == "10.0.0.0"
    assert params["end_addr"] == "10.255.255.255"
    assert params["use_searched_path"] == "1"
    assert params["WHERE"] == "cost='0'"


def test_build_class_request_use_searched_path_false() -> None:
    _, _, params = FreeSubnet.build_class_request("find_free", prefix=30, use_searched_path=False)
    assert params["use_searched_path"] == "0"


def test_build_class_request_no_prefix_or_size_raises() -> None:
    with pytest.raises(ValueError, match=r"prefix.*size"):
        FreeSubnet.build_class_request("find_free")


def test_build_class_request_wrong_operation_raises() -> None:
    with pytest.raises(InternalError):
        FreeSubnet.build_class_request("list")


# ---------------------------------------------------------------------------
# FreeSubnet.parse_response — model-level tests
# ---------------------------------------------------------------------------

def test_parse_response_returns_list() -> None:
    result = FreeSubnet.parse_response("find_free", [_ROW_A, _ROW_B])
    assert len(result) == 2
    assert all(isinstance(r, FreeSubnet) for r in result)
    assert result[0].cost == 0
    assert result[1].cost == 1


def test_parse_response_empty() -> None:
    assert FreeSubnet.parse_response("find_free", []) == []


def test_parse_response_wrong_operation_raises() -> None:
    with pytest.raises(InternalError):
        FreeSubnet.parse_response("list", [])


# ---------------------------------------------------------------------------
# Session.find_free_subnet — integration with mock HTTP
# ---------------------------------------------------------------------------

@respx.mock
def test_find_free_subnet_prefix_sends_options() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_subnet").mock(
        return_value=httpx.Response(200, json=[_ROW_A, _ROW_B]),
    )
    with Session(HOST, *CREDS) as s:
        results = s.find_free_subnet(prefix=24, space=7)
    assert route.called
    assert route.calls.last.request.url.params["prefix"] == "24"
    assert route.calls.last.request.url.params["site_id"] == "7"
    assert len(results) == 2
    assert all(isinstance(r, FreeSubnet) for r in results)
    assert results[0].start_hostaddr == IPv4Address("10.0.0.0")


@respx.mock
def test_find_free_subnet_size_param() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_subnet").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    with Session(HOST, *CREDS) as s:
        s.find_free_subnet(size=256)
    assert route.calls.last.request.url.params["size"] == "256"


@respx.mock
def test_find_free_subnet_space_object() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_subnet").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    sp = Space.model_validate(_SPACE_ROW)
    with Session(HOST, *CREDS) as s:
        s.find_free_subnet(prefix=30, space=sp)
    assert route.calls.last.request.url.params["site_id"] == "7"


@respx.mock
def test_find_free_subnet_subnet_object() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_subnet").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    sn = Subnet.model_validate(_SUBNET_ROW)
    with Session(HOST, *CREDS) as s:
        s.find_free_subnet(prefix=30, subnet=sn)
    assert route.calls.last.request.url.params["block_id"] == "3"


@respx.mock
def test_find_free_subnet_empty_result() -> None:
    respx.options(f"{BASE}rpc/ip_find_free_subnet").mock(
        return_value=httpx.Response(200, json=[]),
    )
    with Session(HOST, *CREDS) as s:
        results = s.find_free_subnet(prefix=24)
    assert results == []


def test_find_free_subnet_no_prefix_or_size_raises() -> None:
    with Session(HOST, *CREDS) as s, pytest.raises(ValueError, match=r"prefix.*size"):
        s.find_free_subnet()


# ---------------------------------------------------------------------------
# AsyncSession.find_free_subnet
# ---------------------------------------------------------------------------

@respx.mock
async def test_async_find_free_subnet() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_subnet").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        results = await s.find_free_subnet(prefix=30, space=7)
    assert route.called
    assert len(results) == 1
    assert results[0].cost == 0


@respx.mock
async def test_async_find_free_subnet_all_optional_params() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_subnet").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        await s.find_free_subnet(
            size=256,
            space=7,
            max_find=5,
            begin_addr="10.0.0.0",
            end_addr="10.255.255.255",
            subnet=3,
            use_searched_path=True,
            where="cost='0'",
        )
    p = route.calls.last.request.url.params
    assert p["size"] == "256"
    assert p["site_id"] == "7"
    assert p["max_find"] == "5"
    assert p["begin_addr"] == "10.0.0.0"
    assert p["end_addr"] == "10.255.255.255"
    assert p["block_id"] == "3"
    assert p["use_searched_path"] == "1"
    assert p["WHERE"] == "cost='0'"


@respx.mock
async def test_async_find_free_subnet_no_prefix_or_size_raises() -> None:
    async with AsyncSession(HOST, *CREDS) as s:
        with pytest.raises(ValueError, match=r"prefix.*size"):
            await s.find_free_subnet()
