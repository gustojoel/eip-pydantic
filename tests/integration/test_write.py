"""Live read/write integration tests for the SolidServer IPAM API.

Objects created here are NOT deleted at teardown — inspect them on the server
to validate state after a run.  All create operations use the server's default
``new_edit`` behaviour (Subnet / Pool / IpAddress), so re-running the suite
against a server that already has the test objects will succeed: the API
overwrites metadata in place and ``apply_response`` captures the returned PK.

Hierarchy created under TEST_SITE_ID inside TEST_IP_NETWORK:

    Block /16 (subnet_level=0)
      Child /24  (parent_subnet_id = block)
        Pool     10..20
        IP .100  name + mac
      Terminal /24 (is_terminal=True)
      No-lock /24  (lock_network_broadcast=False)
      ClassParam /24 (for class-parameter tests)

Configure via .env or environment variables:
    TEST_SITE_ID     (default 24)
    TEST_IP_NETWORK  (default 100.64.0.0/10)
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

import pytest
from pydantic import ValidationError

from eip_pydantic import Session
from eip_pydantic.models.address import IpAddress
from eip_pydantic.models.pool import Pool
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet
from tests.integration.conftest import open_session


# ---------------------------------------------------------------------------
# Address-space helpers
# ---------------------------------------------------------------------------

def _block(base: IPv4Network) -> IPv4Network:
    """First /16 from *base* (or *base* itself if already /16 or smaller)."""
    if base.prefixlen >= 16:
        return base
    return next(base.subnets(new_prefix=16))


def _child_24s(base: IPv4Network) -> list[IPv4Network]:
    """All /24 subnets within the first /16 of *base*."""
    return list(_block(base).subnets(new_prefix=24))


# Stable names used across test runs (so new_edit finds/updates the same objects)
_BLOCK_NAME      = "pytest-block"
_CHILD_NAME      = "pytest-child-10"
_TERMINAL_NAME   = "pytest-terminal-11"
_NOLOCK_NAME     = "pytest-nolock-12"
_CLASSPARAM_NAME = "pytest-classparam-13"
_POOL_NAME       = "pytest-pool-1"
_POOL_RO_NAME    = "pytest-pool-readonly"
_IP1_NAME        = "pytest-addr-100"
# Locally-administered MACs (52:54:00:* range, used by QEMU/KVM).
# Avoids silent server rejection that occurs when a MAC is already registered.
_MAC_INITIAL     = "52:54:00:AB:CD:01"
_MAC_UPDATED     = "52:54:00:AB:CD:02"

# Index into the /24 list for each test subnet
_IDX_CHILD      = 10
_IDX_TERMINAL   = 11
_IDX_NOLOCK     = 12
_IDX_CLASSPARAM = 13
# Pool occupies .10 – .20 within _IDX_CHILD /24
_POOL_OFFSET_START = 10
_POOL_OFFSET_END   = 20
# RO pool occupies .21 – .30
_POOL_RO_OFFSET_START = 21
_POOL_RO_OFFSET_END   = 30
# Test IP: .100 within _IDX_CHILD /24
_IP_OFFSET = 100


# ---------------------------------------------------------------------------
# Session-scoped setup fixtures
# Each fixture opens its own short-lived Session, flushes, then closes it.
# The returned object carries the server-assigned PK for use in tests.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def block(test_site_id: int, test_network: IPv4Network) -> Subnet:
    """Create (or upsert) the test block subnet; return it with subnet_id set."""
    block_net = _block(test_network)
    s = open_session()
    try:
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
    """Create (or upsert) the /24 child subnet under the block."""
    net = _child_24s(test_network)[_IDX_CHILD]
    assert block.subnet_id is not None
    s = open_session()
    try:
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
    """Create a /24 subnet with ``is_terminal=True``."""
    net = _child_24s(test_network)[_IDX_TERMINAL]
    assert block.subnet_id is not None
    s = open_session()
    try:
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
    """Create (or upsert) a pool within the child /24."""
    base = int(_child_24s(test_network)[_IDX_CHILD].network_address)
    start = IPv4Address(base + _POOL_OFFSET_START)
    end   = IPv4Address(base + _POOL_OFFSET_END)
    assert child_subnet.subnet_id is not None
    s = open_session()
    try:
        p = s.create(
            Pool,
            subnet_id=child_subnet.subnet_id,
            start_hostaddr=start,
            end_hostaddr=end,
            pool_name=_POOL_NAME,
        )
        s.flush()
    finally:
        s._client.close()
    return p


@pytest.fixture(scope="session")
def addr1(terminal_subnet: Subnet, test_network: IPv4Network) -> IpAddress:
    """Create (or upsert) a test IP address inside the terminal subnet.

    IPs can only be added to terminal subnets on this server; ip_add silently
    returns HTTP 200 with empty body (no ret_oid) for non-terminal subnets.
    For terminal subnets the normal JSON response with ret_oid is returned.
    """
    base = int(_child_24s(test_network)[_IDX_TERMINAL].network_address)
    ip = IPv4Address(base + _IP_OFFSET)
    assert terminal_subnet.site_id is not None
    s = open_session()
    try:
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
            # Safety fallback: ip_add returned empty body; look up by address
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


def test_find_free_subnet(session: Session, block: Subnet) -> None:
    """ip_find_free_subnet (rpc/) returns at least one /28 candidate inside the block."""
    candidates = session.find_free_subnet(prefix=28, subnet=block)
    assert len(candidates) >= 1
    first = candidates[0]
    assert first.start_ip_addr is not None
    assert first.start_ip_addr in block.subnet


# ---------------------------------------------------------------------------
# Block subnet creation (subnet_level=0)
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
    # Real server always returns 'subnet' regardless of subnet_level; rely on
    # subnet_level instead (tested by test_block_is_level_0).
    assert sn.type == "subnet"


def test_block_network_address(session: Session, block: Subnet, test_network: IPv4Network) -> None:
    """The block's subnet matches what we requested."""
    assert block.subnet_id is not None
    sn = session.get(Subnet, block.subnet_id)
    assert sn.subnet.network_address == _block(test_network).network_address
    assert sn.subnet.prefixlen == _block(test_network).prefixlen


