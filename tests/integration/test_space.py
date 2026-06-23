"""Live integration tests for Space reads and Subnet writes inside nested Spaces.

All nested Spaces are created under TEST_SITE_ID.  Each session-scoped Space
fixture tears down any previous instance (recursively deleting child spaces and
their subnets) before creating a fresh one, so every run exercises the full
delete → create cycle.

Hierarchy targeted:
    TEST_SITE_ID  (pre-existing root space, default 24)
      pytest-space-child-a    (nested Space, depth 1)
        pytest-space-deep-b   (nested Space, depth 2)
          pytest-space-deeper-c  (nested Space, depth 3)
        pytest-nested-block   (/16 block, subnet_level=0)
          pytest-nested-child-14  (/24 child)

Subnet range uses the *second* /16 of TEST_IP_NETWORK (100.65.0.0/16 by
default) so it never overlaps with test_write.py (which uses the first /16).

Configure via .env:
    TEST_SITE_ID     (default 24)
    TEST_IP_NETWORK  (default 100.64.0.0/10)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from eip_pydantic import Session
from eip_pydantic.exceptions import ApiError
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet
from tests.integration.conftest import open_session



if TYPE_CHECKING:
    from ipaddress import IPv4Network



_SKIP_SPACE_WRITE = "Space write operations require 'ip_site_add' permission (not yet granted)"


# ---------------------------------------------------------------------------
# Stable names
# ---------------------------------------------------------------------------

_SPACE_CHILD_NAME    = "pytest-space-child-a"
_SPACE_DEEP_NAME     = "pytest-space-deep-b"      # grandchild of root (depth 2)
_SPACE_DEEPER_NAME   = "pytest-space-deeper-c"    # great-grandchild of root (depth 3)
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
# Space teardown helpers
# ---------------------------------------------------------------------------

def _delete_space_by_name(s: Session, site_name: str) -> None:
    """Find a space by name, delete its subnets, then delete it.

    Does nothing if no space with that name exists.  Does NOT recurse into
    child spaces — callers must delete descendants by name (deepest first)
    before calling this on an ancestor, because the server rejects deletion of
    a Space that still has child spaces (errno 5066).

    Filtering child spaces by parent_site_id via ip_site_list WHERE is not
    reliable on all SolidServer versions, so we avoid that approach.
    """
    spaces = s.list(Space, where=Space.c.site_name == site_name, limit=1)
    if not spaces:
        return
    sp = spaces[0]
    assert sp.site_id is not None
    for sn in s.list(Subnet, where=Subnet.c.site_id == sp.site_id, limit=1000):
        s.delete(sn)
    s.delete(sp)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def nested_space(test_site_id: int) -> Space:
    """Depth-1 Space under test_site_id.

    Skipped if the API user lacks 'ip_site_add' permission.  Descendants are
    deleted deepest-first before this space is deleted and re-created, because
    the server rejects deletion of a non-empty parent Space (errno 5066).
    """
    s = open_session()
    try:
        try:
            _delete_space_by_name(s, _SPACE_DEEPER_NAME)
            _delete_space_by_name(s, _SPACE_DEEP_NAME)
            _delete_space_by_name(s, _SPACE_CHILD_NAME)
            sp = s.create(
                Space,
                site_name=_SPACE_CHILD_NAME,
                site_description=_SPACE_DESC_ORIGINAL,
                parent_site_id=test_site_id,
            )
            s.flush()
        except ApiError as exc:
            pytest.skip(f"{_SKIP_SPACE_WRITE}: {exc}")
    finally:
        s._client.close()
    return sp


@pytest.fixture(scope="session")
def deep_space(nested_space: Space) -> Space:
    """Depth-2 Space nested under ``nested_space``.

    ``nested_space``'s fixture already deleted this as part of its teardown,
    but we re-check for safety on partial runs.
    """
    s = open_session()
    try:
        try:
            _delete_space_by_name(s, _SPACE_DEEPER_NAME)
            _delete_space_by_name(s, _SPACE_DEEP_NAME)
            sp = s.create(
                Space,
                site_name=_SPACE_DEEP_NAME,
                parent_site_id=nested_space.site_id,
            )
            s.flush()
        except ApiError as exc:
            pytest.skip(f"{_SKIP_SPACE_WRITE}: {exc}")
    finally:
        s._client.close()
    return sp


@pytest.fixture(scope="session")
def deeper_space(deep_space: Space) -> Space:
    """Depth-3 Space nested under ``deep_space``."""
    s = open_session()
    try:
        try:
            _delete_space_by_name(s, _SPACE_DEEPER_NAME)
            sp = s.create(
                Space,
                site_name=_SPACE_DEEPER_NAME,
                parent_site_id=deep_space.site_id,
            )
            s.flush()
        except ApiError as exc:
            pytest.skip(f"{_SKIP_SPACE_WRITE}: {exc}")
    finally:
        s._client.close()
    return sp


@pytest.fixture(scope="session")
def nested_block(nested_space: Space, test_network: IPv4Network) -> Subnet:
    """Block subnet (level=0) inside ``nested_space``.

    Any leftover from a prior run is deleted before a fresh copy is created.
    """
    block_net = _nested_block_net(test_network)
    s = open_session()
    try:
        for existing in s.list(Subnet, where=Subnet.c.subnet_name == _NESTED_BLOCK_NAME, limit=10):
            s.delete(existing)
        assert nested_space.site_id is not None
        sn = s.create(
            Subnet,
            site_id=nested_space.site_id,
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
    """/24 child subnet inside the nested block.

    Any leftover from a prior run is deleted before a fresh copy is created.
    """
    net = _nested_child_24s(test_network)[_IDX_NESTED_CHILD]
    assert nested_block.subnet_id is not None
    s = open_session()
    try:
        for existing in s.list(Subnet, where=Subnet.c.subnet_name == _NESTED_CHILD_NAME, limit=10):
            s.delete(existing)
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
    nested_space: Space,
    test_site_id: int,
) -> None:
    """get() fetches the nested space; parent_site_id resolves to root."""
    assert nested_space.site_id is not None
    sp = session.get(Space, nested_space.site_id)
    assert sp.site_id == nested_space.site_id
    assert sp.parent_site_id == test_site_id
    assert sp.tree_level is not None
    assert sp.tree_level >= 1


def test_space_list_expression_where(session: Session, test_site_id: int) -> None:
    """Expression-builder WHERE on site_id works for Space."""
    results = session.list(Space, where=Space.c.site_id == test_site_id)
    assert any(s.site_id == test_site_id for s in results)


def test_space_id_filter(session: Session, nested_space: Space) -> None:
    """.id_filter generates a valid WHERE clause for Space."""
    assert nested_space.site_id is not None
    sp = session.get(Space, nested_space.site_id)
    results = session.list(Space, where=sp.id_filter)
    assert len(results) == 1
    assert results[0].site_id == nested_space.site_id


def test_space_count_where(session: Session, nested_space: Space) -> None:
    """count() with WHERE filters Space correctly."""
    assert nested_space.site_id is not None
    assert session.count(Space, where=Space.c.site_id == nested_space.site_id) == 1


def test_space_tree_path_contains_parent_name(
    session: Session,
    nested_space: Space,
) -> None:
    """tree_path for the nested space contains the parent space name."""
    assert nested_space.site_id is not None
    sp = session.get(Space, nested_space.site_id)
    assert sp.tree_path is not None
    parent = session.get(Space, sp.parent_site_id)  # type: ignore[arg-type]
    assert parent.site_name is not None
    assert parent.site_name in sp.tree_path


def test_space_row_enabled_set(session: Session, nested_space: Space) -> None:
    """row_enabled is populated on nested spaces."""
    assert nested_space.site_id is not None
    sp = session.get(Space, nested_space.site_id)
    assert sp.row_enabled is not None


# ---------------------------------------------------------------------------
# Space — frozen-field enforcement
# ---------------------------------------------------------------------------

def test_space_site_id_is_frozen(session: Session, nested_space: Space) -> None:
    """Assigning to the frozen site_id field raises ValidationError."""
    assert nested_space.site_id is not None
    sp = session.get(Space, nested_space.site_id)
    with pytest.raises(ValidationError):
        sp.site_id = 9999


def test_space_parent_site_id_is_frozen(
    session: Session,
    nested_space: Space,
) -> None:
    """parent_site_id is frozen after construction."""
    assert nested_space.site_id is not None
    sp = session.get(Space, nested_space.site_id)
    with pytest.raises(ValidationError):
        sp.parent_site_id = 1


# ---------------------------------------------------------------------------
# Space — write tests
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
    assert sp.tree_level is not None
    assert sp.tree_level >= 1


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
    write_session.flush()
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
    write_session.flush()

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
    write_session.flush()

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


def test_nested_block_site_id(nested_block: Subnet, nested_space: Space) -> None:
    """Block subnet's site_id matches the nested space."""
    assert nested_block.site_id == nested_space.site_id


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
    assert sn.subnet is not None
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
    nested_space: Space,
) -> None:
    """Child subnet's site_id matches the nested space."""
    assert nested_child.subnet_id is not None
    sn = session.get(Subnet, nested_child.subnet_id)
    assert sn.site_id == nested_space.site_id


