"""IpAddress creation, mutation, and frozen-field integration tests."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

import pytest
from pydantic import ValidationError

from eip_pydantic import Session
from eip_pydantic.models.address import IpAddress
from eip_pydantic.models.subnet import Subnet
from tests.integration.conftest import (
    _IDX_TERMINAL,
    _IP1_NAME,
    _IP_OFFSET,
    _MAC_INITIAL,
    _MAC_UPDATED,
    _child_24s,
    open_session,
)



# ---------------------------------------------------------------------------
# IP address creation
# ---------------------------------------------------------------------------

def test_ip_address_created_with_pk(addr1: IpAddress) -> None:
    assert addr1.ip_id is not None


def test_ip_address_hostaddr(
    session: Session,
    addr1: IpAddress,
    test_network: IPv4Network,
) -> None:
    assert addr1.ip_id is not None
    a = session.get(IpAddress, addr1.ip_id)
    base = int(_child_24s(test_network)[_IDX_TERMINAL].network_address)
    assert a.hostaddr == IPv4Address(base + _IP_OFFSET)


def test_ip_addr_property(session: Session, addr1: IpAddress) -> None:
    """ip_addr property returns the same value as hostaddr."""
    assert addr1.ip_id is not None
    a = session.get(IpAddress, addr1.ip_id)
    assert a.ip_addr == a.hostaddr


def test_ip_address_name_and_mac(session: Session, addr1: IpAddress) -> None:
    assert addr1.ip_id is not None
    a = session.get(IpAddress, addr1.ip_id)
    assert a.name == _IP1_NAME
    assert a.mac_addr is not None
    assert a.mac_addr.replace(":", "").replace("-", "").lower() == _MAC_INITIAL.replace(":", "").lower()


def test_ip_parent_subnet_link(
    session: Session,
    addr1: IpAddress,
    terminal_subnet: Subnet,
) -> None:
    """Server populates parent-subnet link from the subnet_id we submitted."""
    assert addr1.ip_id is not None
    a = session.get(IpAddress, addr1.ip_id)
    assert a.subnet_id == terminal_subnet.subnet_id


# ---------------------------------------------------------------------------
# IP address mutation
# ---------------------------------------------------------------------------

def test_ip_address_name_update(
    write_session: Session,
    addr1: IpAddress,
) -> None:
    """Mutate IP name via flush; verify the server accepted the change."""
    assert addr1.ip_id is not None
    a = write_session.get(IpAddress, addr1.ip_id)
    new_name = _IP1_NAME + "-renamed"
    a.name = new_name
    assert a.is_dirty
    write_session.flush()
    assert not a.is_dirty
    fresh = open_session()
    try:
        refetched = fresh.get(IpAddress, addr1.ip_id)
        assert refetched.name == new_name
        refetched.name = _IP1_NAME
        fresh.flush()
    finally:
        fresh._client.close()


def test_ip_address_mac_update(
    write_session: Session,
    addr1: IpAddress,
) -> None:
    """Updating mac_addr via flush persists on the server."""
    assert addr1.ip_id is not None
    a = write_session.get(IpAddress, addr1.ip_id)
    a.mac_addr = _MAC_UPDATED
    write_session.flush()
    fresh = open_session()
    try:
        refetched = fresh.get(IpAddress, addr1.ip_id)
        assert refetched.mac_addr is not None
        assert refetched.mac_addr.replace(":", "").lower() == _MAC_UPDATED.replace(":", "").lower()
        refetched.mac_addr = _MAC_INITIAL
        fresh.flush()
    finally:
        fresh._client.close()


# ---------------------------------------------------------------------------
# Frozen-field enforcement
# ---------------------------------------------------------------------------

def test_ip_hostaddr_is_frozen(addr1: IpAddress) -> None:
    with pytest.raises(ValidationError):
        addr1.hostaddr = IPv4Address("10.0.0.1")  # type: ignore[misc]
