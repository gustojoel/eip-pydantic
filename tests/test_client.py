"""Basic smoke tests for sync and async clients."""

import httpx
import pytest
import respx

from eip_pydantic import AsyncEipClient, EipClient
from eip_pydantic.exceptions import ApiError, AuthenticationError, NotFoundError


BASE = "https://solidserver.example.com/"


@respx.mock
def test_sync_get_ok() -> None:
    respx.get(f"{BASE}ip_address").mock(return_value=httpx.Response(200, json=[{"id": "1"}]))
    with EipClient("solidserver.example.com", "admin", "secret") as client:
        result = client.get("ip_address")
    assert result == [{"id": "1"}]


@respx.mock
def test_sync_raises_401() -> None:
    respx.get(f"{BASE}ip_address").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with EipClient("solidserver.example.com", "admin", "wrong") as client:
        with pytest.raises(AuthenticationError):
            client.get("ip_address")


@respx.mock
def test_sync_raises_404() -> None:
    respx.get(f"{BASE}missing").mock(return_value=httpx.Response(404, text="Not Found"))
    with EipClient("solidserver.example.com", "admin", "secret") as client:
        with pytest.raises(NotFoundError):
            client.get("missing")


@respx.mock
def test_sync_raises_generic_api_error() -> None:
    respx.get(f"{BASE}bad").mock(return_value=httpx.Response(500, text="Server Error"))
    with EipClient("solidserver.example.com", "admin", "secret") as client:
        with pytest.raises(ApiError):
            client.get("bad")


@respx.mock
async def test_async_get_ok() -> None:
    respx.get(f"{BASE}ip_address").mock(return_value=httpx.Response(200, json=[{"id": "2"}]))
    async with AsyncEipClient("solidserver.example.com", "admin", "secret") as client:
        result = await client.get("ip_address")
    assert result == [{"id": "2"}]


@respx.mock
async def test_async_raises_401() -> None:
    respx.get(f"{BASE}ip_address").mock(return_value=httpx.Response(401, text="Unauthorized"))
    async with AsyncEipClient("solidserver.example.com", "admin", "wrong") as client:
        with pytest.raises(AuthenticationError):
            await client.get("ip_address")


@respx.mock
def test_sync_get_204_returns_empty_list() -> None:
    respx.get(f"{BASE}rest/ip_block_subnet_list").mock(return_value=httpx.Response(204))
    with EipClient("solidserver.example.com", "admin", "secret") as client:
        result = client.get("rest/ip_block_subnet_list")
    assert result == []


@respx.mock
async def test_async_get_204_returns_empty_list() -> None:
    respx.get(f"{BASE}rest/ip_block_subnet_list").mock(return_value=httpx.Response(204))
    async with AsyncEipClient("solidserver.example.com", "admin", "secret") as client:
        result = await client.get("rest/ip_block_subnet_list")
    assert result == []


@respx.mock
def test_session_list_returns_empty_on_204() -> None:
    from eip_pydantic import Session
    from eip_pydantic.models.subnet import Subnet
    respx.get(f"{BASE}rest/ip_block_subnet_list").mock(return_value=httpx.Response(204))
    with Session("solidserver.example.com", "admin", "secret") as s:
        result = s.list(Subnet)
    assert result == []
