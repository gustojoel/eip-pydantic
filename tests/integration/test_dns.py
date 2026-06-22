"""Integration tests for DNS models: DnsServer, DnsView, DnsZone, DnsRr.

These tests require live SolidServer credentials in a .env file:
    EIP_HOST, EIP_USERNAME, EIP_PASSWORD, EIP_VERIFY (optional)

They are skipped automatically when credentials are absent.

NOTE: DNS server write permissions must be enabled in SolidServer for the
create/update/delete tests to succeed.  List/get tests work read-only.

Test data created:
    - DnsView: "sdk-test-view" on the first available DNS server
    - DnsZone: "sdk-test-zone.example." (forward master) inside that view
    - DnsRr:   A record "sdk-test-rr" inside that zone
"""

import pytest

from eip_pydantic import Session
from eip_pydantic.models.dns_rr import DnsRr
from eip_pydantic.models.dns_server import DnsServer
from eip_pydantic.models.dns_view import DnsView
from eip_pydantic.models.dns_zone import DnsZone

from .conftest import open_session, _skip_if_no_creds

_VIEW_NAME = "sdk-test-view"
_ZONE_NAME = "sdk-test-zone.example."
_RR_GLUE = "sdk-test-rr"
_RR_VALUE = "192.0.2.42"


# ---------------------------------------------------------------------------
# DnsServer (read-only)
# ---------------------------------------------------------------------------


