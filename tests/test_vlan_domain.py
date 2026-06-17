"""Unit tests for VlanDomain model and vlmdomain_* services."""

import httpx
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.vlan_domain import VlanDomain



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")


_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "vlmdomain_id": "5",
    "vlmdomain_name": "dc-vlan-domain",
    "vlmdomain_description": "Datacenter VLANs",
    "vlmdomain_start_vlan_id": "100",
    "vlmdomain_end_vlan_id": "3999",
    "support_vxlan": "1",
    "vlmdomain_class_name": "net/vlan-domain",
    "vlmdomain_class_parameters": "tenant=core",
    "vlmdomain_class_parameters_properties": "tenant=set,propagate",
    "vlmdomain_class_parameters_inheritance_source": "tenant=real_vlmdomain,5",
    "row_enabled": "1",
}


def test_vlan_domain_coerce_fields() -> None:
    d = VlanDomain.model_validate(_LIST_ROW)
    assert d.vlmdomain_id == 5
    assert d.vlmdomain_start_vlan_id == 100
    assert d.vlmdomain_end_vlan_id == 3999
    assert d.support_vxlan is True
    assert d.row_enabled == RowEnabled.ENABLED


def test_vlan_domain_class_params() -> None:
    d = VlanDomain.model_validate(_LIST_ROW)
    assert d.class_params["tenant"] == "core"
    assert d.class_params.source("tenant") == ("real_vlmdomain", "5")


def test_vlan_domain_write_params_description() -> None:
    d = VlanDomain.model_validate(_LIST_ROW)
    d.vlmdomain_description = "Updated"
    assert d.write_params() == {"vlmdomain_description": "Updated"}


def test_vlan_domain_build_request_paths() -> None:
    d = VlanDomain(
        vlmdomain_name="lab",
        vlmdomain_start_vlan_id=100,
        vlmdomain_end_vlan_id=200,
    )
    d.mark_new()
    create = d.build_request("create")

    existing = VlanDomain.model_validate(_LIST_ROW)
    delete = existing.build_request("delete")

    assert create[0] == "POST"
    assert create[1] == "rest/vlm_domain_add"
    assert delete[0] == "DELETE"
    assert delete[1] == "rest/vlm_domain_delete"


def test_vlan_domain_create_support_vxlan() -> None:
    d = VlanDomain(
        vlmdomain_name="vxlan-domain",
        vlmdomain_start_vlan_id=1,
        vlmdomain_end_vlan_id=4094,
        support_vxlan=True,
    )
    d.mark_new()
    _, _, params = d.build_request("create")
    assert params["support_vxlan"] == "1"
    assert params["vlmdomain_name"] == "vxlan-domain"


def test_vlan_domain_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert VlanDomain._coerce(sentinel) is sentinel


def test_vlan_domain_unknown_extra_is_preserved() -> None:
    d = VlanDomain.model_validate({**_LIST_ROW, "custom_marker": "keep-me"})
    assert d.model_extra is not None
    assert d.model_extra["custom_marker"] == "keep-me"


@respx.mock
def test_vlan_domain_list_and_get() -> None:
    respx.get(f"{BASE}rest/vlmdomain_list").mock(return_value=httpx.Response(200, json=[_LIST_ROW]))
    respx.get(f"{BASE}rest/vlmdomain_info").mock(return_value=httpx.Response(200, json=[_LIST_ROW]))

    with Session(HOST, *CREDS) as s:
        listed = s.list(VlanDomain)
        fetched = s.get(VlanDomain, 5)

    assert len(listed) == 1
    assert listed[0].vlmdomain_name == "dc-vlan-domain"
    assert fetched.vlmdomain_id == 5
