"""Basic smoke tests for sync and async clients."""

import hashlib

import httpx
import pytest
import respx

from eip_pydantic import AsyncEipClient, EipClient
from eip_pydantic.client import ApiKeyAuth
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
    with EipClient("solidserver.example.com", "admin", "wrong") as client, pytest.raises(AuthenticationError):
        client.get("ip_address")


@respx.mock
def test_sync_raises_404() -> None:
    respx.get(f"{BASE}missing").mock(return_value=httpx.Response(404, text="Not Found"))
    with EipClient("solidserver.example.com", "admin", "secret") as client, pytest.raises(NotFoundError):
        client.get("missing")


@respx.mock
def test_sync_raises_generic_api_error() -> None:
    respx.get(f"{BASE}bad").mock(return_value=httpx.Response(500, text="Server Error"))
    with EipClient("solidserver.example.com", "admin", "secret") as client, pytest.raises(ApiError):
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


# ---- API token authentication ---------------------------------------------

@respx.mock
def test_sync_client_api_token_auth_sends_signed_headers() -> None:
    route = respx.get(f"{BASE}ip_address").mock(return_value=httpx.Response(200, json=[{"id": "1"}]))
    with EipClient("solidserver.example.com", token_id="token-id", token_secret="token-secret") as client:
        result = client.get("ip_address")
    assert result == [{"id": "1"}]

    sent = route.calls.last.request
    ts = sent.headers["X-SDS-TS"]
    auth_header = sent.headers["Authorization"]
    assert auth_header.startswith("SDS token-id:")
    sig = auth_header.removeprefix("SDS token-id:")
    expected_string = f"token-secret\n{ts}\nGET\n{sent.url}"
    assert sig == hashlib.sha3_256(expected_string.encode()).hexdigest()


@respx.mock
async def test_async_client_api_token_auth_sends_signed_headers() -> None:
    route = respx.get(f"{BASE}ip_address").mock(return_value=httpx.Response(200, json=[{"id": "1"}]))
    async with AsyncEipClient("solidserver.example.com", token_id="token-id", token_secret="token-secret") as client:
        result = await client.get("ip_address")
    assert result == [{"id": "1"}]

    sent = route.calls.last.request
    ts = sent.headers["X-SDS-TS"]
    auth_header = sent.headers["Authorization"]
    assert auth_header.startswith("SDS token-id:")
    sig = auth_header.removeprefix("SDS token-id:")
    expected_string = f"token-secret\n{ts}\nGET\n{sent.url}"
    assert sig == hashlib.sha3_256(expected_string.encode()).hexdigest()


def test_client_requires_one_credential_pair() -> None:
    with pytest.raises(ValueError, match="Must specify either"):
        EipClient("solidserver.example.com")


def test_client_rejects_both_credential_pairs() -> None:
    with pytest.raises(ValueError, match="not both"):
        EipClient(
            "solidserver.example.com",
            "admin", "secret",
            token_id="token-id", token_secret="token-secret",
        )


def test_api_key_auth_flow_yields_signed_request() -> None:
    auth = ApiKeyAuth("token-id", "token-secret")
    request = httpx.Request("GET", f"{BASE}ip_address")
    flow = auth.auth_flow(request)
    signed = next(flow)
    ts = signed.headers["X-SDS-TS"]
    expected_string = f"token-secret\n{ts}\nGET\n{signed.url}"
    expected_sig = hashlib.sha3_256(expected_string.encode()).hexdigest()
    assert signed.headers["Authorization"] == f"SDS token-id:{expected_sig}"