class TestDnsServerList:
    def test_list_returns_servers(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            servers = s.list(DnsServer, limit=5)
        assert len(servers) >= 1
        assert all(srv.dns_id is not None for srv in servers)
        assert all(srv.dns_name is not None for srv in servers)

    def test_get_first_server(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            servers = s.list(DnsServer, limit=1)
            assert len(servers) >= 1
            first_id = servers[0].dns_id
            assert first_id is not None
            srv = s.get(DnsServer, first_id)
        assert srv.dns_id == first_id

    def test_list_with_expression_builder(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            servers = s.list(DnsServer, limit=1)
            if not servers:
                pytest.skip("No DNS servers available")
            name = servers[0].dns_name
            assert name is not None
            results = s.list(DnsServer, where=DnsServer.c.dns_name == name)
        assert any(r.dns_name == name for r in results)


# ---------------------------------------------------------------------------
# Helper: find the first DNS server id to use as parent
# ---------------------------------------------------------------------------


def _first_dns_id(s: Session) -> int:
    servers = s.list(DnsServer, limit=1)
    if not servers:
        pytest.skip("No DNS servers available for integration tests")
    assert servers[0].dns_id is not None
    return servers[0].dns_id


# ---------------------------------------------------------------------------
# DnsView CRUD
# ---------------------------------------------------------------------------


class TestDnsViewCrud:
    def test_list_views(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            views = s.list(DnsView, limit=5)
        assert isinstance(views, list)

    def test_create_get_update_delete_view(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            dns_id = _first_dns_id(s)

            # Delete any leftover from a previous run
            existing = s.list(DnsView, where=f"dnsview_name='{_VIEW_NAME}' and dns_id='{dns_id}'")
            for v in existing:
                s.delete(v)

        with open_session() as s:
            dns_id = _first_dns_id(s)

            # Create
            view = DnsView(dns_id=dns_id, dnsview_name=_VIEW_NAME, dnsview_recursion="no")
            s.new(view)
            s.flush()

            assert view.dnsview_id is not None

            # Get
            fetched = s.get(DnsView, view.dnsview_id)
            assert fetched.dnsview_name == _VIEW_NAME

            # Update
            fetched.dnsview_allow_query = "any"
            # flush happens on context manager exit

        # Verify update
        with open_session() as s:
            dns_id = _first_dns_id(s)
            views = s.list(DnsView, where=f"dnsview_name='{_VIEW_NAME}' and dns_id='{dns_id}'")
            assert len(views) == 1
            assert views[0].dnsview_allow_query == "any"

            # Delete
            s.delete(views[0])

        # Verify deletion
        with open_session() as s:
            dns_id = _first_dns_id(s)
            gone = s.list(DnsView, where=f"dnsview_name='{_VIEW_NAME}' and dns_id='{dns_id}'")
        assert len(gone) == 0


# ---------------------------------------------------------------------------
# DnsZone CRUD
# ---------------------------------------------------------------------------


class TestDnsZoneCrud:
    def _setup_view(self, s: Session, dns_id: int) -> DnsView:
        """Ensure the test view exists; return it."""
        existing = s.list(DnsView, where=f"dnsview_name='{_VIEW_NAME}' and dns_id='{dns_id}'")
        if existing:
            return existing[0]
        view = DnsView(dns_id=dns_id, dnsview_name=_VIEW_NAME, dnsview_recursion="no")
        s.new(view)
        s.flush()
        return view

    def _teardown_view(self, s: Session, dns_id: int) -> None:
        existing = s.list(DnsView, where=f"dnsview_name='{_VIEW_NAME}' and dns_id='{dns_id}'")
        for v in existing:
            s.delete(v)

    def test_list_zones(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            zones = s.list(DnsZone, limit=5)
        assert isinstance(zones, list)

    def test_create_get_update_delete_zone(self) -> None:
        _skip_if_no_creds()

        # Clean up any leftovers
        with open_session() as s:
            dns_id = _first_dns_id(s)
            leftovers = s.list(DnsZone, where=f"dnszone_name='{_ZONE_NAME}' and dns_id='{dns_id}'")
            for z in leftovers:
                s.delete(z)
            self._teardown_view(s, dns_id)

        with open_session() as s:
            dns_id = _first_dns_id(s)
            view = self._setup_view(s, dns_id)
            assert view.dnsview_id is not None

            # Create zone
            zone = DnsZone(
                dns_id=dns_id,
                dnsview_id=view.dnsview_id,
                dnszone_name=_ZONE_NAME,
                dnszone_type="master",
            )
            s.new(zone)
            s.flush()

            assert zone.dnszone_id is not None

            # Get
            fetched = s.get(DnsZone, zone.dnszone_id)
            assert fetched.dnszone_name == _ZONE_NAME

            # Update
            fetched.dnszone_allow_query = "any"
            # flush on exit

        # Verify update
        with open_session() as s:
            dns_id = _first_dns_id(s)
            zones = s.list(DnsZone, where=f"dnszone_name='{_ZONE_NAME}' and dns_id='{dns_id}'")
            assert len(zones) == 1
            assert zones[0].dnszone_allow_query == "any"

            # Delete
            s.delete(zones[0])
            self._teardown_view(s, dns_id)

        # Verify gone
        with open_session() as s:
            dns_id = _first_dns_id(s)
            gone = s.list(DnsZone, where=f"dnszone_name='{_ZONE_NAME}' and dns_id='{dns_id}'")
        assert len(gone) == 0


# ---------------------------------------------------------------------------
# DnsRr CRUD
# ---------------------------------------------------------------------------


class TestDnsRrCrud:
    def _setup_zone(self, s: Session, dns_id: int) -> tuple[DnsZone, DnsView]:
        """Ensure the test view and zone exist; return (zone, view)."""
        view_list = s.list(DnsView, where=f"dnsview_name='{_VIEW_NAME}' and dns_id='{dns_id}'")
        if view_list:
            view = view_list[0]
        else:
            view = DnsView(dns_id=dns_id, dnsview_name=_VIEW_NAME, dnsview_recursion="no")
            s.new(view)
            s.flush()

        assert view.dnsview_id is not None
        zone_list = s.list(DnsZone, where=f"dnszone_name='{_ZONE_NAME}' and dns_id='{dns_id}'")
        if zone_list:
            return zone_list[0], view

        zone = DnsZone(
            dns_id=dns_id,
            dnsview_id=view.dnsview_id,
            dnszone_name=_ZONE_NAME,
            dnszone_type="master",
        )
        s.new(zone)
        s.flush()
        return zone, view

    def _teardown_zone_and_view(self, s: Session, dns_id: int) -> None:
        for z in s.list(DnsZone, where=f"dnszone_name='{_ZONE_NAME}' and dns_id='{dns_id}'"):
            s.delete(z)
        for v in s.list(DnsView, where=f"dnsview_name='{_VIEW_NAME}' and dns_id='{dns_id}'"):
            s.delete(v)

    def test_list_rrs(self) -> None:
        _skip_if_no_creds()
        with open_session() as s:
            rrs = s.list(DnsRr, limit=5)
        assert isinstance(rrs, list)

    def test_create_get_update_delete_rr(self) -> None:
        _skip_if_no_creds()

        # Clean up leftovers
        with open_session() as s:
            dns_id = _first_dns_id(s)
            zones = s.list(DnsZone, where=f"dnszone_name='{_ZONE_NAME}' and dns_id='{dns_id}'")
            for zone in zones:
                assert zone.dnszone_id is not None
                rrs = s.list(
                    DnsRr,
                    where=f"rr_glue='{_RR_GLUE}' and dnszone_id='{zone.dnszone_id}'",
                )
                for rr in rrs:
                    s.delete(rr)
            self._teardown_zone_and_view(s, dns_id)

        with open_session() as s:
            dns_id = _first_dns_id(s)
            zone, view = self._setup_zone(s, dns_id)
            assert zone.dnszone_id is not None
            assert view.dnsview_id is not None

            # Create RR
            rr = DnsRr(
                dns_id=dns_id,
                dnszone_id=zone.dnszone_id,
                dnsview_id=view.dnsview_id,
                rr_type="A",
                rr_glue=_RR_GLUE,
                value1=_RR_VALUE,
            )
            s.new(rr)
            s.flush()

            assert rr.rr_id is not None

            # Get
            fetched = s.get(DnsRr, rr.rr_id)
            assert fetched.value1 == _RR_VALUE

            # Update
            fetched.value1 = "192.0.2.43"
            # flush on exit

        # Verify update
        with open_session() as s:
            dns_id = _first_dns_id(s)
            zones = s.list(DnsZone, where=f"dnszone_name='{_ZONE_NAME}' and dns_id='{dns_id}'")
            assert len(zones) == 1
            assert zones[0].dnszone_id is not None
            rrs = s.list(
                DnsRr,
                where=f"rr_glue='{_RR_GLUE}' and dnszone_id='{zones[0].dnszone_id}'",
            )
            assert len(rrs) == 1
            assert rrs[0].value1 == "192.0.2.43"

            # Delete
            s.delete(rrs[0])
            self._teardown_zone_and_view(s, dns_id)

        # Verify gone
        with open_session() as s:
            dns_id = _first_dns_id(s)
            gone = s.list(DnsZone, where=f"dnszone_name='{_ZONE_NAME}' and dns_id='{dns_id}'")
        assert len(gone) == 0
