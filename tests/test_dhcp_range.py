"""Unit tests for DhcpRange model and dhcp_range_* services."""
from ipaddress import IPv4Address

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.dhcp_range import DhcpRange



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")


_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "dhcprange_id": "42",
    "dhcpscope_id": "12",
    "dhcp_id": "3",
    "dhcp_name": "dhcp-primary",
    "dhcp_type": "isc",
    "dhcp_class_name": "",
    "dhcp_version": "4.4.2",
    "dhcprange_start_addr": "192.168.10.100",
    "dhcprange_end_addr": "192.168.10.200",
    "dhcprange_start_ip_addr": "c0a80a64",
    "dhcprange_end_ip_addr": "c0a80ac8",
    "dhcprange_size": "101",
    "dhcprange_name": "192.168.10.100-192.168.10.200",
    "dhcprange_class_name": "",
    "dhcprange_acl": "",
    "dhcprange_lease_count": "15",
    "dhcprange_lease_percent": "14.85",
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
    "dhcprange_class_parameters": "",
    "dhcprange_class_parameters_properties": "",
    "dhcprange_class_parameters_inheritance_source": "",
    "row_enabled": "1",
}


def test_dhcp_range_coerce_fields() -> None:
    r = DhcpRange.model_validate(_LIST_ROW)
    assert r.dhcprange_id == 42
    assert r.dhcpscope_id == 12
    assert r.dhcp_id == 3
    assert r.dhcprange_start_addr == IPv4Address("192.168.10.100")
    assert r.dhcprange_end_addr == IPv4Address("192.168.10.200")
    assert r.dhcprange_start_ip_addr == IPv4Address("192.168.10.100")
    assert r.dhcprange_end_ip_addr == IPv4Address("192.168.10.200")
    assert r.dhcprange_size == 101
    assert r.dhcprange_lease_count == 15
    assert r.dhcprange_lease_percent == pytest.approx(14.85)
    assert r.dhcpscope_net_addr == IPv4Address("192.168.10.0")
    assert r.dhcpscope_net_mask == IPv4Address("255.255.255.0")
    assert r.dhcpscope_site_id is None
    assert r.dhcpsn_id is None
    assert r.vdhcp_parent_id is None
    assert r.ip_addr == IPv4Address("10.84.20.0")
    assert r.row_enabled == RowEnabled.ENABLED
    assert r.errno == 0


def test_dhcp_range_write_params_name() -> None:
    r = DhcpRange.model_validate(_LIST_ROW)
    r.dhcprange_name = "new-name"
    assert r.write_params() == {"dhcprange_name": "new-name"}


def test_dhcp_range_write_params_addr() -> None:
    r = DhcpRange.model_validate(_LIST_ROW)
    r.dhcprange_end_addr = IPv4Address("192.168.10.150")
    assert r.write_params() == {"dhcprange_end_addr": "192.168.10.150"}


def test_dhcp_range_write_params_row_enabled() -> None:
    r = DhcpRange.model_validate(_LIST_ROW)
    r.row_enabled = RowEnabled.UNMANAGED
    assert r.write_params() == {"row_enabled": "2"}


def test_dhcp_range_build_request_paths() -> None:
    r = DhcpRange(
        dhcpscope_id=12,
        dhcprange_start_addr=IPv4Address("192.168.10.100"),
        dhcprange_end_addr=IPv4Address("192.168.10.200"),
    )
    r.mark_new()
    verb, path, params = r.build_request("create")
    assert verb == "POST"
    assert path == "rest/dhcp_range_add"
    assert params["dhcpscope_id"] == "12"
    assert params["dhcprange_start_addr"] == "192.168.10.100"
    assert params["dhcprange_end_addr"] == "192.168.10.200"

    existing = DhcpRange.model_validate(_LIST_ROW)
    assert existing.build_request("delete") == ("DELETE", "rest/dhcp_range_delete", {"dhcprange_id": "42"})


def test_dhcp_range_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert DhcpRange._coerce(sentinel) is sentinel


def test_dhcp_range_unknown_extra_preserved() -> None:
    d = DhcpRange.model_validate({**_LIST_ROW, "custom_tag": "keep-me"})
    assert d.model_extra is not None
    assert d.model_extra["custom_tag"] == "keep-me"


@respx.mock
def test_dhcp_range_list_and_get() -> None:
    respx.get(f"{BASE}rest/dhcp_range_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )
    respx.get(f"{BASE}rest/dhcp_range_info").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )

    with Session(HOST, *CREDS) as s:
        listed = s.list(DhcpRange)
        fetched = s.get(DhcpRange, 42)

    assert len(listed) == 1
    assert listed[0].dhcprange_name == "192.168.10.100-192.168.10.200"
    assert fetched.dhcprange_id == 42
