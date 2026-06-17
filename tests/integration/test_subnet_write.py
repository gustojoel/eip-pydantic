"""Subnet creation, mutation, and expression-builder integration tests.

Objects created here are NOT deleted at teardown — inspect them on the server
after a run.  All creates use ``new_edit`` (no add_flag on Subnet), so re-runs
against a server with existing objects succeed.

Hierarchy created under TEST_SITE_ID inside the first /16 of TEST_IP_NETWORK:

    Block /16 (subnet_level=0)                                  — pytest-block
      Child /24   (terminal, holds pools)                       — pytest-child-10
      Terminal /24 (is_terminal=True, holds IPs)                — pytest-terminal-11
      No-lock /24  (lock_network_broadcast=False)               — pytest-nolock-12
      ClassParam /24 (for class-parameter tests)                — pytest-classparam-13
      VLSM /24    (is_terminal=False, for nested-subnet tests)  — pytest-vlsm-14
        Grandchild /28 (.128–.143)  ← 3-level nesting          — pytest-grandchild-28
"""

from __future__ import annotations

from ipaddress import IPv4Network

import pytest
from pydantic import ValidationError

from eip_pydantic import Session
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet
from tests.integration.conftest import (
    _CHILD_NAME,
    _CLASSPARAM_NAME,
    _GRANDCHILD_NAME,
    _IDX_CHILD,
    _IDX_CLASSPARAM,
    _IDX_NOLOCK,
    _IDX_TERMINAL,
    _NOLOCK_NAME,
    _TERMINAL_NAME,
    _VLSM_NAME,
    _block,
    _child_24s,
    open_session,
)


# ---------------------------------------------------------------------------
# Read-only smoke tests
# ---------------------------------------------------------------------------

def test_read_test_space(session: Session, test_site_id: int) -> None:
    """Fetch the test space and verify basic fields are present."""
    space = session.get(Space, test_site_id)
    assert space.site_id == test_site_id
    assert space.site_name is not None
    assert space.row_enabled is not None


def test_subnet_count_in_space(session: Session, test_site_id: int) -> None:
    """count() should return a non-negative integer."""
    n = session.count(Subnet, where=Subnet.c.site_id == test_site_id)
    assert n >= 0


def test_find_free_subnet(session: Session, block: Subnet) -> None:
    """ip_find_free_subnet returns at least one /28 candidate inside the block."""
    candidates = session.find_free_subnet(prefix=28, subnet=block)
    assert len(candidates) >= 1
    first = candidates[0]
    assert first.start_ip_addr is not None
    assert block.subnet is not None
    assert first.start_ip_addr in block.subnet


# ---------------------------------------------------------------------------
# Block subnet (subnet_level=0)
# ---------------------------------------------------------------------------

def test_block_created_with_pk(block: Subnet) -> None:
    """Server returns a ret_oid that is stored in subnet_id after flush."""
    assert block.subnet_id is not None


def test_block_is_level_0(session: Session, block: Subnet) -> None:
    """Block created with subnet_level=0 must be reported as level 0 by the server."""
    assert block.subnet_id is not None
    sn = session.get(Subnet, block.subnet_id)
    assert sn.subnet_level == 0


def test_block_type_field(session: Session, block: Subnet) -> None:
    """Server returns type='subnet' for ALL networks (including blocks).
    Block status is determined solely by subnet_level == 0.
    """
    assert block.subnet_id is not None
    sn = session.get(Subnet, block.subnet_id)
    assert sn.type == "subnet"


