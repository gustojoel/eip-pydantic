"""Unit tests for DnsRr model."""

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.dns_rr import DnsRr



HOST = "solidserver.example.com"
CREDS = ("admin", "secret")
BASE = f"https://{HOST}/"

_RR_ROW: dict[str, str] = {
    "errno": "0",
    "rr_id": "200",
    "rr_type": "A",
    "rr_name": "www.example.com.",
    "rr_full_name": "www.example.com.",
    "rr_full_name_utf": "www.example.com.",
    "rr_glue": "www",
    "rr_all_value": "10.0.0.1",
    "rr_class_name": "",
    "value1": "10.0.0.1",
    "value2": "",
    "value3": "",
    "value4": "",
    "value5": "",
    "value6": "",
    "value7": "",
    "ttl": "3600",
    "delayed_time": "0",
    "delayed_create_time": "0",
    "delayed_delete_time": "0",
    "dnszone_id": "50",
    "dns_id": "3",
    "dnszone_name": "example.com",
    "dnszone_name_utf": "example.com",
    "dns_name": "ns1.example.com",
    "dns_type": "ipm",
    "vdns_parent_id": "0",
    "vdns_parent_name": "#",
    "dnsview_id": "0",
    "dnsview_name": "",
    "dnsview_class_name": "",
    "dnszone_site_name": "",
    "dnszone_site_id": "0",
    "dnszone_is_reverse": "0",
    "dnszone_masters": "",
    "dnszone_forwarders": "",
    "dnszone_type": "master",
    "dnszone_is_rpz": "1",
    "dnszone_class_name": "",
    "dns_class_name": "corporate/ns",
    "dns_version": "9.11.4",
    "dns_comment": "",
    "multistatus": "",
    "rr_auth_gsstsig": "1",
    "rr_last_update_days": "5",
    "rr_class_parameters": "owner=ops",
    "rr_class_parameters_properties": "owner=set,propagate",
    "rr_class_parameters_inheritance_source": "owner=real_rr,200",
    "dnsview_class_parameters": "acl=strict",
    "dnsview_class_parameters_properties": "acl=set,propagate",
    "dnsview_class_parameters_inheritance_source": "acl=real_dnsview,12",
    "row_enabled": "1",
}


