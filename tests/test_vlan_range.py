"""Unit tests for VlanRange model and vlmrange_* services."""

import httpx
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.vlan_range import VlanRange



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "vlmrange_id": "3",
    "vlmrange_name": "prod-range",
    "vlmrange_description": "Production VLANs",
    "vlmrange_start_vlan_id": "100",
    "vlmrange_end_vlan_id": "999",
    "vlmrange_disable_overlapping": "1",
    "vlmrange_class_name": "net/range",
    "vlmrange_class_parameters": "env=prod",
    "vlmrange_class_parameters_properties": "env=set,propagate",
    "vlmrange_class_parameters_inheritance_source": "env=real_vlmrange,3",
    "vlmdomain_id": "5",
    "vlmdomain_name": "dc-vlan-domain",
    "vlmdomain_description": "Datacenter VLANs",
    "vlmdomain_start_vlan_id": "100",
    "vlmdomain_end_vlan_id": "3999",
    "vlmdomain_class_name": "",
    "support_vxlan": "0",
    "vlmdomain_class_parameters": "tenant=core",
    "vlmdomain_class_parameters_properties": "tenant=set,propagate",
    "row_enabled": "1",
}


def test_vlan_range_coerce_fields() -> None:
    r = VlanRange.model_validate(_LIST_ROW)
    assert r.vlmrange_id == 3
    assert r.vlmrange_start_vlan_id == 100
    assert r.vlmrange_end_vlan_id == 999
    assert r.vlmrange_disable_overlapping is True
    assert r.vlmdomain_id == 5
    assert r.vlmdomain_start_vlan_id == 100
    assert r.support_vxlan is False
    assert r.row_enabled == RowEnabled.ENABLED


def test_vlan_range_class_params() -> None:
    r = VlanRange.model_validate(_LIST_ROW)
    assert r.class_params["env"] == "prod"
    assert r.class_params.source("env") == ("real_vlmrange", "3")
    assert r.vlmdomain_class_params is not None
    assert r.vlmdomain_class_params["tenant"] == "core"


def test_vlan_range_write_params_name() -> None:
    r = VlanRange.model_validate(_LIST_ROW)
    r.vlmrange_name = "prod-range-v2"
    assert r.write_params() == {"vlmrange_name": "prod-range-v2"}


def test_vlan_range_write_params_overlapping() -> None:
    r = VlanRange.model_validate(_LIST_ROW)
    r.vlmrange_disable_overlapping = False
    assert r.write_params() == {"vlmrange_disable_overlapping": "0"}


def test_vlan_range_build_request_create() -> None:
    r = VlanRange(vlmrange_name="test-range", vlmdomain_id=5, vlmrange_start_vlan_id=100, vlmrange_end_vlan_id=200)
    r.mark_new()
    verb, path, params = r.build_request("create")
    assert verb == "POST"
    assert path == "rest/vlm_range_add"
    assert params["vlmrange_name"] == "test-range"


def test_vlan_range_build_request_delete() -> None:
    r = VlanRange.model_validate(_LIST_ROW)
    verb, path, params = r.build_request("delete")
    assert verb == "DELETE"
    assert path == "rest/vlm_range_delete"
    assert params["vlmrange_id"] == "3"


def test_vlan_range_no_model_extra() -> None:
    r = VlanRange.model_validate(_LIST_ROW)
    assert not r.model_extra


def test_vlan_range_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert VlanRange._coerce(sentinel) is sentinel


def test_vlan_range_unknown_extra_is_preserved() -> None:
    r = VlanRange.model_validate({**_LIST_ROW, "custom_marker": "keep-me"})
    assert r.model_extra is not None
    assert r.model_extra["custom_marker"] == "keep-me"


@respx.mock
def test_vlan_range_list_and_get() -> None:
    respx.get(f"{BASE}rest/vlmrange_list").mock(return_value=httpx.Response(200, json=[_LIST_ROW]))
    respx.get(f"{BASE}rest/vlmrange_info").mock(return_value=httpx.Response(200, json=[_LIST_ROW]))

    with Session(HOST, *CREDS) as s:
        listed = s.list(VlanRange)
        fetched = s.get(VlanRange, 3)

    assert len(listed) == 1
    assert listed[0].vlmrange_name == "prod-range"
    assert fetched.vlmrange_id == 3