def test_block_network_address(
    session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """The block's subnet matches what we requested."""
    assert block.subnet_id is not None
    sn = session.get(Subnet, block.subnet_id)
    assert sn.subnet is not None
    assert sn.subnet.network_address == _block(test_network).network_address
    assert sn.subnet.prefixlen == _block(test_network).prefixlen


# ---------------------------------------------------------------------------
# Child subnet (level 1)
# ---------------------------------------------------------------------------

def test_child_created_with_pk(child_subnet: Subnet) -> None:
    assert child_subnet.subnet_id is not None


def test_child_has_correct_parent(
    session: Session,
    child_subnet: Subnet,
    block: Subnet,
) -> None:
    """Parent-subnet linkage is set by the server from parent_subnet_id."""
    assert child_subnet.subnet_id is not None
    sn = session.get(Subnet, child_subnet.subnet_id)
    assert sn.parent_subnet_id == block.subnet_id


def test_child_type_field(session: Session, child_subnet: Subnet) -> None:
    """type is always 'subnet' on the real server; subnet_level distinguishes blocks."""
    assert child_subnet.subnet_id is not None
    sn = session.get(Subnet, child_subnet.subnet_id)
    assert sn.type == "subnet"
    assert sn.subnet_level is not None and sn.subnet_level > 0


# ---------------------------------------------------------------------------
# Grandchild subnet (level 2) — 3-level VLSM nesting
# ---------------------------------------------------------------------------

def test_grandchild_created_with_pk(grandchild_subnet: Subnet) -> None:
    """Server assigned a PK to the grandchild /28."""
    assert grandchild_subnet.subnet_id is not None


def test_grandchild_parent_is_vlsm(
    session: Session,
    grandchild_subnet: Subnet,
    vlsm_subnet: Subnet,
) -> None:
    """Grandchild's parent_subnet_id resolves to the vlsm /24.

    The grandchild lives inside vlsm_subnet (idx 14), not child_subnet (idx 10),
    because this server requires a non-terminal parent for VLSM nesting and
    child_subnet is terminal (it holds pools).
    """
    assert grandchild_subnet.subnet_id is not None
    sn = session.get(Subnet, grandchild_subnet.subnet_id)
    assert sn.parent_subnet_id == vlsm_subnet.subnet_id


def test_grandchild_subnet_level(
    session: Session,
    grandchild_subnet: Subnet,
    vlsm_subnet: Subnet,
) -> None:
    """Grandchild subnet_level is one deeper than its parent (vlsm_subnet)."""
    assert grandchild_subnet.subnet_id is not None
    assert vlsm_subnet.subnet_id is not None
    gc = session.get(Subnet, grandchild_subnet.subnet_id)
    parent = session.get(Subnet, vlsm_subnet.subnet_id)
    assert gc.subnet_level is not None
    assert parent.subnet_level is not None
    assert gc.subnet_level == parent.subnet_level + 1


def test_grandchild_is_within_parent_range(
    session: Session,
    grandchild_subnet: Subnet,
    vlsm_subnet: Subnet,
) -> None:
    """Grandchild's network address falls inside the vlsm_subnet /24."""
    assert grandchild_subnet.subnet_id is not None
    gc = session.get(Subnet, grandchild_subnet.subnet_id)
    assert gc.subnet is not None
    assert vlsm_subnet.subnet is not None
    assert gc.subnet.network_address in vlsm_subnet.subnet


def test_grandchild_inherits_site_id(
    session: Session,
    grandchild_subnet: Subnet,
    block: Subnet,
) -> None:
    """Grandchild created via parent_subnet_id only inherits the correct site_id."""
    assert grandchild_subnet.subnet_id is not None
    gc = session.get(Subnet, grandchild_subnet.subnet_id)
    assert gc.site_id == block.site_id


def test_grandchild_prefix_is_28(
    session: Session,
    grandchild_subnet: Subnet,
) -> None:
    assert grandchild_subnet.subnet_id is not None
    gc = session.get(Subnet, grandchild_subnet.subnet_id)
    assert gc.subnet is not None
    assert gc.subnet.prefixlen == 28


def test_grandchild_name(session: Session, grandchild_subnet: Subnet) -> None:
    assert grandchild_subnet.subnet_id is not None
    gc = session.get(Subnet, grandchild_subnet.subnet_id)
    assert gc.subnet_name == _GRANDCHILD_NAME


# ---------------------------------------------------------------------------
# Terminal subnet (is_terminal=True)
# ---------------------------------------------------------------------------

def test_terminal_created_with_pk(terminal_subnet: Subnet) -> None:
    assert terminal_subnet.subnet_id is not None


def test_terminal_subnet_flag(session: Session, terminal_subnet: Subnet) -> None:
    """Server should echo is_terminal=True back on a refetch."""
    assert terminal_subnet.subnet_id is not None
    sn = session.get(Subnet, terminal_subnet.subnet_id)
    assert sn.is_terminal is True


# ---------------------------------------------------------------------------
# lock_network_broadcast
# ---------------------------------------------------------------------------

def test_lock_network_broadcast_default_is_true(
    session: Session,
    child_subnet: Subnet,
) -> None:
    """PDF documents lock_network_broadcast defaults to 1 (True) when omitted."""
    assert child_subnet.subnet_id is not None
    sn = session.get(Subnet, child_subnet.subnet_id)
    assert sn.lock_network_broadcast is True


def test_lock_network_broadcast_can_be_false(
    write_session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Create a subnet with lock_network_broadcast=False; re-fetch and verify."""
    net = _child_24s(test_network)[_IDX_NOLOCK]
    assert block.subnet_id is not None
    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=net,
        subnet_name=_NOLOCK_NAME,
        lock_network_broadcast=False,
    )
    write_session.flush()
    assert sn.subnet_id is not None
    fresh = open_session()
    try:
        refetched = fresh.get(Subnet, sn.subnet_id)
        assert refetched.lock_network_broadcast is False
    finally:
        fresh._client.close()


# ---------------------------------------------------------------------------
# Frozen-field enforcement (local Python guard, no API call)
# ---------------------------------------------------------------------------

def test_subnet_field_is_frozen(block: Subnet) -> None:
    """Attempting to reassign the frozen 'subnet' field raises ValidationError."""
    with pytest.raises(ValidationError):
        block.subnet = IPv4Network("192.168.0.0/24")  # type: ignore[misc]


def test_subnet_id_is_frozen(block: Subnet) -> None:
    with pytest.raises(ValidationError):
        block.subnet_id = 9999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Subnet metadata update (dirty-tracking / flush)
# ---------------------------------------------------------------------------

def test_subnet_name_update_via_flush(
    write_session: Session,
    child_subnet: Subnet,
) -> None:
    """Mutating subnet_name and flushing issues a PUT with add_flag=edit_only."""
    assert child_subnet.subnet_id is not None
    sn = write_session.get(Subnet, child_subnet.subnet_id)
    assert not sn.is_dirty
    renamed = _CHILD_NAME + "-renamed"
    sn.subnet_name = renamed
    assert sn.is_dirty
    write_session.flush()
    assert not sn.is_dirty
    fresh = open_session()
    try:
        refetched = fresh.get(Subnet, sn.subnet_id)  # type: ignore[arg-type]
        assert refetched.subnet_name == renamed
        refetched.subnet_name = _CHILD_NAME
        fresh.flush()
    finally:
        fresh._client.close()


def test_grandchild_name_update(
    write_session: Session,
    grandchild_subnet: Subnet,
) -> None:
    """Mutating subnet_name on the grandchild propagates to the server."""
    assert grandchild_subnet.subnet_id is not None
    sn = write_session.get(Subnet, grandchild_subnet.subnet_id)
    renamed = _GRANDCHILD_NAME + "-renamed"
    sn.subnet_name = renamed
    write_session.flush()
    fresh = open_session()
    try:
        refetched = fresh.get(Subnet, grandchild_subnet.subnet_id)
        assert refetched.subnet_name == renamed
        refetched.subnet_name = _GRANDCHILD_NAME
        fresh.flush()
    finally:
        fresh._client.close()


# ---------------------------------------------------------------------------
# Class-parameter CRUD
# ---------------------------------------------------------------------------

def test_subnet_class_params_create(
    write_session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Create a subnet with a class parameter; verify via refetch."""
    net = _child_24s(test_network)[_IDX_CLASSPARAM]
    assert block.subnet_id is not None
    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=net,
        subnet_name=_CLASSPARAM_NAME,
    )
    sn.class_params["env"] = "pytest"
    write_session.flush()
    assert sn.subnet_id is not None
    fresh = open_session()
    try:
        refetched = fresh.get(Subnet, sn.subnet_id)
        assert "env" in refetched.class_params
        assert refetched.class_params["env"] == "pytest"
    finally:
        fresh._client.close()


def test_subnet_class_params_update(
    write_session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Update a class parameter on an existing subnet; verify the new value persists."""
    net = _child_24s(test_network)[_IDX_CLASSPARAM]
    assert block.subnet_id is not None
    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=net,
        subnet_name=_CLASSPARAM_NAME,
    )
    write_session.flush()
    assert sn.subnet_id is not None
    fresh = open_session()
    try:
        loaded = fresh.get(Subnet, sn.subnet_id)
        loaded.class_params["env"] = "updated"
        fresh.flush()
        ver = open_session()
        try:
            verified = ver.get(Subnet, sn.subnet_id)
            assert "env" in verified.class_params
            assert verified.class_params["env"] == "updated"
        finally:
            ver._client.close()
    finally:
        fresh._client.close()


# ---------------------------------------------------------------------------
# add_flag behaviour
# ---------------------------------------------------------------------------

def test_create_sends_no_add_flag_for_subnet(
    write_session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Subnet.build_request('create') does not inject add_flag, so the server
    defaults to new_edit.  Verify by upsert-creating a subnet that already exists."""
    net = _child_24s(test_network)[_IDX_TERMINAL]
    assert block.subnet_id is not None
    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=net,
        subnet_name=_TERMINAL_NAME,
        is_terminal=True,
    )
    write_session.flush()   # must not raise even if the subnet already exists
    assert sn.subnet_id is not None


# ---------------------------------------------------------------------------
# Expression builder — live TAGS auto-injection
# ---------------------------------------------------------------------------

def test_expression_builder_where(session: Session, block: Subnet) -> None:
    """Expression-builder WHERE clause is forwarded correctly to the server."""
    assert block.subnet_id is not None
    results = session.list(Subnet, where=Subnet.c.subnet_id == block.subnet_id)
    assert any(s.subnet_id == block.subnet_id for s in results)


def test_id_filter_where(session: Session, child_subnet: Subnet) -> None:
    """.id_filter generates a usable WHERE condition."""
    results = session.list(Subnet, where=child_subnet.id_filter)
    assert len(results) == 1
    assert results[0].subnet_id == child_subnet.subnet_id


def test_tagged_class_param_where(
    session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """When WHERE references a tagged class parameter, TAGS is auto-injected."""
    results = session.list(
        Subnet,
        where=(Subnet.c.site_id == block.site_id) & Subnet.c.subnet_name.like(f"%{_CLASSPARAM_NAME}%"),
    )
    assert isinstance(results, list)


def test_tagged_class_param_orderby(session: Session, test_site_id: int) -> None:
    """ORDER BY a tagged class parameter auto-injects the correct TAGS."""
    results = session.list(
        Subnet,
        where=Subnet.c.site_id == test_site_id,
        orderby=Subnet.c.env.asc(),
        limit=5,
    )
    assert isinstance(results, list)
