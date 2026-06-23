"""Integration tests for DHCPv4 models: DhcpServer, DhcpScope, DhcpRange, DhcpStatic.

Requires live SolidServer credentials in a .env file:
    EIP_HOST, EIP_USERNAME, EIP_PASSWORD, EIP_VERIFY (optional)

Tests are skipped automatically when credentials are absent.

The target DHCP server is selected by name (not created or deleted by tests —
DhcpServer has no add/delete API paths in this SDK).  Any test that cannot
locate the named server is skipped automatically.

Two address spaces are used:

  CRUD test objects  (created and deleted each run, safe to destroy):
    DhcpScope   sdk-test-dhcpscope  TEST_DHCP_SCOPE_NET/MASK   (default 100.64.1.0/24)
      DhcpRange   sdk-test-dhcprange  TEST_DHCP_RANGE_START–END  (default .100–.150)
      DhcpStatic  sdk-test-dhcpstatic TEST_DHCP_STATIC_ADDR      (default .200)

  Persistent inspect objects  (created once, never deleted — visible in GUI):
    DhcpScope   sdk-inspect-dhcpscope  TEST_DHCP_INSPECT_SCOPE_NET/MASK (default 100.64.2.0/24)
      DhcpRange   sdk-inspect-dhcprange  .100–.150
      DhcpStatic  sdk-inspect-dhcpstatic .200  (mac 01:bb:cc:dd:ee:ff:01)
      DhcpStatic  sdk-inspect-dhcpstatic2 .201 (mac 01:bb:cc:dd:ee:ff:02)

MAC format: TYPE:HH:HH:HH:HH:HH:HH — 7 sections, first byte is the type (01 = Ethernet).
The server stores and returns the value verbatim in this format.

Env vars:
    TEST_DHCP_SERVER            — DHCP server name to target (default: test.dhcp)
    TEST_DHCP_SCOPE_NET         — test scope network (default: 100.64.1.0)
    TEST_DHCP_SCOPE_MASK        — test scope mask (default: 255.255.255.0)
    TEST_DHCP_RANGE_START       — test range start (default: 100.64.1.100)
    TEST_DHCP_RANGE_END         — test range end (default: 100.64.1.150)
    TEST_DHCP_STATIC_ADDR       — test static IP (default: 100.64.1.200)
    TEST_DHCP_STATIC_MAC        — test static MAC (default: 01:aa:bb:cc:dd:ee:01)
    TEST_DHCP_INSPECT_SCOPE_NET — inspect scope network (default: 100.64.2.0)
    TEST_DHCP_INSPECT_SCOPE_MASK — inspect scope mask (default: 255.255.255.0)
"""
import os
from ipaddress import IPv4Address

import pytest

from eip_pydantic import Session
from eip_pydantic.models.dhcp_range import DhcpRange
from eip_pydantic.models.dhcp_scope import DhcpScope
from eip_pydantic.models.dhcp_server import DhcpServer
from eip_pydantic.models.dhcp_static import DhcpStatic

from .conftest import _skip_if_no_creds, open_session


_DHCP_SERVER_NAME = os.getenv("TEST_DHCP_SERVER", "test.dhcp")

# ---------------------------------------------------------------------------
# CRUD test address space (created and deleted each run)
# ---------------------------------------------------------------------------

_SCOPE_NET   = IPv4Address(os.getenv("TEST_DHCP_SCOPE_NET",   "100.64.1.0"))
_SCOPE_MASK  = IPv4Address(os.getenv("TEST_DHCP_SCOPE_MASK",  "255.255.255.0"))
_RANGE_START = IPv4Address(os.getenv("TEST_DHCP_RANGE_START", "100.64.1.100"))
_RANGE_END   = IPv4Address(os.getenv("TEST_DHCP_RANGE_END",   "100.64.1.150"))
_STATIC_ADDR = IPv4Address(os.getenv("TEST_DHCP_STATIC_ADDR", "100.64.1.200"))
_STATIC_MAC_WRITE = os.getenv("TEST_DHCP_STATIC_MAC", "01:aa:bb:cc:dd:ee:01")
_STATIC_MAC_READ  = _STATIC_MAC_WRITE

