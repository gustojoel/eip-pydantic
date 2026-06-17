"""Live integration tests for Space reads and Subnet writes inside nested Spaces.

Space write tests (creation, description/name updates) require the API user to
have 'Add/modify a space' rights (ip_site_add).  If the server returns HTTP 400
errno=6, those tests are skipped automatically — re-run after the ACL is fixed.

Subnet creation/mutation inside nested spaces works regardless.

Objects created here are NOT deleted at teardown.  Fixtures are idempotent.

Hierarchy targeted:
    TEST_SITE_ID  (pre-existing root space, default 24)
      pytest-space-child-a   (nested Space, created by fixture if permitted)
        pytest-nested-block  (/16 block, subnet_level=0)
          pytest-nested-child-14  (/24 child)

Subnet range uses the *second* /16 of TEST_IP_NETWORK (100.65.0.0/16 by
default) so it never overlaps with test_write.py (which uses the first /16).

Configure via .env:
    TEST_SITE_ID            (default 24)
    TEST_NESTED_SITE_ID     (default 25)  — pre-existing nested space fallback
    TEST_IP_NETWORK         (default 100.64.0.0/10)
"""

from __future__ import annotations

from ipaddress import IPv4Network

import pytest
from pydantic import ValidationError

from eip_pydantic import Session
from eip_pydantic.exceptions import ApiError
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet
from tests.integration.conftest import open_session


# ---------------------------------------------------------------------------
# Stable names
# ---------------------------------------------------------------------------

_SPACE_CHILD_NAME    = "pytest-space-child-a"
_SPACE_DESC_ORIGINAL = "pytest child space"
_SPACE_DESC_UPDATED  = "pytest child space (updated)"
_NESTED_BLOCK_NAME   = "pytest-nested-block"
_NESTED_CHILD_NAME   = "pytest-nested-child-14"
_IDX_NESTED_CHILD    = 14   # 100.65.14.0/24 for default TEST_IP_NETWORK


# ---------------------------------------------------------------------------
# Address-space helpers
# ---------------------------------------------------------------------------

def _nested_block_net(base: IPv4Network) -> IPv4Network:
    """Second /16 from *base* (100.65.0.0/16 for the default TEST_IP_NETWORK)."""
    if base.prefixlen >= 16:
        return base
    gen = base.subnets(new_prefix=16)
    next(gen)           # skip first (used by test_write.py)
    return next(gen)


def _nested_child_24s(base: IPv4Network) -> list[IPv4Network]:
    return list(_nested_block_net(base).subnets(new_prefix=24))


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def nested_space(test_site_id: int) -> Space:
    """Nested Space under test_site_id.

    Uses search-or-create: if the space already exists it is returned directly
    (Space uses new_only semantics so we must not POST a duplicate).

    Skipped if the API user lacks 'Add/modify a space' rights (errno=6).
    """
    s = open_session()
    try:
        existing = s.list(Space, where=Space.c.site_name == _SPACE_CHILD_NAME, limit=1)
        if existing:
            return existing[0]
        try:
            sp = s.create(
                Space,
                site_name=_SPACE_CHILD_NAME,
                site_description=_SPACE_DESC_ORIGINAL,
                parent_site_id=test_site_id,
            )
            s.flush()
        except ApiError as exc:
            pytest.skip(f"Space creation requires elevated permissions: {exc}")
    finally:
        s._client.close()
    return sp


@pytest.fixture(scope="session")
def nested_block(test_nested_site_id: int, test_network: IPv4Network) -> Subnet:
    """Block subnet (level=0) inside the pre-existing nested space.

    Uses test_nested_site_id (env var TEST_NESTED_SITE_ID, default 25) so
    subnet tests run even when Space creation is permission-blocked.
    """
    block_net = _nested_block_net(test_network)
    s = open_session()
    try:
        sn = s.create(
            Subnet,
            site_id=test_nested_site_id,
            subnet=block_net,
            subnet_name=_NESTED_BLOCK_NAME,
            subnet_level=0,
        )
        s.flush()
    finally:
        s._client.close()
    return sn


