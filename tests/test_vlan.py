"""Unit tests for Vlan model and vlmvlan_* services."""

import httpx
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.vlan import Vlan



BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "type": "used",
    "vlmvlan_id": "42",
    "vlmvlan_vlan_id": "101",
    "vlmvlan_name": "web-servers",
    "vlmvlan_class_name": "net/vlan",
    "vlmvlan_class_parameters": "owner=webteam",
    "vlmvlan_class_parameters_properties": "owner=set,propagate",
    "vlmvlan_class_parameters_inheritance_source": "owner=real_vlmvlan,42",
    "vlmrange_id": "3",
    "vlmrange_name": "prod-range",
    "vlmrange_start_vlan_id": "100",
    "vlmrange_end_vlan_id": "999",
    "vlmrange_class_name": "net/range",
    "vlmrange_description": "Production VLANs",
    "vlmrange_row_enabled": "1",
    "vlmrange_class_parameters": "env=prod",
    "vlmrange_class_parameters_properties": "env=set,propagate",
    "vlmdomain_id": "5",
    "vlmdomain_name": "dc-vlan-domain",
    "vlmdomain_description": "Datacenter VLANs",
    "vlmdomain_start_vlan_id": "100",
    "vlmdomain_end_vlan_id": "3999",
    "vlmdomain_class_name": "",
    "support_vxlan": "1",
    "vlmdomain_class_parameters": "tenant=core",
    "vlmdomain_class_parameters_properties": "tenant=set,propagate",
    "row_enabled": "1",
}


def test_vlan_vlan_coerce_used_row() -> None:
    v = Vlan.model_validate(_LIST_ROW)
    assert v.vlmvlan_id == 42
    assert v.vlmvlan_vlan_id == 101
    assert v.type == "used"
    assert v.vlmrange_id == 3
    assert v.vlmdomain_id == 5
    assert v.support_vxlan is True
    assert v.row_enabled == RowEnabled.ENABLED


def test_vlan_vlan_class_params() -> None:
    v = Vlan.model_validate(_LIST_ROW)
    assert v.class_params["owner"] == "webteam"
    assert v.vlmrange_class_params is not None
    assert v.vlmrange_class_params["env"] == "prod"
    assert v.vlmdomain_class_params is not None
    assert v.vlmdomain_class_params["tenant"] == "core"


def test_vlan_vlan_write_params_name() -> None:
    v = Vlan.model_validate(_LIST_ROW)
    v.vlmvlan_name = "db-servers"
    assert v.write_params() == {"vlmvlan_name": "db-servers"}


def test_vlan_vlan_build_request_create() -> None:
    v = Vlan(vlmvlan_vlan_id=150, vlmdomain_id=5)
    v.mark_new()
    verb, path, params = v.build_request("create")
    assert verb == "POST"
    assert path == "rest/vlm_vlan_add"
    assert params["vlmvlan_vlan_id"] == "150"
    assert "vlan_id" not in params


def test_vlan_vlan_build_request_delete() -> None:
    v = Vlan.model_validate(_LIST_ROW)
    verb, path, params = v.build_request("delete")
    assert verb == "DELETE"
    assert path == "rest/vlm_vlan_delete"
    assert params["vlmvlan_id"] == "42"


def test_vlan_vlan_no_model_extra() -> None:
    v = Vlan.model_validate(_LIST_ROW)
    assert not v.model_extra


def test_vlan_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert Vlan._coerce(sentinel) is sentinel


def test_vlan_unknown_extra_is_preserved() -> None:
    v = Vlan.model_validate({**_LIST_ROW, "custom_marker": "keep-me"})
    assert v.model_extra is not None
    assert v.model_extra["custom_marker"] == "keep-me"


def test_vlan_vlan_free_row() -> None:
    free_row: dict[str, str] = {
        "errno": "0",
        "type": "free",
        "vlmvlan_id": "0",
        "vlmvlan_vlan_id": "0",
        "free_start_vlan_id": "200",
        "free_end_vlan_id": "299",
        "vlmdomain_id": "5",
        "vlmrange_id": "3",
    }
    v = Vlan.model_validate(free_row)
    assert v.type == "free"
    assert v.free_start_vlan_id == 200
    assert v.free_end_vlan_id == 299
    assert v.vlmvlan_name is None


def test_vlan_vlmvlan_vlan_id_property() -> None:
    v = Vlan.model_validate(_LIST_ROW)
    assert v.vlmvlan_vlan_id == v.vlan_id
    assert v.vlmvlan_vlan_id == 101


@respx.mock
def test_vlan_vlan_list_and_get() -> None:
    respx.get(f"{BASE}rest/vlmvlan_list").mock(return_value=httpx.Response(200, json=[_LIST_ROW]))
    respx.get(f"{BASE}rest/vlmvlan_info").mock(return_value=httpx.Response(200, json=[_LIST_ROW]))

    with Session(HOST, *CREDS) as s:
        listed = s.list(Vlan)
        fetched = s.get(Vlan, 42)

    assert len(listed) == 1
    assert listed[0].vlmvlan_name == "web-servers"
    assert fetched.vlmvlan_id == 42
