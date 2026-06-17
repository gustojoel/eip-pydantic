"""Shared fixtures for live integration tests.

Copy .env.example to .env and fill in your credentials before running:

    poetry run pytest tests/integration/ -v

Write tests use TEST_SITE_ID and TEST_IP_NETWORK to control which IPAM space
and address range are used.  Test objects are NOT deleted after the run so the
state can be inspected on the server.
"""

import os
from collections.abc import AsyncIterator, Iterator
from ipaddress import IPv4Network

import pytest
from dotenv import load_dotenv

from eip_pydantic import AsyncSession, Session



load_dotenv()

_HOST = os.getenv("EIP_HOST", "")
_USERNAME = os.getenv("EIP_USERNAME", "")
_PASSWORD = os.getenv("EIP_PASSWORD", "")
_VERIFY = os.getenv("EIP_VERIFY", "true").lower() != "false"

_CREDS_AVAILABLE = bool(_HOST and _USERNAME and _PASSWORD)


def _skip_if_no_creds() -> None:
    if not _CREDS_AVAILABLE:
        pytest.skip("EIP_HOST / EIP_USERNAME / EIP_PASSWORD not set in .env")


def open_session() -> Session:
    """Open a non-managed Session.  Caller must call ``_client.close()``."""
    _skip_if_no_creds()
    return Session(_HOST, _USERNAME, _PASSWORD, verify=_VERIFY)


@pytest.fixture(scope="session")
def session() -> Iterator[Session]:
    _skip_if_no_creds()
    with Session(_HOST, _USERNAME, _PASSWORD, verify=_VERIFY) as s:
        yield s


@pytest.fixture
async def async_session() -> AsyncIterator[AsyncSession]:
    _skip_if_no_creds()
    async with AsyncSession(_HOST, _USERNAME, _PASSWORD, verify=_VERIFY) as s:
        yield s


@pytest.fixture
def write_session() -> Iterator[Session]:
    """Function-scoped session for write tests; caller manages ``flush()`` explicitly.

    The HTTP client is closed at teardown but the session is NOT auto-flushed,
    so uncommitted state does not leak between tests.
    """
    _skip_if_no_creds()
    s = Session(_HOST, _USERNAME, _PASSWORD, verify=_VERIFY)
    try:
        yield s
    finally:
        s._client.close()


@pytest.fixture(scope="session")
def test_site_id() -> int:
    """ID of the IPAM space used for write integration tests."""
    return int(os.getenv("TEST_SITE_ID", "24"))


@pytest.fixture(scope="session")
def test_network() -> IPv4Network:
    """CIDR block from which all write-test subnets and addresses are drawn."""
    return IPv4Network(os.getenv("TEST_IP_NETWORK", "100.64.0.0/10"))


@pytest.fixture(scope="session")
def test_nested_site_id() -> int:
    """ID of a pre-existing nested IPAM space used for Space/Subnet integration tests.

    The API user lacks permission to create or modify Space objects, so this
    space must already exist on the server.  Set TEST_NESTED_SITE_ID in .env
    to override.
    """
    return int(os.getenv("TEST_NESTED_SITE_ID", "25"))