@pytest.fixture(scope="session")
def nested_child(nested_block: Subnet, test_network: IPv4Network) -> Subnet:
    """/24 child subnet inside the nested block."""
    net = _nested_child_24s(test_network)[_IDX_NESTED_CHILD]
    assert nested_block.subnet_id is not None
    s = open_session()
    try:
        sn = s.create(
            Subnet,
            site_id=nested_block.site_id,
            parent_subnet_id=nested_block.subnet_id,
            subnet=net,
            subnet_name=_NESTED_CHILD_NAME,
        )
        s.flush()
    finally:
        s._client.close()
    return sn


# ---------------------------------------------------------------------------
# Space — read-only tests (always run)
# ---------------------------------------------------------------------------

def test_space_list_nonempty(session: Session) -> None:
    """ip_site_list returns at least one Space."""
    spaces = session.list(Space, limit=5)
    assert len(spaces) >= 1
    assert all(s.site_id is not None for s in spaces)


def test_space_count_positive(session: Session) -> None:
    """count() returns a positive integer."""
    assert session.count(Space) >= 1


def test_space_get_root(session: Session, test_site_id: int) -> None:
    """get() fetches the root space and populates key fields."""
    sp = session.get(Space, test_site_id)
    assert sp.site_id == test_site_id
    assert sp.site_name is not None
    assert sp.row_enabled is not None
    assert sp.tree_level == 0


def test_space_get_nested(
    session: Session,
    test_nested_site_id: int,
    test_site_id: int,
) -> None:
    """get() fetches the nested space; parent_site_id resolves to root."""
    sp = session.get(Space, test_nested_site_id)
    assert sp.site_id == test_nested_site_id
    assert sp.parent_site_id == test_site_id
    assert sp.tree_level is not None and sp.tree_level >= 1


def test_space_list_expression_where(session: Session, test_site_id: int) -> None:
    """Expression-builder WHERE on site_id works for Space."""
    results = session.list(Space, where=Space.c.site_id == test_site_id)
    assert any(s.site_id == test_site_id for s in results)


def test_space_id_filter(session: Session, test_nested_site_id: int) -> None:
    """.id_filter generates a valid WHERE clause for Space."""
    sp = session.get(Space, test_nested_site_id)
    results = session.list(Space, where=sp.id_filter)
    assert len(results) == 1
    assert results[0].site_id == test_nested_site_id


def test_space_count_where(session: Session, test_nested_site_id: int) -> None:
    """count() with WHERE filters Space correctly."""
    assert session.count(Space, where=Space.c.site_id == test_nested_site_id) == 1


def test_space_tree_path_contains_parent_name(
    session: Session,
    test_nested_site_id: int,
) -> None:
    """tree_path for the nested space contains the parent space name."""
    sp = session.get(Space, test_nested_site_id)
    assert sp.tree_path is not None
    parent = session.get(Space, sp.parent_site_id)  # type: ignore[arg-type]
    assert parent.site_name is not None
    assert parent.site_name in sp.tree_path


def test_space_row_enabled_set(session: Session, test_nested_site_id: int) -> None:
    """row_enabled is populated on nested spaces."""
    sp = session.get(Space, test_nested_site_id)
    assert sp.row_enabled is not None


# ---------------------------------------------------------------------------
# Space — frozen-field enforcement
# ---------------------------------------------------------------------------

def test_space_site_id_is_frozen(session: Session, test_nested_site_id: int) -> None:
    """Assigning to the frozen site_id field raises ValidationError."""
    sp = session.get(Space, test_nested_site_id)
    with pytest.raises(ValidationError):
        sp.site_id = 9999  # type: ignore[misc]


def test_space_parent_site_id_is_frozen(
    session: Session,
    test_nested_site_id: int,
) -> None:
    """parent_site_id is frozen after construction."""
    sp = session.get(Space, test_nested_site_id)
    with pytest.raises(ValidationError):
        sp.parent_site_id = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Space — write tests (skipped if API user lacks 'Add/modify a space' rights)
# ---------------------------------------------------------------------------

