"""Unit tests for DhcpScope model and dhcp_scope_* services."""
from ipaddress import IPv4Address

import httpx
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.dhcp_scope import DhcpScope



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")


_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "dhcpscope_id": "12",
    "dhcp_id": "3",
    "dhcp_name": "dhcp-primary",
    "dhcp_type": "isc",
    "dhcp_class_name": "",
    "dhcp_version": "4.4.2",
    "dhcpscope_net_addr": "192.168.10.0",
    "dhcpscope_net_mask": "255.255.255.0",
    "dhcpscope_start_ip_addr": "c0a80a01",
    "dhcpscope_end_ip_addr": "c0a80afe",
    "dhcpscope_size": "254",
    "dhcpscope_name": "office-scope",
    "dhcpscope_class_name": "",
    "dhcpscope_site_id": "0",
    "dhcpscope_site_name": "",
    "dhcpsn_id": "0",
    "dhcpsn_name": "",
    "dhcpfailover_id": "0",
    "dhcpfailover_name": "",
    "vdhcp_parent_id": "0",
    "delayed_create_time": "0",
    "delayed_delete_time": "0",
    "ip_addr": "0a541400",
    "multistatus": "",
    "dhcpscope_class_parameters": "dept=it",
    "dhcpscope_class_parameters_properties": "dept=set,propagate",
    "dhcpscope_class_parameters_inheritance_source": "",
    "row_enabled": "1",
}


def test_dhcp_scope_coerce_fields() -> None:
    sc = DhcpScope.model_validate(_LIST_ROW)
    assert sc.dhcpscope_id == 12
    assert sc.dhcp_id == 3
    assert sc.dhcpscope_net_addr == IPv4Address("192.168.10.0")
    assert sc.dhcpscope_net_mask == IPv4Address("255.255.255.0")
    assert sc.dhcpscope_start_ip_addr == IPv4Address("192.168.10.1")
    assert sc.dhcpscope_end_ip_addr == IPv4Address("192.168.10.254")
    assert sc.dhcpscope_size == 254
    assert sc.dhcpscope_name == "office-scope"
    assert sc.dhcpscope_site_id is None
    assert sc.dhcpsn_id is None
    assert sc.dhcpfailover_id is None
    assert sc.vdhcp_parent_id is None
    assert sc.ip_addr == IPv4Address("10.84.20.0")
    assert sc.row_enabled == RowEnabled.ENABLED
    assert sc.errno == 0


def test_dhcp_scope_class_params() -> None:
    sc = DhcpScope.model_validate(_LIST_ROW)
    assert sc.class_params["dept"] == "it"


def test_dhcp_scope_net_addr_frozen() -> None:
    sc = DhcpScope.model_validate(_LIST_ROW)
    import pytest
    with pytest.raises(Exception):
        sc.dhcpscope_net_addr = IPv4Address("10.0.0.0")  # type: ignore[assignment]


def test_dhcp_scope_write_params_name() -> None:
    sc = DhcpScope.model_validate(_LIST_ROW)
    sc.dhcpscope_name = "renamed-scope"
    assert sc.write_params() == {"dhcpscope_name": "renamed-scope"}


def test_dhcp_scope_write_params_row_enabled() -> None:
    sc = DhcpScope.model_validate(_LIST_ROW)
    sc.row_enabled = RowEnabled.UNMANAGED
    assert sc.write_params() == {"row_enabled": "2"}


def test_dhcp_scope_build_request_paths() -> None:
    sc = DhcpScope(
        dhcp_id=3,
        dhcpscope_net_addr=IPv4Address("192.168.10.0"),
        dhcpscope_net_mask=IPv4Address("255.255.255.0"),
    )
    sc.mark_new()
    verb, path, params = sc.build_request("create")
    assert verb == "POST"
    assert path == "rest/dhcp_scope_add"
    assert params["dhcp_id"] == "3"
    assert params["dhcpscope_net_addr"] == "192.168.10.0"
    assert params["dhcpscope_net_mask"] == "255.255.255.0"

    existing = DhcpScope.model_validate(_LIST_ROW)
    assert existing.build_request("delete") == ("DELETE", "rest/dhcp_scope_delete", {"dhcpscope_id": "12"})


def test_dhcp_scope_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert DhcpScope._coerce(sentinel) is sentinel


def test_dhcp_scope_unknown_extra_preserved() -> None:
    d = DhcpScope.model_validate({**_LIST_ROW, "custom_tag": "keep-me"})
    assert d.model_extra is not None
    assert d.model_extra["custom_tag"] == "keep-me"


@respx.mock
def test_dhcp_scope_list_and_get() -> None:
    respx.get(f"{BASE}rest/dhcp_scope_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )
    respx.get(f"{BASE}rest/dhcp_scope_info").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )

    with Session(HOST, *CREDS) as s:
        listed = s.list(DhcpScope)
        fetched = s.get(DhcpScope, 12)

    assert len(listed) == 1
    assert listed[0].dhcpscope_name == "office-scope"
    assert fetched.dhcpscope_id == 12
