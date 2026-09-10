"""Shared fixtures for live integration tests.

Copy .env.example to .env and fill in your credentials before running:

    poetry run pytest tests/integration/ -v

Write tests use TEST_SITE_ID and TEST_IP_NETWORK to control which IPAM space
and address range are used.

Each session-scoped fixture below uses a delete-then-create pattern: any object
with the fixture's stable name that was left over from a previous run is deleted
first, then a fresh copy is created.  This ensures every test run exercises both
the delete and create paths.

Address-space layout (first /16 of TEST_IP_NETWORK, default 100.64.0.0/16):

    block              /16  (subnet_level=0)  idx —
      child_subnet     /24                    idx 10
        pool           .10–.20 within child
        pool_ro        .21–.30 within child
        grandchild     /28 (.128–.143)
      terminal_subnet  /24  (is_terminal)     idx 11
        addr1          .100
      nolock           /24                    idx 12
      classparam       /24                    idx 13
      transient (delete tests)                idx 250
"""

import os
from collections.abc import AsyncIterator, Iterator
from ipaddress import IPv4Address, IPv4Network
from typing import TypeVar

import pytest
from dotenv import load_dotenv

from eip_pydantic import AsyncSession, Session
from eip_pydantic.models.address import IpAddress
from eip_pydantic.models.pool import Pool
from eip_pydantic.models.subnet import Subnet



load_dotenv()

_HOST = os.getenv("EIP_HOST", "")
_USERNAME = os.getenv("EIP_USERNAME", "")
_PASSWORD = os.getenv("EIP_PASSWORD", "")
_TOKEN_ID = os.getenv("EIP_TOKEN_ID", "")
_TOKEN_SECRET = os.getenv("EIP_TOKEN_SECRET", "")
_VERIFY = os.getenv("EIP_VERIFY", "true").lower() != "false"

# API token auth takes priority when both credential pairs are present in .env.
_USE_TOKEN_AUTH = bool(_TOKEN_ID and _TOKEN_SECRET)
_CREDS_AVAILABLE = bool(_HOST and (_USE_TOKEN_AUTH or (_USERNAME and _PASSWORD)))


def _skip_if_no_creds() -> None:
    if not _CREDS_AVAILABLE:
        pytest.skip(
            "EIP_HOST and either EIP_TOKEN_ID/EIP_TOKEN_SECRET or "
            "EIP_USERNAME/EIP_PASSWORD not set in .env",
        )


_ST = TypeVar("_ST", Session, AsyncSession)


def _new_session(cls: type[_ST]) -> _ST:
    if _USE_TOKEN_AUTH:
        return cls(_HOST, token_id=_TOKEN_ID, token_secret=_TOKEN_SECRET, verify=_VERIFY)
    return cls(_HOST, _USERNAME, _PASSWORD, verify=_VERIFY)


def open_session() -> Session:
    """Open a non-managed Session.  Caller must call ``_client.close()``."""
    _skip_if_no_creds()
    return _new_session(Session)


@pytest.fixture(scope="session")
def session() -> Iterator[Session]:
    _skip_if_no_creds()
    with _new_session(Session) as s:
        yield s


@pytest.fixture
async def async_session() -> AsyncIterator[AsyncSession]:
    _skip_if_no_creds()
    async with _new_session(AsyncSession) as s:
        yield s


@pytest.fixture
def write_session() -> Iterator[Session]:
    """Function-scoped session for write tests; caller manages ``flush()`` explicitly.

    The HTTP client is closed at teardown but the session is NOT auto-flushed,
    so uncommitted state does not leak between tests.
    """
    _skip_if_no_creds()
    s = _new_session(Session)
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


# ---------------------------------------------------------------------------
# Address-space helpers (shared across test files)
# ---------------------------------------------------------------------------

def _block(base: IPv4Network) -> IPv4Network:
    """First /16 from *base* (or *base* itself if already /16 or smaller)."""
    if base.prefixlen >= 16:
        return base
    return next(base.subnets(new_prefix=16))


def _child_24s(base: IPv4Network) -> list[IPv4Network]:
    """All /24 subnets within the first /16 of *base*."""
    return list(_block(base).subnets(new_prefix=24))


# ---------------------------------------------------------------------------
# Stable names (so fixtures can locate leftovers from previous runs)
# ---------------------------------------------------------------------------