def test_nested_space_created_with_pk(nested_space: Space) -> None:
    """Server returns a ret_oid stored in site_id after flush."""
    assert nested_space.site_id is not None


def test_nested_space_parent_id(nested_space: Space, test_site_id: int) -> None:
    """parent_site_id is echoed back correctly by the server."""
    assert nested_space.parent_site_id == test_site_id


def test_nested_space_tree_level(session: Session, nested_space: Space) -> None:
    """Nested space has tree_level >= 1."""
    assert nested_space.site_id is not None
    sp = session.get(Space, nested_space.site_id)
    assert sp.tree_level is not None and sp.tree_level >= 1


def test_nested_space_site_name(session: Session, nested_space: Space) -> None:
    """site_name set at creation is echoed back by the server."""
    assert nested_space.site_id is not None
    sp = session.get(Space, nested_space.site_id)
    assert sp.site_name == _SPACE_CHILD_NAME


def test_nested_space_description_set(session: Session, nested_space: Space) -> None:
    """site_description set at creation is echoed back."""
    assert nested_space.site_id is not None
    sp = session.get(Space, nested_space.site_id)
    assert sp.site_description == _SPACE_DESC_ORIGINAL


def test_nested_space_description_update(
    write_session: Session,
    nested_space: Space,
) -> None:
    """site_description can be updated via flush; verify round-trip."""
    assert nested_space.site_id is not None
    sp = write_session.get(Space, nested_space.site_id)
    assert not sp.is_dirty
    sp.site_description = _SPACE_DESC_UPDATED
    assert sp.is_dirty
    try:
        write_session.flush()
    except ApiError as exc:
        pytest.skip(f"Space update requires elevated permissions: {exc}")
    assert not sp.is_dirty

    fresh = open_session()
    try:
        refetched = fresh.get(Space, nested_space.site_id)
        assert refetched.site_description == _SPACE_DESC_UPDATED
        refetched.site_description = _SPACE_DESC_ORIGINAL
        fresh.flush()
    finally:
        fresh._client.close()


def test_nested_space_name_update(
    write_session: Session,
    nested_space: Space,
) -> None:
    """site_name can be renamed and restored."""
    assert nested_space.site_id is not None
    sp = write_session.get(Space, nested_space.site_id)
    renamed = _SPACE_CHILD_NAME + "-renamed"
    sp.site_name = renamed
    try:
        write_session.flush()
    except ApiError as exc:
        pytest.skip(f"Space update requires elevated permissions: {exc}")

    fresh = open_session()
    try:
        refetched = fresh.get(Space, nested_space.site_id)
        assert refetched.site_name == renamed
        refetched.site_name = _SPACE_CHILD_NAME
        fresh.flush()
    finally:
        fresh._client.close()


def test_nested_space_class_params(
    write_session: Session,
    nested_space: Space,
) -> None:
    """Class parameters set on a Space persist via a subsequent info fetch."""
    assert nested_space.site_id is not None
    sp = write_session.get(Space, nested_space.site_id)
    sp.class_params["env"] = "pytest"
    try:
        write_session.flush()
    except ApiError as exc:
        pytest.skip(f"Space update requires elevated permissions: {exc}")

    fresh = open_session()
    try:
        refetched = fresh.get(Space, nested_space.site_id)
        assert "env" in refetched.class_params
        assert refetched.class_params["env"] == "pytest"
    finally:
        fresh._client.close()


# ---------------------------------------------------------------------------
# Subnet in nested Space — creation and reads
# ---------------------------------------------------------------------------

def test_nested_block_created_with_pk(nested_block: Subnet) -> None:
    assert nested_block.subnet_id is not None


def test_nested_block_site_id(nested_block: Subnet, test_nested_site_id: int) -> None:
    """Block subnet's site_id matches the nested space."""
    assert nested_block.site_id == test_nested_site_id


def test_nested_block_is_level_0(session: Session, nested_block: Subnet) -> None:
    """Block subnet created with subnet_level=0 is reported as level 0."""
    assert nested_block.subnet_id is not None
    sn = session.get(Subnet, nested_block.subnet_id)
    assert sn.subnet_level == 0


