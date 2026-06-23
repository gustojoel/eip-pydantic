"""Unit tests for DhcpFailoverChannel model and dhcp_failover_* services."""
from ipaddress import IPv4Address

import httpx
import respx

from eip_pydantic import Session
from eip_pydantic.models.dhcp_failover import DhcpFailoverChannel



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")


_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "dhcpfailover_id": "7",
    "dhcp_id": "3",
    "dhcp_name": "dhcp-primary",
    "dhcp_type": "ipm",
    "dhcp_state": "active",
    "vdhcp_parent_id": "0",
    "cluster_role": "M",
    "dhcpfailover_name": "fo-channel-1",
    "dhcpfailover_addr": "10.0.0.1",
    "dhcpfailover_port": "647",
    "peer_dhcp_id": "4",
    "dhcpfailover_peer_addr": "10.0.0.2",
    "dhcpfailover_peer_port": "647",
    "dhcpfailover_split": "128",
    "dhcpfailover_state": "normal",
    "dhcpfailover_type": "primary",
    "dhcpfailover_auto_partner_down": "0",
    "dhcpfailover_mclt": "3600",
    "delayed_create_time": "0",
    "delayed_delete_time": "0",
    "ip_addr": "0a000001",
    "ip6_addr": "",
    "hostaddr": "10.0.0.1",
    "multistatus": "",
}


def test_coerce_integer_fields() -> None:
    ch = DhcpFailoverChannel.model_validate(_LIST_ROW)
    assert ch.dhcpfailover_id == 7
    assert ch.dhcp_id == 3
    assert ch.dhcpfailover_port == 647
    assert ch.dhcpfailover_peer_port == 647
    assert ch.dhcpfailover_auto_partner_down == 0
    assert ch.dhcpfailover_mclt == 3600
    assert ch.delayed_create_time == 0
    assert ch.delayed_delete_time == 0
    assert ch.errno == 0


def test_coerce_nz_int_fields() -> None:
    ch = DhcpFailoverChannel.model_validate(_LIST_ROW)
    # vdhcp_parent_id "0" → None
    assert ch.vdhcp_parent_id is None
    # peer_dhcp_id "4" → 4
    assert ch.peer_dhcp_id == 4


def test_coerce_nz_int_peer_dhcp_id_zero() -> None:
    row = {**_LIST_ROW, "peer_dhcp_id": "0"}
    ch = DhcpFailoverChannel.model_validate(row)
    assert ch.peer_dhcp_id is None


def test_coerce_ip_addresses() -> None:
    ch = DhcpFailoverChannel.model_validate(_LIST_ROW)
    assert ch.ip_addr == IPv4Address("10.0.0.1")
    assert ch.dhcpfailover_addr == IPv4Address("10.0.0.1")
    assert ch.dhcpfailover_peer_addr == IPv4Address("10.0.0.2")


def test_coerce_string_fields() -> None:
    ch = DhcpFailoverChannel.model_validate(_LIST_ROW)
    assert ch.dhcpfailover_name == "fo-channel-1"
    assert ch.dhcpfailover_state == "normal"
    assert ch.dhcpfailover_type == "primary"
    assert ch.cluster_role == "M"
    assert ch.dhcp_name == "dhcp-primary"


def test_empty_string_fields_become_none() -> None:
    row = {**_LIST_ROW, "ip6_addr": "", "multistatus": ""}
    ch = DhcpFailoverChannel.model_validate(row)
    assert ch.ip6_addr is None
    assert ch.multistatus is None


def test_non_dict_passthrough() -> None:
    sentinel = object()
    assert DhcpFailoverChannel._coerce(sentinel) is sentinel


def test_unknown_extra_preserved() -> None:
    ch = DhcpFailoverChannel.model_validate({**_LIST_ROW, "custom_tag": "keep-me"})
    assert ch.model_extra is not None
    assert ch.model_extra["custom_tag"] == "keep-me"


def test_no_add_or_delete_path() -> None:
    cfg = DhcpFailoverChannel.solid_config
    assert "add" not in cfg.paths
    assert "delete" not in cfg.paths
    assert "list" in cfg.paths
    assert "info" in cfg.paths
    assert "count" in cfg.paths


def test_dhcpfailover_id_is_frozen() -> None:
    import pytest
    from pydantic import ValidationError
    ch = DhcpFailoverChannel.model_validate(_LIST_ROW)
    with pytest.raises(ValidationError):
        ch.dhcpfailover_id = 999


def test_ip_addr_is_frozen() -> None:
    import pytest
    from pydantic import ValidationError
    ch = DhcpFailoverChannel.model_validate(_LIST_ROW)
    with pytest.raises(ValidationError):
        ch.ip_addr = IPv4Address("1.2.3.4")


@respx.mock
def test_list_and_get() -> None:
    respx.get(f"{BASE}rest/dhcp_failover_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )
    respx.get(f"{BASE}rest/dhcp_failover_info").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )

    with Session(HOST, *CREDS) as s:
        listed = s.list(DhcpFailoverChannel)
        fetched = s.get(DhcpFailoverChannel, 7)

    assert len(listed) == 1
    assert listed[0].dhcpfailover_name == "fo-channel-1"
    assert fetched.dhcpfailover_id == 7


@respx.mock
def test_list_with_where_expression() -> None:
    respx.get(f"{BASE}rest/dhcp_failover_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )

    with Session(HOST, *CREDS) as s:
        results = s.list(
            DhcpFailoverChannel,
            where=DhcpFailoverChannel.c.dhcp_id == 3,
        )

    assert len(results) == 1
    assert results[0].dhcp_id == 3


@respx.mock
def test_in_model_exports() -> None:
    from eip_pydantic.models import DhcpFailoverChannel as Imported
    assert Imported is DhcpFailoverChannel
