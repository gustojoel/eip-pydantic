"""Integration tests for class-parameter round-trips through the SolidServer.

Covers the full path from Python → URL-encoded wire blob → EfficientIP
SolidServer → URL-decoded wire blob → Python, across two models (Subnet and
Pool) and the following dimensions:

  - Create-time dict:       Session.create(..., class_params={...})
  - Basic mutation:         set key, flush, refetch
  - In-place overwrite:     change value, flush, refetch
  - Delete:                 del key, flush, refetch → absent
  - Partial delete:         two keys set, one deleted, other survives
  - Multi-key write:        several keys in one flush
  - Empty-string value:     key="" — documents server discard-or-preserve
  - URL-special characters: & = % + in values
  - UTF-8:                  Latin-extended (é ñ ü) and CJK (中文)

All Subnet tests target a dedicated session-scoped subnet at /24 index 15
("pytest-cp-test-15") within the first /16 of TEST_IP_NETWORK.  Pool tests
target the shared "pytest-pool-1" pool created by conftest.

Each test uses a unique class-parameter key name (e.g. "pytest_basic",
"pytest_utf8_cjk") so that tests are fully independent and accumulating keys
from previous tests do not cause false failures.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from eip_pydantic import Session
from eip_pydantic.models.pool import Pool
from eip_pydantic.models.subnet import Subnet
from tests.integration.conftest import (
    _CLASSPARAM_NAME,
    _IDX_CLASSPARAM,
    _child_24s,
    open_session,
)



if TYPE_CHECKING:
    from collections.abc import Generator
    from ipaddress import IPv4Network

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CP_IDX  = 15
_CP_NAME = "pytest-cp-test-15"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def cp_subnet(block: Subnet, test_network: IPv4Network) -> Subnet:
    """Fresh /24 subnet at index 15, dedicated to class-parameter tests.

    Follows the same delete-then-create pattern as conftest fixtures so that
    every run exercises both the delete and create paths.
    """
    net = _child_24s(test_network)[_CP_IDX]
    assert block.subnet_id is not None
    s = open_session()
    try:
        for existing in s.list(Subnet, where=Subnet.c.subnet_name == _CP_NAME, limit=10):
            s.delete(existing)
        sn = s.create(
            Subnet,
            site_id=block.site_id,
            parent_subnet_id=block.subnet_id,
            subnet=net,
            subnet_name=_CP_NAME,
        )
        s.flush()
    finally:
        s._client.close()
    return sn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _fresh() -> Generator[Session, None, None]:
    """Short-lived Session for read-back verification; always closed on exit."""
    s = open_session()
    try:
        yield s
    finally:
        s._client.close()


# ===========================================================================
# Subnet — create-time class_params via plain dict
# ===========================================================================

def test_subnet_create_with_class_params_dict(
    write_session: Session,
    block: Subnet,
    test_network: IPv4Network,
) -> None:
    """Session.create() with class_params={} sends class parameters to the server.

    Regression: before the _coerce_class_params fix, plain dicts were silently
    discarded (stringified then overwritten by an empty ClassParamDict).
    """
    net = _child_24s(test_network)[_IDX_CLASSPARAM]
    assert block.subnet_id is not None
    sn = write_session.create(
        Subnet,
        site_id=block.site_id,
        parent_subnet_id=block.subnet_id,
        subnet=net,
        subnet_name=_CLASSPARAM_NAME,
        class_params={"cp_env": "pytest-create", "cp_owner": "test-suite"},
    )
    write_session.flush()
    assert sn.subnet_id is not None

    with _fresh() as s:
        fetched = s.get(Subnet, sn.subnet_id)
    assert fetched.class_params["cp_env"] == "pytest-create"
    assert fetched.class_params["cp_owner"] == "test-suite"


# ===========================================================================
# Subnet — mutation round-trips
# ===========================================================================

def test_class_params_basic_round_trip(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """Set a class param, flush, refetch in a new session — value persists."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_basic"] = "hello"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_basic"] == "hello"


def test_class_params_update_overwrites_value(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """Overwriting an existing key with a new value propagates to the server."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_update"] = "v1"
    write_session.flush()

    with _fresh() as s:
        loaded = s.get(Subnet, cp_subnet.subnet_id)
        loaded.class_params["pytest_update"] = "v2"
        s.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_update"] == "v2"


def test_class_params_delete_removes_key(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """Staging a deletion via ``del class_params[k]``; after flush the key is absent."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_del"] = "temporary"
    write_session.flush()

    with _fresh() as s:
        loaded = s.get(Subnet, cp_subnet.subnet_id)
        assert "pytest_del" in loaded.class_params
        del loaded.class_params["pytest_del"]
        s.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert "pytest_del" not in fetched.class_params


def test_class_params_partial_delete_leaves_survivors(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """Deleting one key does not disturb sibling keys on the same object."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_keep"] = "survivor"
    sn.class_params["pytest_gone"] = "deleted"
    write_session.flush()

    with _fresh() as s:
        loaded = s.get(Subnet, cp_subnet.subnet_id)
        del loaded.class_params["pytest_gone"]
        s.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_keep"] == "survivor"
    assert "pytest_gone" not in fetched.class_params


def test_class_params_multi_key_all_persist(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """Several keys written in a single flush all survive the round-trip."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_mk_a"] = "alpha"
    sn.class_params["pytest_mk_b"] = "beta"
    sn.class_params["pytest_mk_c"] = "gamma"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_mk_a"] == "alpha"
    assert fetched.class_params["pytest_mk_b"] == "beta"
    assert fetched.class_params["pytest_mk_c"] == "gamma"