class TestDnsRrCoerce:
    def test_int_fields(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        assert r.rr_id == 200
        assert r.ttl == 3600
        assert r.delayed_time == 0
        assert r.delayed_create_time == 0
        assert r.delayed_delete_time == 0
        assert r.dnszone_id == 50
        assert r.dns_id == 3
        assert r.rr_last_update_days == 5

    def test_nz_int_zero_becomes_none(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        assert r.vdns_parent_id is None
        assert r.dnsview_id is None
        assert r.dnszone_site_id is None

    def test_nz_int_nonzero_preserved(self) -> None:
        r = DnsRr.model_validate({**_RR_ROW, "dnsview_id": "12"})
        assert r.dnsview_id == 12

    def test_bool_fields(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        assert r.dnszone_is_reverse is False
        assert r.dnszone_is_rpz is True
        assert r.rr_auth_gsstsig is True

    def test_str_fields_preserved(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        assert r.rr_type == "A"
        assert r.rr_name == "www.example.com."
        assert r.value1 == "10.0.0.1"

    def test_str_sentinel_to_none(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        assert r.value2 is None
        assert r.rr_class_name is None

    def test_row_enabled(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        assert r.row_enabled == RowEnabled.ENABLED

    def test_class_params_from_blobs(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        assert r.class_params["owner"] == "ops"
        assert r.class_params.source("owner") == ("real_rr", "200")

    def test_all_blob_keys_filtered(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        assert r.model_extra is not None
        for bk in (
            "rr_class_parameters", "rr_class_parameters_properties",
            "rr_class_parameters_inheritance_source",
            "dnsview_class_parameters", "dnsview_class_parameters_properties",
            "dnsview_class_parameters_inheritance_source",
        ):
            assert bk not in r.model_extra

    def test_class_params_passthrough_branch(self) -> None:
        cp = ClassParamDict.from_blobs("owner=noc", None, None, api_prefix="rr")
        r = DnsRr.model_validate({**_RR_ROW, "class_params": cp})
        assert r.class_params["owner"] == "noc"

    def test_unknown_extra_preserved(self) -> None:
        r = DnsRr.model_validate({**_RR_ROW, "tag_custom": "v"})
        assert r.model_extra is not None
        assert r.model_extra["tag_custom"] == "v"

    def test_non_dict_passthrough(self) -> None:
        sentinel = object()
        assert DnsRr._coerce(sentinel) is sentinel

    def test_frozen_rr_id_raises(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        with pytest.raises(Exception):
            r.rr_id = 999  # type: ignore[misc]


class TestDnsRrWriteParams:
    def test_clean_is_empty(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        assert r.write_params() == {}

    def test_str_field_dirty(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        r.value1 = "10.0.0.2"
        assert r.write_params() == {"value1": "10.0.0.2"}

    def test_none_field_becomes_empty_string(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        r.value1 = None   # was "10.0.0.1" → now None → should emit ""
        result = r.write_params()
        assert result.get("value1") == ""

    def test_class_params_dirty_skipped_in_loop(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        r.class_params["ticket"] = "CHG001"
        result = r.write_params()
        assert "rr_class_parameters" in result
        assert "class_params" not in result

    def test_multiple_dirty_fields(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        r.value1 = "192.168.1.1"
        r.rr_class_name = "myclass"
        result = r.write_params()
        assert result["value1"] == "192.168.1.1"
        assert result["rr_class_name"] == "myclass"


class TestDnsRrBuildRequest:
    def test_create(self) -> None:
        r = DnsRr(rr_type="A", rr_name="www", value1="10.0.0.1", dnszone_id=50, dns_id=3)
        r.mark_new()
        verb, path, params = r.build_request("create")
        assert verb == "POST"
        assert path == "rest/dns_rr_add"
        assert params["rr_type"] == "A"

    def test_update(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        r.value1 = "10.0.0.5"
        verb, path, params = r.build_request("update")
        assert verb == "PUT"
        assert path == "rest/dns_rr_add"
        assert params["rr_id"] == "200"

    def test_delete(self) -> None:
        r = DnsRr.model_validate(_RR_ROW)
        verb, path, params = r.build_request("delete")
        assert verb == "DELETE"
        assert path == "rest/dns_rr_delete"
        assert params["rr_id"] == "200"


def test_dns_rr_parent_fields() -> None:
    pf = DnsRr.solid_config.parent_fields
    assert pf["dnszone_id"] == "dnszone_id"
    assert pf["dns_id"] == "dns_id"
    assert pf["dnsview_id"] == "dnsview_id"


def test_dns_rr_has_no_tags_prefix() -> None:
    assert DnsRr.solid_config.tags_prefix == ""


def test_dns_rr_rr_ttl_in_create_fields() -> None:
    assert "rr_ttl" in DnsRr.solid_config.create_fields  # type: ignore[operator]


@respx.mock
def test_dns_rr_list() -> None:
    respx.get(f"{BASE}rest/dns_rr_list").mock(
        return_value=httpx.Response(200, json=[_RR_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        rrs = s.list(DnsRr)
    assert len(rrs) == 1
    assert rrs[0].rr_id == 200


@respx.mock
def test_dns_rr_get() -> None:
    respx.get(f"{BASE}rest/dns_rr_info").mock(
        return_value=httpx.Response(200, json=[_RR_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        r = s.get(DnsRr, 200)
    assert r.rr_type == "A"


@respx.mock
def test_dns_rr_create() -> None:
    route = respx.post(f"{BASE}rest/dns_rr_add").mock(
        return_value=httpx.Response(200, json=[{"errno": "0", "ret_oid": "201"}]),
    )
    with Session(HOST, *CREDS) as s:
        r = DnsRr(rr_type="A", rr_name="api", value1="10.0.0.10", dnszone_id=50, dns_id=3)
        s.new(r)
        s.flush()
    assert route.called
    sent = route.calls.last.request.url.params
    assert sent["rr_type"] == "A"
    assert sent["value1"] == "10.0.0.10"


@respx.mock
def test_dns_rr_update() -> None:
    respx.get(f"{BASE}rest/dns_rr_info").mock(
        return_value=httpx.Response(200, json=[_RR_ROW]),
    )
    route = respx.put(f"{BASE}rest/dns_rr_add").mock(
        return_value=httpx.Response(200, json=[{"errno": "0", "ret_oid": "200"}]),
    )
    with Session(HOST, *CREDS) as s:
        r = s.get(DnsRr, 200)
        r.value1 = "10.0.0.99"
    assert route.called
    assert route.calls.last.request.url.params["rr_id"] == "200"


@respx.mock
def test_dns_rr_delete() -> None:
    respx.get(f"{BASE}rest/dns_rr_info").mock(
        return_value=httpx.Response(200, json=[_RR_ROW]),
    )
    route = respx.delete(f"{BASE}rest/dns_rr_delete").mock(
        return_value=httpx.Response(200, json=[{"errno": "0"}]),
    )
    with Session(HOST, *CREDS) as s:
        r = s.get(DnsRr, 200)
        s.delete(r)
    assert route.called
    assert route.calls.last.request.url.params["rr_id"] == "200"


@respx.mock
def test_dns_rr_list_with_limit() -> None:
    route = respx.get(f"{BASE}rest/dns_rr_list").mock(
        return_value=httpx.Response(200, json=[_RR_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(DnsRr, limit=10)
    assert route.calls.last.request.url.params["limit"] == "10"