_SCOPE_NAME  = "sdk-test-dhcpscope"
_RANGE_NAME  = "sdk-test-dhcprange"
_STATIC_NAME = "sdk-test-dhcpstatic"

# ---------------------------------------------------------------------------
# Persistent inspect address space (created once, never deleted)
# ---------------------------------------------------------------------------

_INSPECT_SCOPE_NET  = IPv4Address(os.getenv("TEST_DHCP_INSPECT_SCOPE_NET",  "100.64.2.0"))
_INSPECT_SCOPE_MASK = IPv4Address(os.getenv("TEST_DHCP_INSPECT_SCOPE_MASK", "255.255.255.0"))
_INSPECT_RANGE_START = IPv4Address("100.64.2.100")
_INSPECT_RANGE_END   = IPv4Address("100.64.2.150")
_INSPECT_STATIC1_ADDR = IPv4Address("100.64.2.200")
_INSPECT_STATIC1_MAC  = "01:bb:cc:dd:ee:ff:01"
_INSPECT_STATIC2_ADDR = IPv4Address("100.64.2.201")
_INSPECT_STATIC2_MAC  = "01:bb:cc:dd:ee:ff:02"

_INSPECT_SCOPE_NAME   = "sdk-inspect-dhcpscope"
_INSPECT_RANGE_NAME   = "sdk-inspect-dhcprange"
_INSPECT_STATIC1_NAME = "sdk-inspect-dhcpstatic"
_INSPECT_STATIC2_NAME = "sdk-inspect-dhcpstatic2"


def _get_test_dhcp_server(s: Session) -> DhcpServer:
    """Return the configured test DHCP server; skip if not found."""
    servers = s.list(DhcpServer, where=DhcpServer.c.dhcp_name == _DHCP_SERVER_NAME)
    if not servers:
        pytest.skip(f"DHCP server '{_DHCP_SERVER_NAME}' not found (set TEST_DHCP_SERVER)")
    return servers[0]


def _test_dhcp_id(s: Session) -> int:
    srv = _get_test_dhcp_server(s)
    assert srv.dhcp_id is not None
    return srv.dhcp_id


# ---------------------------------------------------------------------------
# Persistent inspect fixtures  (created once, never deleted)
# ---------------------------------------------------------------------------


class TestDhcpInspectFixtures:
    """Ensure a persistent set of DHCP objects exists for GUI inspection.

    These objects are created if absent but never deleted, so they survive
    across test runs and are always visible in the SolidServer GUI.
    Running this test multiple times is safe (idempotent).
    """

    def _ensure_scope(self, s: Session, dhcp_id: int) -> DhcpScope:
        existing = s.list(
            DhcpScope,
            where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_INSPECT_SCOPE_NET}'",
            limit=1,
        )
        if existing:
            return existing[0]
        scope = DhcpScope(
            dhcp_id=dhcp_id,
            dhcpscope_net_addr=_INSPECT_SCOPE_NET,
            dhcpscope_net_mask=_INSPECT_SCOPE_MASK,
            dhcpscope_name=_INSPECT_SCOPE_NAME,
        )
        s.new(scope)
        s.flush()
        return scope

    def _ensure_range(self, s: Session, scope: DhcpScope) -> DhcpRange:
        assert scope.dhcpscope_id is not None
        existing = s.list(
            DhcpRange,
            where=f"dhcpscope_id='{scope.dhcpscope_id}' and dhcprange_name='{_INSPECT_RANGE_NAME}'",
            limit=1,
        )
        if existing:
            return existing[0]
        rng = DhcpRange(
            dhcpscope_id=scope.dhcpscope_id,
            dhcprange_start_addr=_INSPECT_RANGE_START,
            dhcprange_end_addr=_INSPECT_RANGE_END,
            dhcprange_name=_INSPECT_RANGE_NAME,
        )
        s.new(rng)
        s.flush()
        return rng

    def _ensure_static(
        self,
        s: Session,
        dhcp_id: int,
        scope: DhcpScope,
        name: str,
        addr: IPv4Address,
        mac: str,
    ) -> DhcpStatic:
        assert scope.dhcpscope_id is not None
        existing = s.list(
            DhcpStatic,
            where=f"dhcpscope_id='{scope.dhcpscope_id}' and dhcphost_name='{name}'",
            limit=1,
        )
        if existing:
            return existing[0]
        st = DhcpStatic(
            dhcp_id=dhcp_id,
            dhcpscope_id=scope.dhcpscope_id,
            dhcphost_addr=addr,
            dhcphost_mac_addr=mac,
            dhcphost_name=name,
        )
        s.new(st)
        s.flush()
        return st

    def test_ensure_inspect_fixtures(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            scope = self._ensure_scope(s, dhcp_id)
            assert scope.dhcpscope_id is not None

            rng = self._ensure_range(s, scope)
            assert rng.dhcprange_id is not None

            st1 = self._ensure_static(
                s, dhcp_id, scope, _INSPECT_STATIC1_NAME, _INSPECT_STATIC1_ADDR, _INSPECT_STATIC1_MAC
            )
            st2 = self._ensure_static(
                s, dhcp_id, scope, _INSPECT_STATIC2_NAME, _INSPECT_STATIC2_ADDR, _INSPECT_STATIC2_MAC
            )
            assert st1.dhcphost_id is not None
            assert st2.dhcphost_id is not None

        # Verify everything is visible
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            scopes = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_INSPECT_SCOPE_NET}'",
            )
            assert len(scopes) == 1
            assert scopes[0].dhcpscope_id is not None

            ranges = s.list(
                DhcpRange,
                where=f"dhcpscope_id='{scopes[0].dhcpscope_id}' and dhcprange_name='{_INSPECT_RANGE_NAME}'",
            )
            assert len(ranges) == 1

            statics = s.list(
                DhcpStatic,
                where=f"dhcpscope_id='{scopes[0].dhcpscope_id}'",
            )
            assert len(statics) >= 2