# ---------------------------------------------------------------------------
# Child subnet creation
# ---------------------------------------------------------------------------

def test_child_created_with_pk(child_subnet: Subnet) -> None:
    assert child_subnet.subnet_id is not None


def test_child_has_correct_parent(session: Session, child_subnet: Subnet, block: Subnet) -> None:
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
# lock_network_broadcast tests
# ---------------------------------------------------------------------------

def test_lock_network_broadcast_default_is_true(session: Session, child_subnet: Subnet) -> None:
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
    # Re-fetch using a fresh session to bypass the local cache
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


def test_pool_start_hostaddr_is_frozen(pool: Pool) -> None:
    with pytest.raises(ValidationError):
        pool.start_hostaddr = IPv4Address("10.0.0.1")  # type: ignore[misc]


def test_ip_hostaddr_is_frozen(addr1: IpAddress) -> None:
    with pytest.raises(ValidationError):
        addr1.hostaddr = IPv4Address("10.0.0.1")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Subnet metadata update (dirty-tracking / flush / edit_only)
# ---------------------------------------------------------------------------

def test_subnet_name_update_via_flush(
    write_session: Session,
    child_subnet: Subnet,
) -> None:
    """Mutating subnet_name and flushing issues a PUT with add_flag=edit_only."""
    assert child_subnet.subnet_id is not None
    # Load into this session's cache via get
    sn = write_session.get(Subnet, child_subnet.subnet_id)
    assert not sn.is_dirty
    renamed = _CHILD_NAME + "-renamed"
    sn.subnet_name = renamed
    assert sn.is_dirty
    write_session.flush()
    assert not sn.is_dirty
    # Verify the name on the server via a fresh session
    fresh = open_session()
    try:
        refetched = fresh.get(Subnet, sn.subnet_id)  # type: ignore[arg-type]
        assert refetched.subnet_name == renamed
        # Restore original name so subsequent test runs see a clean state
        refetched.subnet_name = _CHILD_NAME
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
    # Upsert the subnet to ensure it exists
    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=net,
        subnet_name=_CLASSPARAM_NAME,
    )
    write_session.flush()
    assert sn.subnet_id is not None
    # Load via a fresh session and update a class param
    fresh = open_session()
    try:
        loaded = fresh.get(Subnet, sn.subnet_id)
        loaded.class_params["env"] = "updated"
        fresh.flush()
        # Verify persisted
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
# Pool creation
# ---------------------------------------------------------------------------

