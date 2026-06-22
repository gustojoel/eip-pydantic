"""Unit tests for DhcpServer model and dhcp_server_* services."""
from ipaddress import IPv4Address

import httpx
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.dhcp_server import DhcpServer



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")


_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "dhcp_id": "3",
    "dhcp_name": "dhcp-primary",
    "dhcp_type": "isc",
    "dhcp_state": "active",
    "dhcp_comment": "Primary DHCP server",
    "dhcp_version": "4.4.2",
    "dhcp_class_name": "",
    "dhcp_synching": "0",
    "ip_addr": "0a541400",
    "ip6_addr": "",
    "hostaddr": "10.84.20.0",
    "isolated": "0",
    "tree_level": "0",
    "total_vdhcp_members": "0",
    "vdhcp_parent_id": "0",
    "cluster_peer_dhcp_id": "0",
    "cluster_ssh_keyring_id": "0",
    "dhcp_class_parameters": "env=prod",
    "dhcp_class_parameters_properties": "env=set,propagate",
    "dhcp_class_parameters_inheritance_source": "",
    "row_enabled": "1",
}


def test_dhcp_server_coerce_fields() -> None:
    s = DhcpServer.model_validate(_LIST_ROW)
    assert s.dhcp_id == 3
    assert s.dhcp_name == "dhcp-primary"
    assert s.dhcp_synching is False
    assert s.isolated is False
    assert s.ip_addr == IPv4Address("10.84.20.0")
    assert s.tree_level == 0
    assert s.total_vdhcp_members == 0
    assert s.vdhcp_parent_id is None
    assert s.cluster_peer_dhcp_id is None
    assert s.cluster_ssh_keyring_id is None
    assert s.row_enabled == RowEnabled.ENABLED
    assert s.errno == 0


def test_dhcp_server_class_params() -> None:
    s = DhcpServer.model_validate(_LIST_ROW)
    assert s.class_params["env"] == "prod"


def test_dhcp_server_preparsed_class_params_passthrough() -> None:
    from eip_pydantic.class_params import ClassParamDict
    cp = ClassParamDict.from_blobs("env=staging", None, None, api_prefix="dhcp")
    s = DhcpServer.model_validate({**_LIST_ROW, "class_params": cp})
    assert s.class_params["env"] == "staging"


def test_dhcp_server_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert DhcpServer._coerce(sentinel) is sentinel


def test_dhcp_server_unknown_extra_preserved() -> None:
    d = DhcpServer.model_validate({**_LIST_ROW, "custom_tag": "keep-me"})
    assert d.model_extra is not None
    assert d.model_extra["custom_tag"] == "keep-me"


def test_dhcp_server_no_add_path() -> None:
    cfg = DhcpServer.solid_config
    assert "add" not in cfg.paths
    assert "delete" not in cfg.paths
    assert "list" in cfg.paths
    assert "info" in cfg.paths
    assert "count" in cfg.paths


@respx.mock
def test_dhcp_server_list_and_get() -> None:
    respx.get(f"{BASE}rest/dhcp_server_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )
    respx.get(f"{BASE}rest/dhcp_server_info").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW])
    )

    with Session(HOST, *CREDS) as s:
        listed = s.list(DhcpServer)
        fetched = s.get(DhcpServer, 3)

    assert len(listed) == 1
    assert listed[0].dhcp_name == "dhcp-primary"
    assert fetched.dhcp_id == 3