# ---------------------------------------------------------------------------
# DhcpServer (read-only — no create/delete tests; server is pre-existing)
# ---------------------------------------------------------------------------


class TestDhcpServerList:
    def test_list_returns_servers(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            servers = s.list(DhcpServer, limit=5)
        assert len(servers) >= 1
        assert all(srv.dhcp_id is not None for srv in servers)
        assert all(srv.dhcp_name is not None for srv in servers)

    def test_get_configured_server(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            srv = _get_test_dhcp_server(s)
            assert srv.dhcp_id is not None
            fetched = s.get(DhcpServer, srv.dhcp_id)
        assert fetched.dhcp_name == _DHCP_SERVER_NAME

    def test_list_with_expression_builder(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            results = s.list(DhcpServer, where=DhcpServer.c.dhcp_name == _DHCP_SERVER_NAME)
        assert any(r.dhcp_name == _DHCP_SERVER_NAME for r in results)


# ---------------------------------------------------------------------------
# DhcpScope CRUD
# ---------------------------------------------------------------------------


class TestDhcpScopeCrud:
    def _cleanup(self, s: Session, dhcp_id: int) -> None:
        for sc in s.list(
            DhcpScope,
            where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            limit=5,
        ):
            s.delete(sc)

    def test_list_scopes_for_server(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            scopes = s.list(DhcpScope, where=f"dhcp_id='{dhcp_id}'", limit=5)
        assert isinstance(scopes, list)
        assert all(sc.dhcp_id == dhcp_id for sc in scopes)

    def test_list_scopes_expression_builder(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            scopes = s.list(
                DhcpScope,
                where=DhcpScope.c.dhcp_id == str(dhcp_id),
                limit=5,
            )
        assert isinstance(scopes, list)
        assert all(sc.dhcp_id == dhcp_id for sc in scopes)

    def test_create_get_update_delete_scope(self) -> None:
        _skip_if_no_creds()

        # Clean up any leftover from a previous run
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            self._cleanup(s, dhcp_id)

        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)

            # Create
            scope = DhcpScope(
                dhcp_id=dhcp_id,
                dhcpscope_net_addr=_SCOPE_NET,
                dhcpscope_net_mask=_SCOPE_MASK,
                dhcpscope_name=_SCOPE_NAME,
            )
            s.new(scope)
            s.flush()

            assert scope.dhcpscope_id is not None

            # Get (info)
            fetched = s.get(DhcpScope, scope.dhcpscope_id)
            assert fetched.dhcpscope_name == _SCOPE_NAME
            assert fetched.dhcpscope_net_addr == _SCOPE_NET
            assert fetched.dhcp_id == dhcp_id

            # Update
            fetched.dhcpscope_name = _SCOPE_NAME + "-updated"
            # flush on context manager exit

        # Verify update persisted
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            scopes = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            )
            assert len(scopes) == 1
            assert scopes[0].dhcpscope_name == _SCOPE_NAME + "-updated"

            # Delete
            s.delete(scopes[0])

        # Verify gone
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            gone = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            )
        assert len(gone) == 0


# ---------------------------------------------------------------------------
# DhcpRange CRUD
# ---------------------------------------------------------------------------


class TestDhcpRangeCrud:
    def _setup_scope(self, s: Session, dhcp_id: int) -> DhcpScope:
        """Ensure the test scope exists; return it."""
        existing = s.list(
            DhcpScope,
            where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            limit=1,
        )
        if existing:
            return existing[0]
        scope = DhcpScope(
            dhcp_id=dhcp_id,
            dhcpscope_net_addr=_SCOPE_NET,
            dhcpscope_net_mask=_SCOPE_MASK,
            dhcpscope_name=_SCOPE_NAME,
        )
        s.new(scope)
        s.flush()
        return scope

    def _teardown_scope(self, s: Session, dhcp_id: int) -> None:
        for sc in s.list(
            DhcpScope,
            where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            limit=5,
        ):
            s.delete(sc)

    def _cleanup_range(self, s: Session, scope_id: int) -> None:
        for rng in s.list(
            DhcpRange,
            where=f"dhcpscope_id='{scope_id}' and dhcprange_name='{_RANGE_NAME}'",
            limit=5,
        ):
            s.delete(rng)

    def test_list_ranges_for_server(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            ranges = s.list(DhcpRange, where=f"dhcp_id='{dhcp_id}'", limit=5)
        assert isinstance(ranges, list)

    def test_list_ranges_expression_builder(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            ranges = s.list(
                DhcpRange,
                where=DhcpRange.c.dhcp_id == str(dhcp_id),
                limit=5,
            )
        assert isinstance(ranges, list)
        assert all(r.dhcp_id == dhcp_id for r in ranges)

    def test_create_get_update_delete_range(self) -> None:
        _skip_if_no_creds()

        # Clean up leftovers
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            existing_scope = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
                limit=1,
            )
            if existing_scope:
                assert existing_scope[0].dhcpscope_id is not None
                self._cleanup_range(s, existing_scope[0].dhcpscope_id)
            self._teardown_scope(s, dhcp_id)

        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            scope = self._setup_scope(s, dhcp_id)
            assert scope.dhcpscope_id is not None

            self._cleanup_range(s, scope.dhcpscope_id)

            # Create
            rng = DhcpRange(
                dhcpscope_id=scope.dhcpscope_id,
                dhcprange_start_addr=_RANGE_START,
                dhcprange_end_addr=_RANGE_END,
                dhcprange_name=_RANGE_NAME,
            )
            s.new(rng)
            s.flush()

            assert rng.dhcprange_id is not None

            # Get (info)
            fetched = s.get(DhcpRange, rng.dhcprange_id)
            assert fetched.dhcprange_name == _RANGE_NAME
            assert fetched.dhcprange_start_addr == _RANGE_START
            assert fetched.dhcprange_end_addr == _RANGE_END
            assert fetched.dhcpscope_id == scope.dhcpscope_id

            # Update
            fetched.dhcprange_name = _RANGE_NAME + "-updated"
            # flush on context manager exit

        # Verify update persisted using expression builder
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            scopes = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
                limit=1,
            )
            assert len(scopes) == 1
            assert scopes[0].dhcpscope_id is not None
            ranges = s.list(
                DhcpRange,
                where=(
                    DhcpRange.c.dhcpscope_id == str(scopes[0].dhcpscope_id)
                ) & (
                    DhcpRange.c.dhcprange_name == _RANGE_NAME + "-updated"
                ),
            )
            assert len(ranges) == 1
            assert ranges[0].dhcprange_start_addr == _RANGE_START
            assert ranges[0].dhcprange_end_addr == _RANGE_END

            # Delete range, then scope
            s.delete(ranges[0])
            s.delete(scopes[0])

        # Verify gone
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            gone = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            )
        assert len(gone) == 0


# ---------------------------------------------------------------------------
# DhcpStatic CRUD
# ---------------------------------------------------------------------------


class TestDhcpStaticCrud:
    def _setup_scope(self, s: Session, dhcp_id: int) -> DhcpScope:
        existing = s.list(
            DhcpScope,
            where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            limit=1,
        )
        if existing:
            return existing[0]
        scope = DhcpScope(
            dhcp_id=dhcp_id,
            dhcpscope_net_addr=_SCOPE_NET,
            dhcpscope_net_mask=_SCOPE_MASK,
            dhcpscope_name=_SCOPE_NAME,
        )
        s.new(scope)
        s.flush()
        return scope

    def _teardown_scope(self, s: Session, dhcp_id: int) -> None:
        for sc in s.list(
            DhcpScope,
            where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            limit=5,
        ):
            s.delete(sc)

    def _cleanup_static(self, s: Session, scope_id: int) -> None:
        for st in s.list(
            DhcpStatic,
            where=f"dhcpscope_id='{scope_id}' and dhcphost_name='{_STATIC_NAME}'",
            limit=5,
        ):
            s.delete(st)

    def test_list_statics_for_server(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            statics = s.list(DhcpStatic, where=f"dhcp_id='{dhcp_id}'", limit=5)
        assert isinstance(statics, list)

    def test_list_statics_expression_builder(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            statics = s.list(
                DhcpStatic,
                where=DhcpStatic.c.dhcp_id == str(dhcp_id),
                limit=5,
            )
        assert isinstance(statics, list)
        assert all(st.dhcp_id == dhcp_id for st in statics)

    def test_create_get_update_delete_static(self) -> None:
        _skip_if_no_creds()

        # Clean up leftovers
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            existing_scope = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
                limit=1,
            )
            if existing_scope:
                assert existing_scope[0].dhcpscope_id is not None
                self._cleanup_static(s, existing_scope[0].dhcpscope_id)
            self._teardown_scope(s, dhcp_id)

        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            scope = self._setup_scope(s, dhcp_id)
            assert scope.dhcpscope_id is not None

            self._cleanup_static(s, scope.dhcpscope_id)

            # Create
            static = DhcpStatic(
                dhcp_id=dhcp_id,
                dhcpscope_id=scope.dhcpscope_id,
                dhcphost_addr=_STATIC_ADDR,
                dhcphost_mac_addr=_STATIC_MAC_WRITE,
                dhcphost_name=_STATIC_NAME,
            )
            s.new(static)
            s.flush()

            assert static.dhcphost_id is not None

            # Get (info)
            fetched = s.get(DhcpStatic, static.dhcphost_id)
            assert fetched.dhcphost_name == _STATIC_NAME
            assert fetched.dhcphost_addr == _STATIC_ADDR
            assert fetched.dhcphost_mac_addr == _STATIC_MAC_READ
            assert fetched.dhcpscope_id == scope.dhcpscope_id

            # Update
            fetched.dhcphost_name = _STATIC_NAME + "-updated"
            # flush on context manager exit

        # Verify update persisted using expression builder
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            scopes = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
                limit=1,
            )
            assert len(scopes) == 1
            assert scopes[0].dhcpscope_id is not None
            statics = s.list(
                DhcpStatic,
                where=(
                    DhcpStatic.c.dhcpscope_id == str(scopes[0].dhcpscope_id)
                ) & (
                    DhcpStatic.c.dhcphost_name == _STATIC_NAME + "-updated"
                ),
            )
            assert len(statics) == 1
            assert statics[0].dhcphost_addr == _STATIC_ADDR
            assert statics[0].dhcphost_mac_addr == _STATIC_MAC_READ

            # Delete static, then scope
            s.delete(statics[0])
            s.delete(scopes[0])

        # Verify gone
        with open_session() as s:
            dhcp_id = _test_dhcp_id(s)
            gone = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            )
        assert len(gone) == 0