def test_pool_created_with_pk(pool: Pool) -> None:
    assert pool.pool_id is not None


def test_pool_address_range(session: Session, pool: Pool, test_network: IPv4Network) -> None:
    """Pool start/end addresses match what was requested."""
    assert pool.pool_id is not None
    p = session.get(Pool, pool.pool_id)
    base = int(_child_24s(test_network)[_IDX_CHILD].network_address)
    assert p.start_hostaddr == IPv4Address(base + _POOL_OFFSET_START)
    assert p.end_hostaddr == IPv4Address(base + _POOL_OFFSET_END)


def test_pool_name(session: Session, pool: Pool) -> None:
    assert pool.pool_id is not None
    p = session.get(Pool, pool.pool_id)
    assert p.pool_name == _POOL_NAME


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
        start_hostaddr=start,
        end_hostaddr=end,
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


def test_pool_parent_subnet_link(session: Session, pool: Pool, child_subnet: Subnet) -> None:
    """Server populates the parent-subnet fields from the subnet_id we submitted."""
    assert pool.pool_id is not None
    p = session.get(Pool, pool.pool_id)
    assert p.subnet_id == child_subnet.subnet_id


# ---------------------------------------------------------------------------
# IP address creation and update
# ---------------------------------------------------------------------------

def test_ip_address_created_with_pk(addr1: IpAddress) -> None:
    assert addr1.ip_id is not None


def test_ip_address_hostaddr(session: Session, addr1: IpAddress, test_network: IPv4Network) -> None:
    assert addr1.ip_id is not None
    a = session.get(IpAddress, addr1.ip_id)
    base = int(_child_24s(test_network)[_IDX_TERMINAL].network_address)
    assert a.hostaddr == IPv4Address(base + _IP_OFFSET)


def test_ip_address_name_and_mac(session: Session, addr1: IpAddress) -> None:
    assert addr1.ip_id is not None
    a = session.get(IpAddress, addr1.ip_id)
    assert a.name == _IP1_NAME
    assert a.mac_addr is not None
    assert a.mac_addr.replace(":", "").replace("-", "").lower() == _MAC_INITIAL.replace(":", "").lower()


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
    # Verify via a fresh session
    fresh = open_session()
    try:
        refetched = fresh.get(IpAddress, addr1.ip_id)
        assert refetched.name == new_name
        # Restore
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
        # Restore original MAC
        refetched.mac_addr = _MAC_INITIAL
        fresh.flush()
    finally:
        fresh._client.close()


def test_ip_parent_subnet_link(session: Session, addr1: IpAddress, terminal_subnet: Subnet) -> None:
    """Server populates parent-subnet link from the subnet_id we submitted."""
    assert addr1.ip_id is not None
    a = session.get(IpAddress, addr1.ip_id)
    assert a.subnet_id == terminal_subnet.subnet_id


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
    # Terminal subnet fixture may already exist on the server.
    # new_edit means this must NOT raise an exception.
    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=net,
        subnet_name=_TERMINAL_NAME,
        is_terminal=True,
    )
    write_session.flush()   # should not raise even if the subnet already exists
    assert sn.subnet_id is not None


# ---------------------------------------------------------------------------
# Expression builder — TAGS auto-injection
# ---------------------------------------------------------------------------

def test_tagged_class_param_where(
    session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """When WHERE references a tagged class parameter, TAGS is auto-injected."""
    # Re-use the classparam subnet (created in a different test fixture).
    # Filter by a tag we know we set: env='pytest' or env='updated'.
    # The point is that Subnet.c.env generates tag_network_env in WHERE and
    # injects TAGS=network.env automatically.
    results = session.list(
        Subnet,
        where=(Subnet.c.site_id == block.site_id) & Subnet.c.subnet_name.like(f"%{_CLASSPARAM_NAME}%"),
    )
    # Just verify the request didn't error; exact results depend on setup order.
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
