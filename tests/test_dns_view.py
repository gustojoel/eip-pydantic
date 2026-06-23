"""Unit tests for DnsView model."""

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.dns_view import DnsView



HOST = "solidserver.example.com"
CREDS = ("admin", "secret")
BASE = f"https://{HOST}/"

_VIEW_ROW: dict[str, str] = {
    "errno": "0",
    "dnsview_id": "12",
    "dnsview_name": "external",
    "dnsview_order": "0",
    "dnsview_recursion": "no",
    "dnsview_match_clients": "any",
    "dnsview_match_to": "",
    "dnsview_allow_recursion": "",
    "dnsview_allow_query": "any",
    "dnsview_allow_transfer": "",
    "dnsview_key_name": "",
    "dnsview_class_name": "",
    "dns_id": "3",
    "dns_name": "ns1.example.com",
    "dns_type": "ipm",
    "dns_class_name": "corporate/ns",
    "dns_comment": "Primary DNS",
    "dns_version": "9.11.4",
    "vdns_parent_id": "0",
    "vdns_parent_name": "#",
    "gss_keytab_id": "0",
    "delayed_create_time": "0",
    "delayed_delete_time": "0",
    "ip_addr": "0a540100",
    "ip6_addr": "",
    "hostaddr": "10.84.1.0",
    "multistatus": "",
    "dnsview_class_parameters": "acl=strict",
    "dnsview_class_parameters_properties": "acl=set,propagate",
    "dnsview_class_parameters_inheritance_source": "acl=real_dnsview,12",
    "dns_class_parameters": "env=prod",
    "dns_class_parameters_properties": "env=set,propagate",
    "row_enabled": "1",
}