_BLOCK_NAME      = "pytest-block"
_CHILD_NAME      = "pytest-child-10"
_TERMINAL_NAME   = "pytest-terminal-11"
_NOLOCK_NAME     = "pytest-nolock-12"
_CLASSPARAM_NAME = "pytest-classparam-13"
_POOL_NAME       = "pytest-pool-1"
_POOL_RO_NAME    = "pytest-pool-readonly"
_IP1_NAME        = "pytest-addr-100"
_GRANDCHILD_NAME = "pytest-grandchild-28"
_VLSM_NAME       = "pytest-vlsm-14"

_MAC_INITIAL = "52:54:00:AB:CD:01"
_MAC_UPDATED = "52:54:00:AB:CD:02"

# Indices into the /24 list
_IDX_CHILD      = 10
_IDX_TERMINAL   = 11
_IDX_NOLOCK     = 12
_IDX_CLASSPARAM = 13
_IDX_VLSM       = 14  # non-terminal /24 for grandchild (VLSM nesting) tests

# Pool occupies .10–.20 within the child /24; RO pool occupies .21–.30
_POOL_OFFSET_START    = 10
_POOL_OFFSET_END      = 20
_POOL_RO_OFFSET_START = 21
_POOL_RO_OFFSET_END   = 30

# Test IP: .100 within the terminal /24
_IP_OFFSET = 100

# Grandchild /28: 9th /28 within the child /24 (index 8 → starts at .128)
_IDX_GRANDCHILD_28 = 8


# ---------------------------------------------------------------------------
# Session-scoped setup fixtures
#
# Each fixture opens its own short-lived session.  Before creating the target
# object, it searches by stable name and deletes any leftover from a prior run,
# ensuring that both the delete and create paths are exercised on every run.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def block(test_site_id: int, test_network: IPv4Network) -> Subnet:
    """Delete any leftover pytest-block, then create a fresh /16 block subnet."""
    block_net = _block(test_network)
    s = open_session()
    try:
        for existing in s.list(Subnet, where=Subnet.c.subnet_name == _BLOCK_NAME, limit=10):
            s.delete(existing)
        sn = s.create(
            Subnet,
            site_id=test_site_id,
            subnet=block_net,
            subnet_name=_BLOCK_NAME,
            subnet_level=0,
        )
        s.flush()
    finally:
        s._client.close()
    return sn


@pytest.fixture(scope="session")
def child_subnet(block: Subnet, test_network: IPv4Network) -> Subnet:
    """Delete any leftover pytest-child-10, then create a fresh /24 child."""
    net = _child_24s(test_network)[_IDX_CHILD]
    assert block.subnet_id is not None
    s = open_session()
    try:
        for existing in s.list(Subnet, where=Subnet.c.subnet_name == _CHILD_NAME, limit=10):
            s.delete(existing)
        sn = s.create(
            Subnet,
            site_id=block.site_id,
            parent_subnet_id=block.subnet_id,
            subnet=net,
            subnet_name=_CHILD_NAME,
        )
        s.flush()
    finally:
        s._client.close()
    return sn


@pytest.fixture(scope="session")
def terminal_subnet(block: Subnet, test_network: IPv4Network) -> Subnet:
    """Delete any leftover pytest-terminal-11, then create a fresh is_terminal /24."""
    net = _child_24s(test_network)[_IDX_TERMINAL]
    assert block.subnet_id is not None
    s = open_session()
    try:
        for existing in s.list(Subnet, where=Subnet.c.subnet_name == _TERMINAL_NAME, limit=10):
            s.delete(existing)
        sn = s.create(
            Subnet,
            site_id=block.site_id,
            parent_subnet_id=block.subnet_id,
            subnet=net,
            subnet_name=_TERMINAL_NAME,
            is_terminal=True,
        )
        s.flush()
    finally:
        s._client.close()
    return sn


@pytest.fixture(scope="session")
def pool(child_subnet: Subnet, test_network: IPv4Network) -> Pool:
    """Delete any leftover pytest-pool-1, then create a fresh pool within child /24."""
    base = int(_child_24s(test_network)[_IDX_CHILD].network_address)
    start = IPv4Address(base + _POOL_OFFSET_START)
    end   = IPv4Address(base + _POOL_OFFSET_END)
    assert child_subnet.subnet_id is not None
    s = open_session()
    try:
        for existing in s.list(Pool, where=Pool.c.pool_name == _POOL_NAME, limit=10):
            s.delete(existing)
        p = s.create(
            Pool,
            subnet_id=child_subnet.subnet_id,
            start_ip_addr=start,
            end_ip_addr=end,
            pool_name=_POOL_NAME,
        )
        s.flush()
    finally:
        s._client.close()
    return p


