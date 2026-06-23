"""Unit tests for DnsZone model."""

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.dns_zone import DnsZone



HOST = "solidserver.example.com"
CREDS = ("admin", "secret")
BASE = f"https://{HOST}/"

_ZONE_ROW: dict[str, str] = {
    "errno": "0",
    "dnszone_id": "50",
    "dnszone_name": "example.com",
    "dnszone_name_utf": "example.com",
    "dnszone_type": "master",
    "dnszone_masters": "",
    "dnszone_forwarders": "",
    "dnszone_forward": "",
    "dnszone_allow_transfer": "none",
    "dnszone_allow_query": "any",
    "dnszone_allow_update": "none",
    "dnszone_also_notify": "",
    "dnszone_notify": "yes",
    "dnszone_class_name": "",
    "dnszone_response_policy": "",
    "dnszone_ad_integrated": "0",
    "dnszone_is_rpz": "1",
    "dnszone_rpz_log": "0",
    "dnszone_rpz_recursive_only": "1",
    "dnszone_rpz_max_policy_ttl": "30",
    "dnszone_is_reverse": "0",
    "use_update_policy": "0",
    "dnszone_order": "2",
    "ddns_scavenging": "1",
    "num_keys": "2",
    "gss_enabled": "1",
    "gss_keytab_id": "0",
    "dnszone_synching": "0",
    "dns_state": "Y",
    "vdns_parent_id": "0",
    "vdns_parent_name": "#",
    "delayed_delete_time": "0",
    "delayed_create_time": "0",
    "dnszone_site_name": "",
    "dnszone_site_id": "0",
    "dnsview_id": "0",
    "dnsview_name": "",
    "dnsview_class_name": "",
    "dns_id": "3",
    "dns_name": "ns1.example.com",
    "dns_type": "ipm",
    "dns_comment": "",
    "dns_version": "9.11.4",
    "dns_class_name": "corporate/ns",
    "ds": "",
    "ip_addr": "0a540100",
    "ip6_addr": "",
    "hostaddr": "10.84.1.0",
    "dns_vpc_list": "",
    "aws_delegation_set": "",
    "multistatus": "",
    "ipmdns_type": "named",
    "dnszone_class_parameters": "tier=prod",
    "dnszone_class_parameters_properties": "tier=set,propagate",
    "dnszone_class_parameters_inheritance_source": "tier=real_dnszone,50",
    "dnsview_class_parameters": "acl=strict",
    "dnsview_class_parameters_properties": "acl=set,propagate",
    "dns_class_parameters": "env=prod",
    "dns_class_parameters_properties": "env=set,propagate",
    "row_enabled": "1",
}


