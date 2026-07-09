"""Tests for FreeAddress model methods and Session.find_free_address."""

from ipaddress import IPv4Address

import httpx
import pytest
import respx

from eip_pydantic import AsyncSession, InternalError, Session
from eip_pydantic.models.address import FreeAddress
from eip_pydantic.models.pool import Pool
from eip_pydantic.models.subnet import Subnet



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

_ROW_A: dict[str, str] = {
    "errno": "0",
    "ip_addr": "0a000001",   # 10.0.0.1
    "hostaddr": "10.0.0.1",
    "site_id": "7",
    "site_name": "global",
    "subnet_id": "3",
    "subnet_name": "root-block",
    "pool_id": "0",
    "pool_name": "",
}

_ROW_B: dict[str, str] = {
    "errno": "0",
    "ip_addr": "0a000002",   # 10.0.0.2
    "hostaddr": "10.0.0.2",
    "site_id": "7",
    "site_name": "global",
    "subnet_id": "3",
    "subnet_name": "root-block",
    "pool_id": "0",
    "pool_name": "",
}

_SUBNET_ROW: dict[str, str] = {
    "errno": "0", "subnet_id": "3", "subnet_name": "root-block",
    "site_id": "7", "start_hostaddr": "10.0.0.0",
    "start_ip_addr": "0a000000", "subnet_size": "256", "row_enabled": "1",
}
_POOL_ROW: dict[str, str] = {
    "errno": "0", "pool_id": "5", "pool_name": "dhcp-range",
    "site_id": "7", "subnet_id": "3",
    "start_ip_addr": "0a000001", "end_ip_addr": "0a0000ff", "pool_size": "255",
}


# ---------------------------------------------------------------------------
# FreeAddress model coercion
# ---------------------------------------------------------------------------

def test_free_address_hex_ip() -> None:
    a = FreeAddress.model_validate(_ROW_A)
    assert a.ip_addr == IPv4Address("10.0.0.1")


def test_free_address_dotted_ip() -> None:
    a = FreeAddress.model_validate(_ROW_A)
    assert a.hostaddr == IPv4Address("10.0.0.1")


def test_free_address_int_fields() -> None:
    a = FreeAddress.model_validate(_ROW_A)
    assert a.site_id == 7
    assert a.subnet_id == 3
    assert a.pool_id == 0


def test_free_address_string_fields() -> None:
    a = FreeAddress.model_validate(_ROW_A)
    assert a.site_name == "global"
    assert a.subnet_name == "root-block"


def test_free_address_no_pk() -> None:
    a = FreeAddress.model_validate(_ROW_A)
    assert a.id is None


def test_free_address_extra_field_captured() -> None:
    row = {**_ROW_A, "future_field": "val"}
    a = FreeAddress.model_validate(row)
    assert a.model_extra is not None
    assert "future_field" in a.model_extra


def test_free_address_non_dict_passthrough() -> None:
    sentinel = object()
    assert FreeAddress._coerce(sentinel) is sentinel


# ---------------------------------------------------------------------------
# FreeAddress.build_class_request — model-level tests
# ---------------------------------------------------------------------------

def test_build_class_request_subnet_int() -> None:
    verb, path, params = FreeAddress.build_class_request("find_free", subnet=3)
    assert verb == "OPTIONS"
    assert path == "rpc/ip_find_free_address"
    assert params["subnet_id"] == "3"
    assert "pool_id" not in params
    assert "parent_subnet_id" not in params


def test_build_class_request_subnet_object() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    _, _, params = FreeAddress.build_class_request("find_free", subnet=sn)
    assert params["subnet_id"] == "3"


def test_build_class_request_pool_int() -> None:
    _, _, params = FreeAddress.build_class_request("find_free", pool=5)
    assert params["pool_id"] == "5"


def test_build_class_request_pool_object() -> None:
    p = Pool.model_validate(_POOL_ROW)
    _, _, params = FreeAddress.build_class_request("find_free", pool=p)
    assert params["pool_id"] == "5"


def test_build_class_request_parent_subnet_int() -> None:
    _, _, params = FreeAddress.build_class_request("find_free", parent_subnet=3)
    assert params["parent_subnet_id"] == "3"


def test_build_class_request_parent_subnet_object() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    _, _, params = FreeAddress.build_class_request("find_free", parent_subnet=sn)
    assert params["parent_subnet_id"] == "3"


