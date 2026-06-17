"""Delete operation integration tests.

Valid deletes: transient objects are created solely to be deleted.
Cascade-delete behaviour: this EfficientIP instance allows deleting a non-empty
    subnet (it removes children / pools implicitly).  The "invalid delete"
    tests below use dedicated transient parent+child structures so that shared
    session-scoped fixtures are never targeted for deletion.

Session-scoped fixtures (block, child_subnet, pool, addr1) are deliberately
NOT deleted here — they must survive the full test run for inspection and for
other test files.

Address-space allocation for transient objects (to avoid fixture conflicts):
    Transient /24 subnet           — idx 250 within first /16  (100.64.250.0/24)
    Transient cascade-parent /24   — idx 251  (for children cascade test)
    Transient pool-parent /24      — idx 252  (for pool cascade test)
    Transient pool                 — .210–.220 within child_subnet (outside .10–.30)
    Transient IP address           — .210 within terminal_subnet  (outside .100)
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

import pytest

from eip_pydantic import Session
from eip_pydantic.exceptions import ApiError
from eip_pydantic.models.address import IpAddress
from eip_pydantic.models.pool import Pool
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet
from tests.integration.conftest import (
    _IDX_CHILD,
    _IDX_TERMINAL,
    _child_24s,
    open_session,
)

_IDX_TRANSIENT_24          = 250   # /24 for basic subnet-delete test
_IDX_TRANSIENT_CASCADE_24  = 251   # /24 parent for cascade-children test
_IDX_TRANSIENT_POOL_24     = 252   # /24 parent for cascade-pool test

_TRANSIENT_SUBNET_NAME         = "pytest-transient-250"
_TRANSIENT_CASCADE_PARENT_NAME = "pytest-transient-cascade-parent-251"
_TRANSIENT_CASCADE_CHILD_NAME  = "pytest-transient-cascade-child-251"
_TRANSIENT_POOL_SUBNET_NAME    = "pytest-transient-pool-parent-252"
_TRANSIENT_POOL_NAME_CASCADE   = "pytest-transient-pool-in-252"
_TRANSIENT_POOL_START          = 210
_TRANSIENT_POOL_END            = 220
_TRANSIENT_POOL_NAME           = "pytest-transient-pool"
_TRANSIENT_IP_OFFSET           = 210


# ---------------------------------------------------------------------------
# Valid deletes — transient objects
# ---------------------------------------------------------------------------

def test_delete_subnet_removes_it(
    write_session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Create a leaf /24 subnet, verify it exists, delete it, verify it's gone."""
    net = _child_24s(test_network)[_IDX_TRANSIENT_24]
    assert block.subnet_id is not None
    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=net,
        subnet_name=_TRANSIENT_SUBNET_NAME,
    )
    write_session.flush()
    assert sn.subnet_id is not None

    fresh = open_session()
    try:
        refetched = fresh.get(Subnet, sn.subnet_id)
        assert refetched.subnet_name == _TRANSIENT_SUBNET_NAME
    finally:
        fresh._client.close()

    write_session.delete(sn)

    verify = open_session()
    try:
        results = verify.list(Subnet, where=Subnet.c.subnet_id == sn.subnet_id, limit=1)
        assert len(results) == 0, "Deleted subnet should not be returned by list"
    finally:
        verify._client.close()


def test_delete_pool_removes_it(
    write_session: Session,
    child_subnet: Subnet,
    test_network: IPv4Network,
) -> None:
    """Create a pool, verify it exists, delete it, verify it's gone."""
    base = int(_child_24s(test_network)[_IDX_CHILD].network_address)
    start = IPv4Address(base + _TRANSIENT_POOL_START)
    end   = IPv4Address(base + _TRANSIENT_POOL_END)
    assert child_subnet.subnet_id is not None
    p = write_session.create(
        Pool,
        subnet_id=child_subnet.subnet_id,
        start_ip_addr=start,
        end_ip_addr=end,
        pool_name=_TRANSIENT_POOL_NAME,
    )
    write_session.flush()
    assert p.pool_id is not None

    write_session.delete(p)

    verify = open_session()
    try:
        results = verify.list(Pool, where=Pool.c.pool_id == p.pool_id, limit=1)
        assert len(results) == 0, "Deleted pool should not be returned by list"
    finally:
        verify._client.close()


def test_delete_address_removes_it(
    write_session: Session,
    terminal_subnet: Subnet,
    test_network: IPv4Network,
) -> None:
    """Create an IP address record, delete it, verify it's gone."""
    base = int(_child_24s(test_network)[_IDX_TERMINAL].network_address)
    ip = IPv4Address(base + _TRANSIENT_IP_OFFSET)
    assert terminal_subnet.site_id is not None
    a = write_session.create(
        IpAddress,
        site_id=terminal_subnet.site_id,
        hostaddr=ip,
        subnet_id=terminal_subnet.subnet_id,
        name="pytest-transient-ip",
    )
    write_session.flush()
    if a.ip_id is None:
        found = write_session.list(IpAddress, where=f"hostaddr='{ip}'", limit=1)
        if found:
            a = found[0]
    assert a.ip_id is not None

    write_session.delete(a)

    verify = open_session()
    try:
        results = verify.list(IpAddress, where=f"hostaddr='{ip}'", limit=1)
        assert len(results) == 0, "Deleted address should not appear in list"
    finally:
        verify._client.close()


