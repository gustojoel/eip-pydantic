"""Pool creation, mutation, and frozen-field integration tests."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

import pytest
from pydantic import ValidationError

from eip_pydantic import Session
from eip_pydantic.models.pool import Pool
from eip_pydantic.models.subnet import Subnet
from tests.integration.conftest import (
    _IDX_CHILD,
    _POOL_NAME,
    _POOL_RO_NAME,
    _POOL_RO_OFFSET_END,
    _POOL_RO_OFFSET_START,
    _child_24s,
    open_session,
)


# ---------------------------------------------------------------------------
# Pool creation
# ---------------------------------------------------------------------------

def test_pool_created_with_pk(pool: Pool) -> None:
    assert pool.pool_id is not None


def test_pool_address_range(
    session: Session,
    pool: Pool,
    test_network: IPv4Network,
) -> None:
    """Pool start/end addresses match what was requested."""
    from tests.integration.conftest import _POOL_OFFSET_START, _POOL_OFFSET_END
    assert pool.pool_id is not None
    p = session.get(Pool, pool.pool_id)
    base = int(_child_24s(test_network)[_IDX_CHILD].network_address)
    assert p.start_ip_addr == IPv4Address(base + _POOL_OFFSET_START)
    assert p.end_ip_addr == IPv4Address(base + _POOL_OFFSET_END)


def test_pool_name(session: Session, pool: Pool) -> None:
    assert pool.pool_id is not None
    p = session.get(Pool, pool.pool_id)
    assert p.pool_name == _POOL_NAME


def test_pool_parent_subnet_link(
    session: Session,
    pool: Pool,
    child_subnet: Subnet,
) -> None:
    """Server populates the parent-subnet fields from the subnet_id we submitted."""
    assert pool.pool_id is not None
    p = session.get(Pool, pool.pool_id)
    assert p.subnet_id == child_subnet.subnet_id


def test_pool_size_computed(session: Session, pool: Pool) -> None:
    """pool_size is populated by the server (or derived from start/end)."""
    assert pool.pool_id is not None
    p = session.get(Pool, pool.pool_id)
    assert p.pool_size is not None
    assert p.pool_size > 0


# ---------------------------------------------------------------------------
# Pool with read-only flag
# ---------------------------------------------------------------------------

def test_pool_read_only_flag(
    write_session: Session,
    child_subnet: Subnet,
    test_network: IPv4Network,
) -> None:
    """Create a pool with pool_read_only=True; verify the flag is set."""
    base = int(_child_24s(test_network)[_IDX_CHILD].network_address)
    start = IPv4Address(base + _POOL_RO_OFFSET_START)
    end   = IPv4Address(base + _POOL_RO_OFFSET_END)
    assert child_subnet.subnet_id is not None
    p = write_session.create(
        Pool,
        subnet_id=child_subnet.subnet_id,
        start_ip_addr=start,
        end_ip_addr=end,
        pool_name=_POOL_RO_NAME,
        pool_read_only=True,
    )
    write_session.flush()
    assert p.pool_id is not None
    fresh = open_session()
    try:
        refetched = fresh.get(Pool, p.pool_id)
        assert refetched.pool_read_only is True
    finally:
        fresh._client.close()


# ---------------------------------------------------------------------------
# Frozen-field enforcement
# ---------------------------------------------------------------------------

def test_pool_start_ip_addr_is_frozen(pool: Pool) -> None:
    with pytest.raises(ValidationError):
        pool.start_ip_addr = IPv4Address("10.0.0.1")  # type: ignore[misc]


def test_pool_end_ip_addr_is_frozen(pool: Pool) -> None:
    with pytest.raises(ValidationError):
        pool.end_ip_addr = IPv4Address("10.0.0.99")  # type: ignore[misc]


def test_pool_size_is_frozen(pool: Pool) -> None:
    with pytest.raises(ValidationError):
        pool.pool_size = 999  # type: ignore[misc]