def test_subnet_count_in_nested_space(
    session: Session,
    nested_space: Space,
    nested_block: Subnet,
    nested_child: Subnet,
) -> None:
    """At least two subnets (block + child) are visible in the nested space."""
    assert nested_space.site_id is not None
    n = session.count(Subnet, where=Subnet.c.site_id == nested_space.site_id)
    assert n >= 2


def test_subnet_list_site_filter(
    session: Session,
    nested_space: Space,
    nested_block: Subnet,
) -> None:
    """list() with site_id WHERE returns only nested-space subnets."""
    assert nested_space.site_id is not None
    results = session.list(Subnet, where=Subnet.c.site_id == nested_space.site_id)
    assert all(s.site_id == nested_space.site_id for s in results)
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
    assert nested_block.subnet is not None
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


# ---------------------------------------------------------------------------
# Deeply nested Spaces (3+ levels: root → child-a → deep-b → deeper-c)
# ---------------------------------------------------------------------------

def test_deep_space_created_with_pk(deep_space: Space) -> None:
    """Server returns a ret_oid stored in site_id for the depth-2 space."""
    assert deep_space.site_id is not None


def test_deep_space_parent_is_nested(deep_space: Space, nested_space: Space) -> None:
    """deep_space.parent_site_id resolves to nested_space."""
    assert deep_space.parent_site_id == nested_space.site_id