@pytest.fixture(scope="session")
def addr1(terminal_subnet: Subnet, test_network: IPv4Network) -> IpAddress:
    """Delete any leftover pytest-addr-100, then create a fresh IP address.

    IPs can only be added to terminal subnets on this server; ip_add silently
    returns HTTP 200 with empty body (no ret_oid) for non-terminal subnets.
    For terminal subnets the normal JSON response with ret_oid is returned.
    """
    base = int(_child_24s(test_network)[_IDX_TERMINAL].network_address)
    ip = IPv4Address(base + _IP_OFFSET)
    assert terminal_subnet.site_id is not None
    s = open_session()
    try:
        for existing in s.list(IpAddress, where=f"hostaddr='{ip}'", limit=5):
            s.delete(existing)
        a = s.create(
            IpAddress,
            site_id=terminal_subnet.site_id,
            hostaddr=ip,
            subnet_id=terminal_subnet.subnet_id,
            name=_IP1_NAME,
            mac_addr=_MAC_INITIAL,
        )
        s.flush()
        if a.ip_id is None:
            # ip_add returned empty body — look up by address
            found = s.list(IpAddress, where=f"hostaddr='{ip}'", limit=1)
            if found and found[0].ip_id:
                a = found[0]
        # Explicitly set MAC via PUT — the server silently ignores mac_addr in
        # POST upsert (new_edit) mode when the IP already exists and the
        # requested MAC is already registered to another record.
        a.mac_addr = _MAC_INITIAL
        s.flush()
    finally:
        s._client.close()
    return a


@pytest.fixture(scope="session")
def vlsm_subnet(block: Subnet, test_network: IPv4Network) -> Subnet:
    """Delete any leftover pytest-vlsm-14, then create a fresh non-terminal /24.

    This server requires that a subnet be non-terminal (is_terminal=False) before
    child subnets can be nested inside it.  ``child_subnet`` (idx 10) is terminal
    because it holds pools; we use this separate subnet for 3-level nesting tests.
    """
    net = _child_24s(test_network)[_IDX_VLSM]
    assert block.subnet_id is not None
    s = open_session()
    try:
        # Delete grandchild first: deleting vlsm orphans it, and an orphaned /28
        # inside the range causes errno 5002 "Subnet overlap" when re-creating the /24.
        for existing in s.list(Subnet, where=Subnet.c.subnet_name == _GRANDCHILD_NAME, limit=10):
            s.delete(existing)
        for existing in s.list(Subnet, where=Subnet.c.subnet_name == _VLSM_NAME, limit=10):
            s.delete(existing)
        sn = s.create(
            Subnet,
            site_id=block.site_id,
            parent_subnet_id=block.subnet_id,
            subnet=net,
            subnet_name=_VLSM_NAME,
            is_terminal=False,
        )
        s.flush()
    finally:
        s._client.close()
    return sn


@pytest.fixture(scope="session")
def grandchild_subnet(vlsm_subnet: Subnet, test_network: IPv4Network) -> Subnet:
    """Delete any leftover pytest-grandchild-28, then create a fresh /28 inside vlsm_subnet.

    Network: the 9th /28 within the vlsm /24 (starts at .128).
    The server requires site_id even when parent_subnet_id is provided.
    """
    parent_24 = _child_24s(test_network)[_IDX_VLSM]
    grandchild_net = list(parent_24.subnets(new_prefix=28))[_IDX_GRANDCHILD_28]
    assert vlsm_subnet.subnet_id is not None
    s = open_session()
    try:
        for existing in s.list(Subnet, where=Subnet.c.subnet_name == _GRANDCHILD_NAME, limit=10):
            s.delete(existing)
        sn = s.create(
            Subnet,
            site_id=vlsm_subnet.site_id,
            parent_subnet_id=vlsm_subnet.subnet_id,
            subnet=grandchild_net,
            subnet_name=_GRANDCHILD_NAME,
        )
        s.flush()
    finally:
        s._client.close()
    return sn