class TestDnsViewCoerce:
    def test_int_fields(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        assert v.dnsview_id == 12
        assert v.dns_id == 3
        assert v.dnsview_order == 0
        assert v.delayed_create_time == 0
        assert v.delayed_delete_time == 0

    def test_nz_int_zero_becomes_none(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        assert v.vdns_parent_id is None
        assert v.gss_keytab_id is None

    def test_hex_ipv4(self) -> None:
        from ipaddress import IPv4Address
        v = DnsView.model_validate(_VIEW_ROW)
        assert v.ip_addr == IPv4Address("10.84.1.0")

    def test_str_sentinel_to_none(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        assert v.dnsview_match_to is None
        assert v.dnsview_class_name is None

    def test_str_fields_preserved(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        assert v.dnsview_name == "external"
        assert v.dnsview_recursion == "no"
        assert v.dns_name == "ns1.example.com"

    def test_row_enabled(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        assert v.row_enabled == RowEnabled.ENABLED

    def test_class_params_from_blobs(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        assert v.class_params["acl"] == "strict"
        assert v.class_params.source("acl") == ("real_dnsview", "12")

    def test_parent_blob_keys_filtered(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        assert v.model_extra is not None
        assert "dnsview_class_parameters" not in v.model_extra
        assert "dns_class_parameters" not in v.model_extra
        assert "dns_class_parameters_properties" not in v.model_extra

    def test_class_params_passthrough_branch(self) -> None:
        cp = ClassParamDict.from_blobs("acl=relaxed", None, None, api_prefix="dnsview")
        v = DnsView.model_validate({**_VIEW_ROW, "class_params": cp})
        assert v.class_params["acl"] == "relaxed"

    def test_unknown_extra_preserved(self) -> None:
        v = DnsView.model_validate({**_VIEW_ROW, "tag_dnsview_region": "eu"})
        assert v.model_extra is not None
        assert v.model_extra["tag_dnsview_region"] == "eu"

    def test_non_dict_passthrough(self) -> None:
        sentinel = object()
        assert DnsView._coerce(sentinel) is sentinel

    def test_frozen_dnsview_id_raises(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        with pytest.raises(Exception):
            v.dnsview_id = 99  # type: ignore[misc]

    def test_frozen_ip_addr_raises(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        with pytest.raises(Exception):
            from ipaddress import IPv4Address
            v.ip_addr = IPv4Address("1.2.3.4")  # type: ignore[misc]


class TestDnsViewWriteParams:
    def test_clean_is_empty(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        assert v.write_params() == {}

    def test_str_field_dirty(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        v.dnsview_name = "internal"
        assert v.write_params() == {"dnsview_name": "internal"}

    def test_none_field_becomes_empty_string(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        v.dnsview_name = None   # was "external" → now None → should emit ""
        result = v.write_params()
        assert result.get("dnsview_name") == ""

    def test_class_params_dirty_skipped_in_loop(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        v.class_params["ticket"] = "INC001"
        result = v.write_params()
        assert "dnsview_class_parameters" in result
        assert "class_params" not in result

    def test_multiple_dirty_fields(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        v.dnsview_name = "renamed"
        v.dnsview_allow_query = "none"
        result = v.write_params()
        assert result["dnsview_name"] == "renamed"
        assert result["dnsview_allow_query"] == "none"


class TestDnsViewBuildRequest:
    def test_create(self) -> None:
        v = DnsView(dnsview_name="external", dns_id=3)
        v.mark_new()
        verb, path, params = v.build_request("create")
        assert verb == "POST"
        assert path == "rest/dns_view_add"
        assert params["dnsview_name"] == "external"

    def test_update(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        v.dnsview_name = "internal"
        verb, path, params = v.build_request("update")
        assert verb == "PUT"
        assert path == "rest/dns_view_add"
        assert params["dnsview_id"] == "12"

    def test_delete(self) -> None:
        v = DnsView.model_validate(_VIEW_ROW)
        verb, path, params = v.build_request("delete")
        assert verb == "DELETE"
        assert path == "rest/dns_view_delete"
        assert params["dnsview_id"] == "12"


def test_dns_view_parent_fields() -> None:
    assert DnsView.solid_config.parent_fields == {"dns_id": "dns_id"}


@respx.mock
def test_dns_view_list() -> None:
    respx.get(f"{BASE}rest/dns_view_list").mock(
        return_value=httpx.Response(200, json=[_VIEW_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        views = s.list(DnsView)
    assert len(views) == 1
    assert views[0].dnsview_id == 12


@respx.mock
def test_dns_view_get() -> None:
    respx.get(f"{BASE}rest/dns_view_info").mock(
        return_value=httpx.Response(200, json=[_VIEW_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        v = s.get(DnsView, 12)
    assert v.dnsview_name == "external"


@respx.mock
def test_dns_view_create() -> None:
    route = respx.post(f"{BASE}rest/dns_view_add").mock(
        return_value=httpx.Response(200, json=[{"errno": "0", "ret_oid": "13"}]),
    )
    with Session(HOST, *CREDS) as s:
        v = DnsView(dnsview_name="internal", dns_id=3)
        s.new(v)
        s.flush()
    assert route.called
    sent = route.calls.last.request.url.params
    assert sent["dnsview_name"] == "internal"


@respx.mock
def test_dns_view_update() -> None:
    respx.get(f"{BASE}rest/dns_view_info").mock(
        return_value=httpx.Response(200, json=[_VIEW_ROW]),
    )
    route = respx.put(f"{BASE}rest/dns_view_add").mock(
        return_value=httpx.Response(200, json=[{"errno": "0", "ret_oid": "12"}]),
    )
    with Session(HOST, *CREDS) as s:
        v = s.get(DnsView, 12)
        v.dnsview_name = "renamed"
    assert route.called
    assert route.calls.last.request.url.params["dnsview_id"] == "12"


@respx.mock
def test_dns_view_delete() -> None:
    respx.get(f"{BASE}rest/dns_view_info").mock(
        return_value=httpx.Response(200, json=[_VIEW_ROW]),
    )
    route = respx.delete(f"{BASE}rest/dns_view_delete").mock(
        return_value=httpx.Response(200, json=[{"errno": "0"}]),
    )
    with Session(HOST, *CREDS) as s:
        v = s.get(DnsView, 12)
        s.delete(v)
    assert route.called
    assert route.calls.last.request.url.params["dnsview_id"] == "12"


@respx.mock
def test_dns_view_expression_builder() -> None:
    route = respx.get(f"{BASE}rest/dns_view_list").mock(
        return_value=httpx.Response(200, json=[_VIEW_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(DnsView, where=DnsView.c.dnsview_name == "external")
    assert route.calls.last.request.url.params["WHERE"] == "dnsview_name='external'"
