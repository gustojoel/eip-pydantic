"""Unit tests for DhcpStatic model and dhcp_static_* services."""
from datetime import UTC, datetime
from ipaddress import IPv4Address

import httpx
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.dhcp_static import DhcpStatic



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")


_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "dhcphost_id": "99",
    "dhcp_id": "3",
    "dhcpscope_id": "12",
    "dhcp_name": "dhcp-primary",
    "dhcp_type": "isc",
    "dhcp_class_name": "",
    "dhcp_version": "4.4.2",
    "dhcphost_addr": "192.168.10.50",
    "dhcphost_ip_addr": "c0a80a32",
    "dhcphost_mac_addr": "ethernet aa:bb:cc:dd:ee:ff",
    "dhcphost_name": "printer-01",
    "dhcphost_domain": "office.example.com",
    "dhcphost_identifier": "",
    "dhcphost_class_name": "",
    "dhcphost_last_seen": "1700000000",
    "dhcphost_expire_time": "0",
    "mac_vendor": "Acme Corp",
    "dhcpgroup_id": "0",
    "dhcpgroup_name": "",
    "dhcpscope_net_addr": "192.168.10.0",
    "dhcpscope_net_mask": "255.255.255.0",
    "dhcpscope_site_id": "0",
    "dhcpscope_site_name": "",
    "dhcpsn_id": "0",
    "dhcpsn_name": "",
    "vdhcp_parent_id": "0",
    "delayed_create_time": "0",
    "delayed_delete_time": "0",
    "ip_addr": "0a541400",
    "multistatus": "",
    "dhcphost_class_parameters": "",
    "dhcphost_class_parameters_properties": "",
    "dhcphost_class_parameters_inheritance_source": "",
    "row_enabled": "1",
}


def test_dhcp_static_coerce_fields() -> None:
    st = DhcpStatic.model_validate(_LIST_ROW)
    assert st.dhcphost_id == 99
    assert st.dhcp_id == 3
    assert st.dhcpscope_id == 12
    assert st.dhcphost_addr == IPv4Address("192.168.10.50")
    assert st.dhcphost_ip_addr == IPv4Address("192.168.10.50")
    assert st.dhcphost_mac_addr == "ethernet aa:bb:cc:dd:ee:ff"
    assert st.dhcphost_name == "printer-01"
    assert st.dhcphost_domain == "office.example.com"
    assert st.dhcphost_identifier is None
    assert st.dhcphost_last_seen == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert st.dhcphost_expire_time is not None
    assert st.dhcpgroup_id is None
    assert st.dhcpscope_site_id is None
    assert st.dhcpsn_id is None
    assert st.vdhcp_parent_id is None
    assert st.dhcpscope_net_addr == IPv4Address("192.168.10.0")
    assert st.dhcpscope_net_mask == IPv4Address("255.255.255.0")
    assert st.ip_addr == IPv4Address("10.84.20.0")
    assert st.mac_vendor == "Acme Corp"
    assert st.row_enabled == RowEnabled.ENABLED
    assert st.errno == 0


def test_dhcp_static_normalizes_a_bare_6_octet_mac_to_ethernet() -> None:
    """A plain 6-section MAC (what every other MAC field in this SDK/the real world uses) means Ethernet."""
    st = DhcpStatic(dhcphost_mac_addr="de:ad:be:ef:00:00")
    assert st.dhcphost_mac_addr == "01:de:ad:be:ef:00:00"


def test_dhcp_static_leaves_an_already_7_section_mac_unchanged() -> None:
    st = DhcpStatic(dhcphost_mac_addr="01:de:ad:be:ef:00:00")
    assert st.dhcphost_mac_addr == "01:de:ad:be:ef:00:00"


def test_dhcp_static_normalizes_a_bare_mac_on_assignment_too() -> None:
    """Regression: `_coerce()` alone (a model-level 'before' validator) never re-runs on plain attribute assignment --
    a real reconcile-update path (`existing.dhcphost_mac_addr = value`) sent an unprefixed MAC straight through and
    the server rejected it. A `@field_validator` is required for this to apply on both construction and assignment.
    """
    st = DhcpStatic(dhcphost_mac_addr="01:aa:bb:cc:dd:ee:ff")
    st.dhcphost_mac_addr = "de:ad:be:ef:00:00"
    assert st.dhcphost_mac_addr == "01:de:ad:be:ef:00:00"


def test_dhcp_static_mac_addr_null_sentinel_becomes_none() -> None:
    st = DhcpStatic.model_validate({**_LIST_ROW, "dhcphost_mac_addr": "#"})
    assert st.dhcphost_mac_addr is None


def test_dhcp_static_leaves_a_non_numeric_hardware_type_prefix_unchanged() -> None:
    """Regression: an earlier, looser 'exactly 5 colons' heuristic mangled this pre-existing fixture value."""
    st = DhcpStatic.model_validate(_LIST_ROW)
    assert st.dhcphost_mac_addr == "ethernet aa:bb:cc:dd:ee:ff"


def test_dhcp_static_write_params_name() -> None:
    st = DhcpStatic.model_validate(_LIST_ROW)
    st.dhcphost_name = "printer-renamed"
    assert st.write_params() == {"dhcphost_name": "printer-renamed"}


def test_dhcp_static_write_params_addr() -> None:
    st = DhcpStatic.model_validate(_LIST_ROW)
    st.dhcphost_addr = IPv4Address("192.168.10.51")
    assert st.write_params() == {"dhcphost_addr": "192.168.10.51"}


def test_dhcp_static_write_params_row_enabled() -> None:
    st = DhcpStatic.model_validate(_LIST_ROW)
    st.row_enabled = RowEnabled.UNMANAGED
    assert st.write_params() == {"row_enabled": "2"}


def test_dhcp_static_build_request_paths() -> None:
    st = DhcpStatic(
        dhcp_id=3,
        dhcpscope_id=12,
        dhcphost_addr=IPv4Address("192.168.10.50"),
        dhcphost_mac_addr="ethernet aa:bb:cc:dd:ee:ff",
    )
    st.mark_new()
    verb, path, params = st.build_request("create")
    assert verb == "POST"
    assert path == "rest/dhcp_static_add"
    assert params["dhcp_id"] == "3"
    assert params["dhcpscope_id"] == "12"
    assert params["dhcphost_addr"] == "192.168.10.50"
    assert params["dhcphost_mac_addr"] == "ethernet aa:bb:cc:dd:ee:ff"

    existing = DhcpStatic.model_validate(_LIST_ROW)
    assert existing.build_request("delete") == ("DELETE", "rest/dhcp_static_delete", {"dhcphost_id": "99"})


def test_dhcp_static_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert DhcpStatic._coerce(sentinel) is sentinel


def test_dhcp_static_unknown_extra_preserved() -> None:
    d = DhcpStatic.model_validate({**_LIST_ROW, "custom_tag": "keep-me"})
    assert d.model_extra is not None
    assert d.model_extra["custom_tag"] == "keep-me"


@respx.mock
def test_dhcp_static_list_and_get() -> None:
    respx.get(f"{BASE}rest/dhcp_static_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )
    respx.get(f"{BASE}rest/dhcp_static_info").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )

    with Session(HOST, *CREDS) as s:
        listed = s.list(DhcpStatic)
        fetched = s.get(DhcpStatic, 99)

    assert len(listed) == 1
    assert listed[0].dhcphost_name == "printer-01"
    assert fetched.dhcphost_id == 99
