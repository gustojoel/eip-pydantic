"""Integration tests for DHCPv4 models: DhcpServer, DhcpScope, DhcpRange, DhcpStatic.

Requires live SolidServer credentials in a .env file:
    EIP_HOST, EIP_USERNAME, EIP_PASSWORD, EIP_VERIFY (optional)

Tests are skipped automatically when credentials are absent.

Optional env vars for customising the test address space:
    TEST_DHCP_SERVER_ID   — pin to a specific DHCP server id (default: first available)
    TEST_DHCP_SCOPE_NET   — network address for the test scope (default: 100.64.1.0)
    TEST_DHCP_SCOPE_MASK  — netmask for the test scope (default: 255.255.255.0)
    TEST_DHCP_RANGE_START — first address of test range (default: 100.64.1.100)
    TEST_DHCP_RANGE_END   — last address of test range (default: 100.64.1.150)
    TEST_DHCP_STATIC_ADDR — IP for the static reservation (default: 100.64.1.200)
    TEST_DHCP_STATIC_MAC  — MAC for the static reservation (default: ethernet aa:bb:cc:dd:ee:01)

Object hierarchy created and destroyed per CRUD test:
    DhcpScope   sdk-test-dhcpscope  at TEST_DHCP_SCOPE_NET / MASK
      DhcpRange   sdk-test-dhcprange  TEST_DHCP_RANGE_START – TEST_DHCP_RANGE_END
      DhcpStatic  sdk-test-dhcpstatic TEST_DHCP_STATIC_ADDR  mac=TEST_DHCP_STATIC_MAC
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


_SCOPE_NET   = IPv4Address(os.getenv("TEST_DHCP_SCOPE_NET",   "100.64.1.0"))
_SCOPE_MASK  = IPv4Address(os.getenv("TEST_DHCP_SCOPE_MASK",  "255.255.255.0"))
_RANGE_START = IPv4Address(os.getenv("TEST_DHCP_RANGE_START", "100.64.1.100"))
_RANGE_END   = IPv4Address(os.getenv("TEST_DHCP_RANGE_END",   "100.64.1.150"))
_STATIC_ADDR = IPv4Address(os.getenv("TEST_DHCP_STATIC_ADDR", "100.64.1.200"))
_STATIC_MAC  = os.getenv("TEST_DHCP_STATIC_MAC", "ethernet aa:bb:cc:dd:ee:01")

_SCOPE_NAME  = "sdk-test-dhcpscope"
_RANGE_NAME  = "sdk-test-dhcprange"
_STATIC_NAME = "sdk-test-dhcpstatic"


def _first_dhcp_id(s: Session) -> int:
    """Return the id of the pinned or first available DHCP server; skip if none."""
    svr_id_env = os.getenv("TEST_DHCP_SERVER_ID", "")
    if svr_id_env:
        return int(svr_id_env)
    servers = s.list(DhcpServer, limit=1)
    if not servers:
        pytest.skip("No DHCP servers available for integration tests")
    assert servers[0].dhcp_id is not None
    return servers[0].dhcp_id


# ---------------------------------------------------------------------------
# DhcpServer (read-only)
# ---------------------------------------------------------------------------


class TestDhcpServerList:
    def test_list_returns_servers(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            servers = s.list(DhcpServer, limit=5)
        assert len(servers) >= 1
        assert all(srv.dhcp_id is not None for srv in servers)
        assert all(srv.dhcp_name is not None for srv in servers)

    def test_get_first_server(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            servers = s.list(DhcpServer, limit=1)
            assert len(servers) >= 1
            first_id = servers[0].dhcp_id
            assert first_id is not None
            srv = s.get(DhcpServer, first_id)
        assert srv.dhcp_id == first_id

    def test_list_with_expression_builder(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            servers = s.list(DhcpServer, limit=1)
            if not servers:
                pytest.skip("No DHCP servers available")
            name = servers[0].dhcp_name
            assert name is not None
            results = s.list(DhcpServer, where=DhcpServer.c.dhcp_name == name)
        assert any(r.dhcp_name == name for r in results)


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

    def test_list_scopes(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            scopes = s.list(DhcpScope, limit=5)
        assert isinstance(scopes, list)

    def test_create_get_update_delete_scope(self) -> None:
        _skip_if_no_creds()

        # Clean up any leftover from a previous run
        with open_session() as s:
            dhcp_id = _first_dhcp_id(s)
            self._cleanup(s, dhcp_id)

        with open_session() as s:
            dhcp_id = _first_dhcp_id(s)

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

            # Get
            fetched = s.get(DhcpScope, scope.dhcpscope_id)
            assert fetched.dhcpscope_name == _SCOPE_NAME
            assert fetched.dhcpscope_net_addr == _SCOPE_NET

            # Update (rename)
            fetched.dhcpscope_name = _SCOPE_NAME + "-updated"
            # flush on context manager exit

        # Verify update persisted
        with open_session() as s:
            dhcp_id = _first_dhcp_id(s)
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
            dhcp_id = _first_dhcp_id(s)
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

    def test_list_ranges(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            ranges = s.list(DhcpRange, limit=5)
        assert isinstance(ranges, list)

    def test_create_get_update_delete_range(self) -> None:
        _skip_if_no_creds()

        # Clean up leftovers
        with open_session() as s:
            dhcp_id = _first_dhcp_id(s)
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
            dhcp_id = _first_dhcp_id(s)
            scope = self._setup_scope(s, dhcp_id)
            assert scope.dhcpscope_id is not None

            # Clean any leftover range in the fresh scope
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

            # Get
            fetched = s.get(DhcpRange, rng.dhcprange_id)
            assert fetched.dhcprange_name == _RANGE_NAME
            assert fetched.dhcprange_start_addr == _RANGE_START
            assert fetched.dhcprange_end_addr == _RANGE_END

            # Update (rename)
            fetched.dhcprange_name = _RANGE_NAME + "-updated"
            # flush on context manager exit

        # Verify update persisted
        with open_session() as s:
            dhcp_id = _first_dhcp_id(s)
            scopes = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
                limit=1,
            )
            assert len(scopes) == 1
            assert scopes[0].dhcpscope_id is not None
            ranges = s.list(
                DhcpRange,
                where=f"dhcpscope_id='{scopes[0].dhcpscope_id}' and dhcprange_name='{_RANGE_NAME}-updated'",
            )
            assert len(ranges) == 1
            assert ranges[0].dhcprange_start_addr == _RANGE_START

            # Delete range, then scope
            s.delete(ranges[0])
            s.delete(scopes[0])

        # Verify gone
        with open_session() as s:
            dhcp_id = _first_dhcp_id(s)
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

    def test_list_statics(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            statics = s.list(DhcpStatic, limit=5)
        assert isinstance(statics, list)

    def test_create_get_update_delete_static(self) -> None:
        _skip_if_no_creds()

        # Clean up leftovers
        with open_session() as s:
            dhcp_id = _first_dhcp_id(s)
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
            dhcp_id = _first_dhcp_id(s)
            scope = self._setup_scope(s, dhcp_id)
            assert scope.dhcpscope_id is not None

            self._cleanup_static(s, scope.dhcpscope_id)

            # Create
            static = DhcpStatic(
                dhcp_id=dhcp_id,
                dhcpscope_id=scope.dhcpscope_id,
                dhcphost_addr=_STATIC_ADDR,
                dhcphost_mac_addr=_STATIC_MAC,
                dhcphost_name=_STATIC_NAME,
            )
            s.new(static)
            s.flush()

            assert static.dhcphost_id is not None

            # Get
            fetched = s.get(DhcpStatic, static.dhcphost_id)
            assert fetched.dhcphost_name == _STATIC_NAME
            assert fetched.dhcphost_addr == _STATIC_ADDR
            assert fetched.dhcphost_mac_addr == _STATIC_MAC

            # Update (rename)
            fetched.dhcphost_name = _STATIC_NAME + "-updated"
            # flush on context manager exit

        # Verify update persisted
        with open_session() as s:
            dhcp_id = _first_dhcp_id(s)
            scopes = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
                limit=1,
            )
            assert len(scopes) == 1
            assert scopes[0].dhcpscope_id is not None
            statics = s.list(
                DhcpStatic,
                where=f"dhcpscope_id='{scopes[0].dhcpscope_id}' and dhcphost_name='{_STATIC_NAME}-updated'",
            )
            assert len(statics) == 1
            assert statics[0].dhcphost_addr == _STATIC_ADDR

            # Delete static, then scope
            s.delete(statics[0])
            s.delete(scopes[0])

        # Verify gone
        with open_session() as s:
            dhcp_id = _first_dhcp_id(s)
            gone = s.list(
                DhcpScope,
                where=f"dhcp_id='{dhcp_id}' and dhcpscope_net_addr='{_SCOPE_NET}'",
            )
        assert len(gone) == 0