def test_deep_space_tree_level(session: Session, deep_space: Space) -> None:
    """Depth-2 space has tree_level >= 2."""
    assert deep_space.site_id is not None
    sp = session.get(Space, deep_space.site_id)
    assert sp.tree_level is not None
    assert sp.tree_level >= 2


def test_deep_space_site_name(session: Session, deep_space: Space) -> None:
    assert deep_space.site_id is not None
    sp = session.get(Space, deep_space.site_id)
    assert sp.site_name == _SPACE_DEEP_NAME


def test_deep_space_tree_path_contains_parent_names(
    session: Session,
    deep_space: Space,
    nested_space: Space,
) -> None:
    """tree_path of the depth-2 space contains both parent space names."""
    assert deep_space.site_id is not None
    sp = session.get(Space, deep_space.site_id)
    assert sp.tree_path is not None
    assert nested_space.site_name is not None
    assert nested_space.site_name in sp.tree_path


def test_deeper_space_created_with_pk(deeper_space: Space) -> None:
    """Server returns a ret_oid stored in site_id for the depth-3 space."""
    assert deeper_space.site_id is not None


def test_deeper_space_parent_is_deep(deeper_space: Space, deep_space: Space) -> None:
    """deeper_space.parent_site_id resolves to deep_space."""
    assert deeper_space.parent_site_id == deep_space.site_id


def test_deeper_space_tree_level(session: Session, deeper_space: Space) -> None:
    """Depth-3 space has tree_level >= 3."""
    assert deeper_space.site_id is not None
    sp = session.get(Space, deeper_space.site_id)
    assert sp.tree_level is not None
    assert sp.tree_level >= 3


def test_deeper_space_site_name(session: Session, deeper_space: Space) -> None:
    assert deeper_space.site_id is not None
    sp = session.get(Space, deeper_space.site_id)
    assert sp.site_name == _SPACE_DEEPER_NAME


def test_deeper_space_tree_path_contains_all_ancestors(
    session: Session,
    deeper_space: Space,
    deep_space: Space,
    nested_space: Space,
) -> None:
    """tree_path of the depth-3 space contains names of all ancestor spaces."""
    assert deeper_space.site_id is not None
    sp = session.get(Space, deeper_space.site_id)
    assert sp.tree_path is not None
    assert nested_space.site_name is not None
    assert nested_space.site_name in sp.tree_path
    assert deep_space.site_name is not None
    assert deep_space.site_name in sp.tree_path


def test_deeper_space_id_filter(session: Session, deeper_space: Space) -> None:
    """.id_filter on the depth-3 space returns exactly one result."""
    assert deeper_space.site_id is not None
    results = session.list(Space, where=deeper_space.id_filter)
    assert len(results) == 1
    assert results[0].site_id == deeper_space.site_id