class TestDnsZoneCoerce:
    def test_int_fields(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.dnszone_id == 50
        assert z.dns_id == 3
        assert z.dnszone_order == 2
        assert z.dnszone_rpz_max_policy_ttl == 30
        assert z.num_keys == 2
        assert z.dnszone_synching == 0
        assert z.delayed_create_time == 0
        assert z.delayed_delete_time == 0

    def test_nz_int_zero_becomes_none(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.vdns_parent_id is None
        assert z.gss_keytab_id is None
        assert z.dnsview_id is None
        assert z.dnszone_site_id is None

    def test_nz_int_nonzero_preserved(self) -> None:
        z = DnsZone.model_validate({**_ZONE_ROW, "dnsview_id": "12", "dnszone_site_id": "5"})
        assert z.dnsview_id == 12
        assert z.dnszone_site_id == 5

    def test_bool_fields(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.dnszone_ad_integrated is False
        assert z.dnszone_is_rpz is True
        assert z.dnszone_rpz_log is False
        assert z.dnszone_rpz_recursive_only is True
        assert z.dnszone_is_reverse is False
        assert z.use_update_policy is False
        assert z.ddns_scavenging is True
        assert z.gss_enabled is True

    def test_hex_ipv4(self) -> None:
        from ipaddress import IPv4Address
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.ip_addr == IPv4Address("10.84.1.0")

    def test_str_sentinel_to_none(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.dnszone_class_name is None
        assert z.dnsview_name is None

    def test_str_fields_preserved(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.dnszone_name == "example.com"
        assert z.dnszone_type == "master"

    def test_frozen_dnszone_id_raises(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        with pytest.raises(Exception):
            z.dnszone_id = 99  # type: ignore[misc]

    def test_frozen_dnszone_name_raises(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        with pytest.raises(Exception):
            z.dnszone_name = "changed.com"  # type: ignore[misc]

    def test_row_enabled(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.row_enabled == RowEnabled.ENABLED

    def test_class_params_from_blobs(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.class_params["tier"] == "prod"
        assert z.class_params.source("tier") == ("real_dnszone", "50")

    def test_all_parent_blob_keys_filtered(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.model_extra is not None
        for bk in (
            "dnszone_class_parameters", "dnszone_class_parameters_properties",
            "dnszone_class_parameters_inheritance_source",
            "dnsview_class_parameters", "dnsview_class_parameters_properties",
            "dns_class_parameters", "dns_class_parameters_properties",
        ):
            assert bk not in z.model_extra

    def test_class_params_passthrough_branch(self) -> None:
        cp = ClassParamDict.from_blobs("tier=dev", None, None, api_prefix="dnszone")
        z = DnsZone.model_validate({**_ZONE_ROW, "class_params": cp})
        assert z.class_params["tier"] == "dev"

    def test_unknown_extra_preserved(self) -> None:
        z = DnsZone.model_validate({**_ZONE_ROW, "tag_dnszone_env": "staging"})
        assert z.model_extra is not None
        assert z.model_extra["tag_dnszone_env"] == "staging"

    def test_non_dict_passthrough(self) -> None:
        sentinel = object()
        assert DnsZone._coerce(sentinel) is sentinel


class TestDnsZoneWriteParams:
    def test_clean_is_empty(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        assert z.write_params() == {}

    def test_bool_field_true(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        z.dnszone_ad_integrated = True
        assert z.write_params() == {"dnszone_ad_integrated": "1"}

    def test_bool_field_false(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        z.dnszone_is_rpz = False
        assert z.write_params() == {"dnszone_is_rpz": "0"}

    def test_bool_field_none_becomes_empty_string(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        z.dnszone_rpz_log = None
        result = z.write_params()
        assert result.get("dnszone_rpz_log") == ""

    def test_all_bool_fields_covered(self) -> None:
        """Exercise every bool field name in the write_params match branch."""
        z = DnsZone.model_validate(_ZONE_ROW)
        z.dnszone_rpz_recursive_only = False
        z.use_update_policy = True
        z.ddns_scavenging = False
        z.gss_enabled = None
        result = z.write_params()
        assert result["dnszone_rpz_recursive_only"] == "0"
        assert result["use_update_policy"] == "1"
        assert result["ddns_scavenging"] == "0"
        assert result["gss_enabled"] == ""

    def test_str_field_dirty(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        z.dnszone_type = "slave"
        assert z.write_params() == {"dnszone_type": "slave"}

    def test_str_field_none_becomes_empty_string(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        z.dnszone_type = None   # was "master" → now None → should emit ""
        result = z.write_params()
        assert result.get("dnszone_type") == ""

    def test_class_params_dirty_skipped_in_loop(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        z.class_params["env"] = "staging"
        result = z.write_params()
        assert "dnszone_class_parameters" in result
        assert "class_params" not in result


class TestDnsZoneBuildRequest:
    def test_create(self) -> None:
        z = DnsZone(dnszone_name="example.com", dnszone_type="master", dns_id=3)
        z.mark_new()
        verb, path, _ = z.build_request("create")
        assert verb == "POST"
        assert path == "rest/dns_zone_add"

    def test_update(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        z.dnszone_type = "slave"
        verb, path, params = z.build_request("update")
        assert verb == "PUT"
        assert path == "rest/dns_zone_add"
        assert params["dnszone_id"] == "50"

    def test_delete(self) -> None:
        z = DnsZone.model_validate(_ZONE_ROW)
        verb, path, params = z.build_request("delete")
        assert verb == "DELETE"
        assert path == "rest/dns_zone_delete"
        assert params["dnszone_id"] == "50"


def test_dns_zone_parent_fields() -> None:
    pf = DnsZone.solid_config.parent_fields
    assert pf["dns_id"] == "dns_id"
    assert pf["dnsview_id"] == "dnsview_id"


@respx.mock
def test_dns_zone_list() -> None:
    respx.get(f"{BASE}rest/dns_zone_list").mock(
        return_value=httpx.Response(200, json=[_ZONE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        zones = s.list(DnsZone)
    assert len(zones) == 1
    assert zones[0].dnszone_id == 50


@respx.mock
def test_dns_zone_get() -> None:
    respx.get(f"{BASE}rest/dns_zone_info").mock(
        return_value=httpx.Response(200, json=[_ZONE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        z = s.get(DnsZone, 50)
    assert z.dnszone_name == "example.com"


@respx.mock
def test_dns_zone_create() -> None:
    route = respx.post(f"{BASE}rest/dns_zone_add").mock(
        return_value=httpx.Response(200, json=[{"errno": "0", "ret_oid": "51"}]),
    )
    with Session(HOST, *CREDS) as s:
        z = DnsZone(dnszone_name="sub.example.com", dnszone_type="master", dns_id=3)
        s.new(z)
        s.flush()
    assert route.called
    sent = route.calls.last.request.url.params
    assert sent["dnszone_name"] == "sub.example.com"


@respx.mock
def test_dns_zone_update() -> None:
    respx.get(f"{BASE}rest/dns_zone_info").mock(
        return_value=httpx.Response(200, json=[_ZONE_ROW]),
    )
    route = respx.put(f"{BASE}rest/dns_zone_add").mock(
        return_value=httpx.Response(200, json=[{"errno": "0", "ret_oid": "50"}]),
    )
    with Session(HOST, *CREDS) as s:
        z = s.get(DnsZone, 50)
        z.dnszone_type = "slave"
    assert route.called


@respx.mock
def test_dns_zone_delete() -> None:
    respx.get(f"{BASE}rest/dns_zone_info").mock(
        return_value=httpx.Response(200, json=[_ZONE_ROW]),
    )
    route = respx.delete(f"{BASE}rest/dns_zone_delete").mock(
        return_value=httpx.Response(200, json=[{"errno": "0"}]),
    )
    with Session(HOST, *CREDS) as s:
        z = s.get(DnsZone, 50)
        s.delete(z)
    assert route.called
    assert route.calls.last.request.url.params["dnszone_id"] == "50"


@respx.mock
def test_dns_zone_expression_builder() -> None:
    route = respx.get(f"{BASE}rest/dns_zone_list").mock(
        return_value=httpx.Response(200, json=[_ZONE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(DnsZone, where=DnsZone.c.dnszone_name == "example.com")
    assert route.calls.last.request.url.params["WHERE"] == "dnszone_name='example.com'"
