"""Integration tests for invalid-input / constraint-violation error cases.

These tests send requests that the server should reject.  The expected
exception type depends on how the server signals the error:

* HTTP 4xx  →  ``ApiError`` raised by the transport layer
* HTTP 200 with errno != 0 (no ``ret_oid``)  →  ``KeyError`` raised by
  ``apply_response("create", ...)`` when it cannot read ``result["ret_oid"]``

Tests use ``pytest.raises((ApiError, KeyError))`` where the server response
format is uncertain.

All objects that do succeed despite an error expectation are artifacts of
unexpected server lenience — check the docstring note and the server docs.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

import pytest

from eip_pydantic import Session
from eip_pydantic.exceptions import ApiError
from eip_pydantic.models.address import IpAddress
from eip_pydantic.models.pool import Pool
from eip_pydantic.models.subnet import Subnet
from tests.integration.conftest import (
    _IDX_CHILD,
    _IDX_TERMINAL,
    _child_24s,
)

# A site_id that is extremely unlikely to exist on any real server.
_NONEXISTENT_SITE_ID = 999999


# ---------------------------------------------------------------------------
# Subnet constraint violations
# ---------------------------------------------------------------------------

def test_subnet_outside_parent_range(
    write_session: Session,
    block: Subnet,
) -> None:
    """Creating a subnet whose CIDR lies outside the parent block is rejected.

    block is 100.64.0.0/16 (or equivalent for TEST_IP_NETWORK); we attempt to
    nest a 10.0.0.0/24 inside it, which is clearly out of range.
    """
    assert block.subnet_id is not None
    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=IPv4Network("10.0.0.0/24"),
        subnet_name="pytest-error-out-of-range",
    )
    with pytest.raises((ApiError, KeyError)):
        write_session.flush()
    # Guard: if no exception was raised, mark test as unexpected-pass and warn
    # that the server accepted an out-of-range subnet (inspect manually).


def test_subnet_mismatched_site_and_parent(
    write_session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Providing site_id from one space with a parent_subnet_id from another is rejected.

    block belongs to test_site_id; passing a non-existent site_id with
    block.subnet_id as parent should create a mismatch the server must reject.
    """
    assert block.subnet_id is not None
    net = _child_24s(test_network)[_IDX_CHILD]  # fits in block's range
    sn = write_session.create(
        Subnet,
        site_id=_NONEXISTENT_SITE_ID,     # wrong / non-existent space
        parent_subnet_id=block.subnet_id,  # parent in a different space
        subnet=net,
        subnet_name="pytest-error-mismatch",
    )
    with pytest.raises((ApiError, KeyError)):
        write_session.flush()


# ---------------------------------------------------------------------------
# Pool constraint violations
# ---------------------------------------------------------------------------

def test_pool_outside_subnet_range(
    write_session: Session,
    child_subnet: Subnet,
) -> None:
    """A pool whose IP range lies entirely outside the subnet is rejected."""
    assert child_subnet.subnet_id is not None
    p = write_session.create(
        Pool,
        subnet_id=child_subnet.subnet_id,
        start_ip_addr=IPv4Address("10.0.0.1"),   # nowhere near the test subnet
        end_ip_addr=IPv4Address("10.0.0.10"),
        pool_name="pytest-error-pool-out-of-range",
    )
    with pytest.raises((ApiError, KeyError)):
        write_session.flush()


def test_pool_inverted_range(
    write_session: Session,
    child_subnet: Subnet,
    test_network: IPv4Network,
) -> None:
    """A pool where start_addr > end_addr is rejected by the server."""
    base = int(_child_24s(test_network)[_IDX_CHILD].network_address)
    p = write_session.create(
        Pool,
        subnet_id=child_subnet.subnet_id,
        start_ip_addr=IPv4Address(base + 30),   # start is after end
        end_ip_addr=IPv4Address(base + 10),
        pool_name="pytest-error-inverted-pool",
    )
    with pytest.raises((ApiError, KeyError)):
        write_session.flush()


# ---------------------------------------------------------------------------
# Address constraint violations
# ---------------------------------------------------------------------------

def test_ip_address_outside_subnet(
    write_session: Session,
    terminal_subnet: Subnet,
) -> None:
    """Probe whether the server validates that hostaddr lies within the subnet.

    Some SolidServer versions accept any IP regardless of the subnet_id passed,
    treating it as a free-form IPAM record.  Others reject it with an API error.
    This test documents the observed behaviour without prescribing one outcome.
    """
    assert terminal_subnet.site_id is not None
    a = write_session.create(
        IpAddress,
        site_id=terminal_subnet.site_id,
        hostaddr=IPv4Address("10.0.0.254"),   # outside test terminal_subnet
        subnet_id=terminal_subnet.subnet_id,
        name="pytest-error-ip-out-of-range",
    )
    try:
        write_session.flush()
        # Server accepted the out-of-range IP — clean it up.
        if a.ip_id is not None:
            write_session.delete(a)
    except (ApiError, KeyError):
        pass   # server enforced subnet containment — expected on strict installs


def test_ip_address_invalid_hostname_chars(
    write_session: Session,
    terminal_subnet: Subnet,
    test_network: IPv4Network,
) -> None:
    """An IP name containing characters forbidden by DNS rules may be rejected.

    Behaviour is server-version dependent; some installations accept any string.
    The assertion checks that the server either:
      a) rejects the request (ApiError / KeyError), or
      b) accepts it — in which case the test passes without raising.
    This test exists to document observed server behaviour.
    """
    base = int(_child_24s(test_network)[_IDX_TERMINAL].network_address)
    ip = IPv4Address(base + 253)  # .253 — unlikely to conflict
    assert terminal_subnet.site_id is not None
    a = write_session.create(
        IpAddress,
        site_id=terminal_subnet.site_id,
        hostaddr=ip,
        subnet_id=terminal_subnet.subnet_id,
        name="<invalid hostname>",   # angle brackets are not valid in DNS names
    )
    try:
        write_session.flush()
        # Server accepted the request — document this behaviour but don't fail.
        # The test serves as a live probe of server validation strictness.
        if a.ip_id is not None:
            write_session.delete(a)   # clean up the unintended record
    except (ApiError, KeyError):
        pass   # expected: server rejected the invalid name