def test_build_class_request_max_find() -> None:
    _, _, params = FreeAddress.build_class_request("find_free", subnet=3, max_find=20)
    assert params["max_find"] == "20"


def test_build_class_request_no_target_raises() -> None:
    with pytest.raises(ValueError, match=r"subnet.*pool.*parent_subnet"):
        FreeAddress.build_class_request("find_free")


def test_build_class_request_wrong_operation_raises() -> None:
    with pytest.raises(InternalError):
        FreeAddress.build_class_request("list")


# ---------------------------------------------------------------------------
# FreeAddress.parse_response — model-level tests
# ---------------------------------------------------------------------------

def test_parse_response_returns_list() -> None:
    result = FreeAddress.parse_response("find_free", [_ROW_A, _ROW_B])
    assert len(result) == 2
    assert all(isinstance(r, FreeAddress) for r in result)
    assert result[0].hostaddr == IPv4Address("10.0.0.1")
    assert result[1].hostaddr == IPv4Address("10.0.0.2")


def test_parse_response_empty() -> None:
    assert FreeAddress.parse_response("find_free", []) == []


def test_parse_response_wrong_operation_raises() -> None:
    with pytest.raises(InternalError):
        FreeAddress.parse_response("list", [])


# ---------------------------------------------------------------------------
# Session.find_free_address — integration with mock HTTP
# ---------------------------------------------------------------------------

@respx.mock
def test_find_free_address_subnet_sends_options() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_address").mock(
        return_value=httpx.Response(200, json=[_ROW_A, _ROW_B]),
    )
    with Session(HOST, *CREDS) as s:
        results = s.find_free_address(subnet=3)
    assert route.called
    assert route.calls.last.request.url.params["subnet_id"] == "3"
    assert len(results) == 2
    assert all(isinstance(r, FreeAddress) for r in results)
    assert results[0].hostaddr == IPv4Address("10.0.0.1")


@respx.mock
def test_find_free_address_pool_object() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_address").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    p = Pool.model_validate(_POOL_ROW)
    with Session(HOST, *CREDS) as s:
        s.find_free_address(pool=p)
    assert route.calls.last.request.url.params["pool_id"] == "5"


@respx.mock
def test_find_free_address_parent_subnet_object() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_address").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    sn = Subnet.model_validate(_SUBNET_ROW)
    with Session(HOST, *CREDS) as s:
        s.find_free_address(parent_subnet=sn)
    assert route.calls.last.request.url.params["parent_subnet_id"] == "3"


@respx.mock
def test_find_free_address_max_find() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_address").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    with Session(HOST, *CREDS) as s:
        s.find_free_address(subnet=3, max_find=20)
    assert route.calls.last.request.url.params["max_find"] == "20"


@respx.mock
def test_find_free_address_empty_result() -> None:
    respx.options(f"{BASE}rpc/ip_find_free_address").mock(
        return_value=httpx.Response(200, json=[]),
    )
    with Session(HOST, *CREDS) as s:
        results = s.find_free_address(subnet=3)
    assert results == []


def test_find_free_address_no_target_raises() -> None:
    with Session(HOST, *CREDS) as s, pytest.raises(ValueError, match=r"subnet.*pool.*parent_subnet"):
        s.find_free_address()


# ---------------------------------------------------------------------------
# AsyncSession.find_free_address
# ---------------------------------------------------------------------------

@respx.mock
async def test_async_find_free_address() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_address").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        results = await s.find_free_address(subnet=3)
    assert route.called
    assert len(results) == 1
    assert results[0].hostaddr == IPv4Address("10.0.0.1")


@respx.mock
async def test_async_find_free_address_all_optional_params() -> None:
    route = respx.options(f"{BASE}rpc/ip_find_free_address").mock(
        return_value=httpx.Response(200, json=[_ROW_A]),
    )
    async with AsyncSession(HOST, *CREDS) as s:
        await s.find_free_address(subnet=3, pool=5, parent_subnet=3, max_find=20)
    p = route.calls.last.request.url.params
    assert p["subnet_id"] == "3"
    assert p["pool_id"] == "5"
    assert p["parent_subnet_id"] == "3"
    assert p["max_find"] == "20"


@respx.mock
async def test_async_find_free_address_no_target_raises() -> None:
    async with AsyncSession(HOST, *CREDS) as s:
        with pytest.raises(ValueError, match=r"subnet.*pool.*parent_subnet"):
            await s.find_free_address()