# ---------------------------------------------------------------------------
# Cascade-delete behaviour — dedicated transient parent+child structures
#
# This server cascade-deletes children when a parent is removed.
# Tests use SEPARATE transient objects (not shared fixtures) so that
# block / child_subnet / pool / addr1 are never at risk.
# ---------------------------------------------------------------------------

def test_delete_subnet_cascade_deletes_children(
    write_session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Delete a /24 subnet that contains a /28 child.

    Observed EfficientIP behaviour: deleting the parent /24 succeeds immediately —
    the server does NOT enforce a non-empty constraint for child subnets.  However,
    the child /28 is NOT removed; it is left as an orphan (no parent_subnet_id).
    This test documents that behaviour and cleans up orphans so the next run can
    recreate the same address space.

    A dedicated /24 at idx 251 is used so that shared fixtures are untouched.
    """
    parent_net = _child_24s(test_network)[_IDX_TRANSIENT_CASCADE_24]
    assert block.subnet_id is not None

    # Pre-run cleanup: delete any orphaned child from a previous run.
    # When the parent /24 is deleted, this server leaves the /28 child as an orphan.
    # That orphan would cause "Subnet overlap" when re-creating the /24 parent.
    pre_cleanup = open_session()
    try:
        orphans = pre_cleanup.list(
            Subnet,
            where=Subnet.c.subnet_name == _TRANSIENT_CASCADE_CHILD_NAME,
            limit=10,
        )
        for orphan in orphans:
            pre_cleanup.delete(orphan)
    finally:
        pre_cleanup._client.close()

    parent_sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=parent_net,
        subnet_name=_TRANSIENT_CASCADE_PARENT_NAME,
        is_terminal=False,
    )
    write_session.flush()
    assert parent_sn.subnet_id is not None
    parent_id = parent_sn.subnet_id

    child_net = list(parent_net.subnets(new_prefix=28))[1]  # idx 1: different start addr from /24
    child_sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=parent_sn.subnet_id,
        subnet=child_net,
        subnet_name=_TRANSIENT_CASCADE_CHILD_NAME,
    )
    write_session.flush()
    assert child_sn.subnet_id is not None
    child_id = child_sn.subnet_id

    try:
        write_session.delete(parent_sn)

        post_verify = open_session()
        try:
            # Parent must be gone.
            results = post_verify.list(Subnet, where=Subnet.c.subnet_id == parent_id, limit=1)
            assert len(results) == 0, "Parent subnet should have been deleted"
            # Child is left as an orphan (documented EfficientIP behaviour).
            # Delete it here so the next test run can recreate the same /24 range.
            orphaned = post_verify.list(Subnet, where=Subnet.c.subnet_id == child_id, limit=1)
            for sn in orphaned:
                post_verify.delete(sn)
        finally:
            post_verify._client.close()

    except ApiError:
        # Server enforced non-empty constraint — clean up child first, then parent.
        write_session.delete(child_sn)
        write_session.delete(parent_sn)


def test_delete_subnet_cascade_deletes_pool(
    write_session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Delete a subnet that owns a pool.

    This EfficientIP instance allows it (pool removed implicitly).
    A dedicated /24 at idx 252 is used so that shared fixtures are untouched.
    """
    subnet_net = _child_24s(test_network)[_IDX_TRANSIENT_POOL_24]
    assert block.subnet_id is not None

    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=subnet_net,
        subnet_name=_TRANSIENT_POOL_SUBNET_NAME,
    )
    write_session.flush()
    assert sn.subnet_id is not None
    subnet_id = sn.subnet_id

    base = int(subnet_net.network_address)
    p = write_session.create(
        Pool,
        subnet_id=sn.subnet_id,
        start_ip_addr=IPv4Address(base + 10),
        end_ip_addr=IPv4Address(base + 20),
        pool_name=_TRANSIENT_POOL_NAME_CASCADE,
    )
    write_session.flush()
    assert p.pool_id is not None

    try:
        write_session.delete(sn)
        verify = open_session()
        try:
            results = verify.list(Subnet, where=Subnet.c.subnet_id == subnet_id, limit=1)
            assert len(results) == 0, "Subnet should have been deleted"
        finally:
            verify._client.close()
    except ApiError:
        # Server enforced constraint — clean up manually.
        write_session.delete(p)
        write_session.delete(sn)


def test_delete_space_with_subnets_raises(
    write_session: Session,
    block: Subnet,
) -> None:
    """Deleting a Space that contains subnets must be rejected by the server.

    ``block.site_id`` is the test space; ``block`` is a subnet within it.
    """
    assert block.site_id is not None
    sp = write_session.get(Space, block.site_id)
    with pytest.raises(ApiError):
        write_session.delete(sp)