# ===========================================================================
# Subnet — empty string vs absence
# ===========================================================================

def test_class_params_empty_string_value(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """An empty-string value is sent to the server as key= in the wire blob.

    SolidServer may store it (returned as "") or silently discard it (key absent
    after refetch).  Both outcomes are valid server behaviour; this test
    documents which one the live server exhibits without asserting a specific
    value — it only asserts that the value is not somehow corrupted to a
    non-empty string.
    """
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_empty"] = ""
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    if "pytest_empty" in fetched.class_params:
        # Server preserved the key: value must still be empty string.
        assert fetched.class_params["pytest_empty"] == ""
    # Key absent → server silently discarded the empty value (also valid).


# ===========================================================================
# Subnet — URL-special characters in values
# ===========================================================================

def test_class_params_value_with_equals(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """'=' inside a value does not corrupt the key=value wire encoding."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_eq"] = "a=b"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_eq"] == "a=b"


def test_class_params_value_with_ampersand(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """'&' inside a value does not split into a spurious second key."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_amp"] = "a&b"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_amp"] == "a&b"


def test_class_params_value_with_percent(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """'%' is percent-encoded (% → %25) without double-decoding on the way back."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_pct"] = "50%off"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_pct"] == "50%off"


def test_class_params_value_with_plus(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """'+' in a value is encoded as %2B so the server does not decode it as a space."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_plus"] = "rock+roll"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_plus"] == "rock+roll"


# ===========================================================================
# Subnet — UTF-8 values
# ===========================================================================

def test_class_params_utf8_latin_extended(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """Latin-extended characters (é, ñ, ü) survive the URL-encoding round-trip."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_utf8_lat"] = "café résumé naïve"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_utf8_lat"] == "café résumé naïve"


def test_class_params_utf8_cjk(
    write_session: Session,
    cp_subnet: Subnet,
) -> None:
    """CJK characters survive the URL-encoding round-trip."""
    assert cp_subnet.subnet_id is not None
    sn = write_session.get(Subnet, cp_subnet.subnet_id)
    sn.class_params["pytest_utf8_cjk"] = "中文"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Subnet, cp_subnet.subnet_id)
    assert fetched.class_params["pytest_utf8_cjk"] == "中文"


# ===========================================================================
# Pool — class_params (second model, different class_param_prefix)
# ===========================================================================

def test_pool_class_params_basic_round_trip(
    write_session: Session,
    pool: Pool,
) -> None:
    """Set a class param on a Pool, flush, refetch — value persists.

    Pool uses class_param_prefix="pool" so this exercises a different
    wire field name (pool_class_parameters) from the Subnet tests.
    """
    assert pool.pool_id is not None
    p = write_session.get(Pool, pool.pool_id)
    p.class_params["pytest_pool_basic"] = "pool-value"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Pool, pool.pool_id)
    assert fetched.class_params["pytest_pool_basic"] == "pool-value"


def test_pool_class_params_update_and_delete(
    write_session: Session,
    pool: Pool,
) -> None:
    """Pool class params can be updated and deleted via successive flushes."""
    assert pool.pool_id is not None
    p = write_session.get(Pool, pool.pool_id)
    p.class_params["pytest_pool_ud"] = "original"
    write_session.flush()

    with _fresh() as s:
        loaded = s.get(Pool, pool.pool_id)
        loaded.class_params["pytest_pool_ud"] = "changed"
        s.flush()

    with _fresh() as s:
        mid = s.get(Pool, pool.pool_id)
    assert mid.class_params["pytest_pool_ud"] == "changed"

    with _fresh() as s:
        loaded2 = s.get(Pool, pool.pool_id)
        del loaded2.class_params["pytest_pool_ud"]
        s.flush()

    with _fresh() as s:
        final = s.get(Pool, pool.pool_id)
    assert "pytest_pool_ud" not in final.class_params


def test_pool_class_params_utf8(
    write_session: Session,
    pool: Pool,
) -> None:
    """UTF-8 class param values survive round-trip on Pool as they do on Subnet."""
    assert pool.pool_id is not None
    p = write_session.get(Pool, pool.pool_id)
    p.class_params["pytest_pool_utf8"] = "café"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Pool, pool.pool_id)
    assert fetched.class_params["pytest_pool_utf8"] == "café"


def test_pool_class_params_url_special_chars(
    write_session: Session,
    pool: Pool,
) -> None:
    """URL-special characters in Pool class param values survive encoding."""
    assert pool.pool_id is not None
    p = write_session.get(Pool, pool.pool_id)
    p.class_params["pytest_pool_eq"]  = "a=b"
    p.class_params["pytest_pool_amp"] = "x&y"
    p.class_params["pytest_pool_pct"] = "100%"
    write_session.flush()

    with _fresh() as s:
        fetched = s.get(Pool, pool.pool_id)
    assert fetched.class_params["pytest_pool_eq"]  == "a=b"
    assert fetched.class_params["pytest_pool_amp"] == "x&y"
    assert fetched.class_params["pytest_pool_pct"] == "100%"