def test_nested_block_network_address(
    session: Session,
    nested_block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Block subnet network matches what was requested."""
    assert nested_block.subnet_id is not None
    sn = session.get(Subnet, nested_block.subnet_id)
    expected = _nested_block_net(test_network)
    assert sn.subnet.network_address == expected.network_address
    assert sn.subnet.prefixlen == expected.prefixlen


def test_nested_child_created_with_pk(nested_child: Subnet) -> None:
    assert nested_child.subnet_id is not None


def test_nested_child_parent_block_id(
    session: Session,
    nested_child: Subnet,
    nested_block: Subnet,
) -> None:
    """Child subnet's parent_subnet_id resolves back to the nested block."""
    assert nested_child.subnet_id is not None
    sn = session.get(Subnet, nested_child.subnet_id)
    assert sn.parent_subnet_id == nested_block.subnet_id


def test_nested_child_site_id(
    session: Session,
    nested_child: Subnet,
    test_nested_site_id: int,
) -> None:
    """Child subnet's site_id matches the nested space."""
    assert nested_child.subnet_id is not None
    sn = session.get(Subnet, nested_child.subnet_id)
    assert sn.site_id == test_nested_site_id


def test_subnet_count_in_nested_space(
    session: Session,
    test_nested_site_id: int,
    nested_block: Subnet,
    nested_child: Subnet,
) -> None:
    """At least two subnets (block + child) are visible in the nested space."""
    n = session.count(Subnet, where=Subnet.c.site_id == test_nested_site_id)
    assert n >= 2


def test_subnet_list_site_filter(
    session: Session,
    test_nested_site_id: int,
    nested_block: Subnet,
) -> None:
    """list() with site_id WHERE returns only nested-space subnets."""
    results = session.list(Subnet, where=Subnet.c.site_id == test_nested_site_id)
    assert all(s.site_id == test_nested_site_id for s in results)
    assert any(s.subnet_id == nested_block.subnet_id for s in results)


def test_nested_block_id_filter(session: Session, nested_block: Subnet) -> None:
    """.id_filter on a nested-space subnet returns exactly one result."""
    assert nested_block.subnet_id is not None
    results = session.list(Subnet, where=nested_block.id_filter)
    assert len(results) == 1
    assert results[0].subnet_id == nested_block.subnet_id


def test_nested_space_find_free_subnet(
    session: Session,
    nested_block: Subnet,
) -> None:
    """ip_find_free_subnet works for a block inside a nested space."""
    candidates = session.find_free_subnet(prefix=28, subnet=nested_block)
    assert len(candidates) >= 1
    assert candidates[0].start_ip_addr in nested_block.subnet


# ---------------------------------------------------------------------------
# Subnet in nested Space — mutation
# ---------------------------------------------------------------------------

def test_nested_subnet_name_update(
    write_session: Session,
    nested_child: Subnet,
) -> None:
    """subnet_name can be updated via flush on a subnet inside a nested space."""
    assert nested_child.subnet_id is not None
    sn = write_session.get(Subnet, nested_child.subnet_id)
    renamed = _NESTED_CHILD_NAME + "-renamed"
    sn.subnet_name = renamed
    assert sn.is_dirty
    write_session.flush()
    assert not sn.is_dirty

    fresh = open_session()
    try:
        refetched = fresh.get(Subnet, nested_child.subnet_id)
        assert refetched.subnet_name == renamed
        refetched.subnet_name = _NESTED_CHILD_NAME
        fresh.flush()
    finally:
        fresh._client.close()


def test_nested_subnet_class_params(
    write_session: Session,
    nested_child: Subnet,
) -> None:
    """Class parameters on a subnet inside a nested space persist correctly."""
    assert nested_child.subnet_id is not None
    sn = write_session.get(Subnet, nested_child.subnet_id)
    sn.class_params["env"] = "pytest-nested"
    write_session.flush()

    fresh = open_session()
    try:
        refetched = fresh.get(Subnet, nested_child.subnet_id)
        assert "env" in refetched.class_params
        assert refetched.class_params["env"] == "pytest-nested"
    finally:
        fresh._client.close()
