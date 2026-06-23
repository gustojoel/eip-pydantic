"""Unit tests for DnsServer model."""

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.dns_server import DnsServer



HOST = "solidserver.example.com"
CREDS = ("admin", "secret")
BASE = f"https://{HOST}/"

_SERVER_ROW: dict[str, str] = {
    "errno": "0",
    "dns_id": "3",
    "dns_name": "ns1.example.com",
    "dns_type": "ipm",
    "dns_comment": "Primary DNS",
    "dns_version": "9.11.4",
    "dns_state": "Y",
    "dns_class_name": "corporate/ns",
    "dns_role": "master",
    "dns_notify": "yes",
    "dns_also_notify": "",
    "dns_allow_query": "any",
    "dns_allow_query_cache": "",
    "dns_allow_transfer": "",
    "dns_allow_recursion": "any",
    "dns_recursion": "yes",
    "dns_forwarders": "",
    "dns_forward": "",
    "dns_key_name": "",
    "dns_key_value": "",
    "dns_key_proto": "",
    "dns_rpz_recursive_only": "1",
    "dns_rpz_break_dnssec": "0",
    "dns_rpz_qname_wait_recurse": "0",
    "dns_rpz_max_policy_ttl": "5",
    "dns_rpz_min_ns_dots": "1",
    "gss_keytab_id": "0",
    "gss_enabled": "0",
    "tree_level": "0",
    "tree_path": "ns1.example.com#",
    "total_vdns_members": "0",
    "vdns_members_name": "",
    "vdns_arch": "",
    "vdns_parent_id": "0",
    "vdns_parent_name": "#",
    "vdns_parent_arch": "",
    "vdns_public_ns_list": "",
    "ip_addr": "0a540100",
    "ip6_addr": "",
    "hostaddr": "10.84.1.0",
    "connectionprofile_name": "",
    "ipmdns_type": "named",
    "ipmdns_is_package": "N",
    "ldap_user": "",
    "ldap_domain": "",
    "isolated": "",
    "reverse_proxy_conf": "",
    "aws_keyid": "",
    "aws_use_role": "",
    "aws_role_arn": "",
    "aws_role_external_id": "",
    "aws_role_session_name": "",
    "aws_delegation_set": "",
    "dns_cloud_private": "0",
    "az_tenantid": "",
    "az_keyid": "",
    "az_subscriptionid": "",
    "az_group": "",
    "dnsblast_enabled": "0",
    "dnsblast_status": "",
    "dnssec_validation": "",
    "dnsgslb_supported": "1",
    "dnsguardian_supported": "0",
    "guardian_stats_only_supported": "",
    "dns_vpc_list": "",
    "querylog_state": "0",
    "dns_synching": "0",
    "multistatus": "",
    "dns_class_parameters": "env=prod",
    "dns_class_parameters_properties": "env=set,propagate",
    "dns_class_parameters_inheritance_source": "env=real_dns,3",
    "row_enabled": "1",
}


class TestDnsServerCoerce:
    def test_int_fields(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.dns_id == 3
        assert s.errno == 0
        assert s.tree_level == 0
        assert s.total_vdns_members == 0
        assert s.dns_rpz_max_policy_ttl == 5
        assert s.dns_rpz_min_ns_dots == 1

    def test_nz_int_zero_becomes_none(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.vdns_parent_id is None   # "0" → None
        assert s.gss_keytab_id is None    # "0" → None

    def test_nz_int_nonzero_preserved(self) -> None:
        s = DnsServer.model_validate({**_SERVER_ROW, "vdns_parent_id": "7", "gss_keytab_id": "2"})
        assert s.vdns_parent_id == 7
        assert s.gss_keytab_id == 2

    def test_bool_fields_true(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.dns_rpz_recursive_only is True   # "1"

    def test_bool_fields_false(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.dns_rpz_break_dnssec is False    # "0"
        assert s.dns_rpz_qname_wait_recurse is False
        assert s.gss_enabled is False

    def test_additional_bool_fields(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        # PDF-confirmed booleans (0/1 flags)
        assert s.dns_cloud_private is False       # "0" → False
        assert s.dnsblast_enabled is False        # "0" → False
        assert s.dnsgslb_supported is True        # "1" → True
        assert s.dnsguardian_supported is False   # "0" → False
        assert s.querylog_state is False          # "0" → False
        assert s.dns_synching is False            # "0" → False
        # "" → None for optional booleans
        assert s.isolated is None
        assert s.aws_use_role is None
        assert s.guardian_stats_only_supported is None

    def test_additional_bool_fields_nonzero(self) -> None:
        s = DnsServer.model_validate({
            **_SERVER_ROW,
            "isolated": "1",
            "aws_use_role": "1",
            "guardian_stats_only_supported": "1",
            "dns_synching": "1",
        })
        assert s.isolated is True
        assert s.aws_use_role is True
        assert s.guardian_stats_only_supported is True
        assert s.dns_synching is True

    def test_dnsblast_status_is_int(self) -> None:
        s = DnsServer.model_validate({**_SERVER_ROW, "dnsblast_status": "2"})
        assert s.dnsblast_status == 2  # Stopped
        # "" → None
        s2 = DnsServer.model_validate(_SERVER_ROW)
        assert s2.dnsblast_status is None

    def test_hex_ipv4(self) -> None:
        from ipaddress import IPv4Address
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.ip_addr == IPv4Address("10.84.1.0")

    def test_str_sentinel_empty_to_none(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.dns_also_notify is None    # "" → None via _as_str
        assert s.vdns_parent_name is None   # "#" → None via _as_str on declared field
        assert s.ldap_user is None
        assert s.ldap_domain is None

    def test_str_field_preserved(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.dns_name == "ns1.example.com"
        assert s.dns_type == "ipm"
        assert s.ipmdns_type == "named"

    def test_row_enabled(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.row_enabled == RowEnabled.ENABLED

    def test_class_params_from_blobs(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.class_params["env"] == "prod"
        assert s.class_params.is_set("env")
        assert s.class_params.is_propagate("env")
        assert s.class_params.source("env") == ("real_dns", "3")

    def test_blob_keys_not_in_model_extra(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        assert s.model_extra is not None
        assert "dns_class_parameters" not in s.model_extra
        assert "dns_class_parameters_properties" not in s.model_extra
        assert "dns_class_parameters_inheritance_source" not in s.model_extra

    def test_class_params_passthrough_branch(self) -> None:
        """Passing an existing ClassParamDict skips from_blobs and goes through directly."""
        cp = ClassParamDict.from_blobs("custom=val", None, None, api_prefix="dns")
        s = DnsServer.model_validate({**_SERVER_ROW, "class_params": cp})
        assert s.class_params["custom"] == "val"

    def test_unknown_extra_preserved(self) -> None:
        s = DnsServer.model_validate({**_SERVER_ROW, "tag_dns_env": "production"})
        assert s.model_extra is not None
        assert s.model_extra["tag_dns_env"] == "production"

    def test_non_dict_passthrough(self) -> None:
        sentinel = object()
        assert DnsServer._coerce(sentinel) is sentinel

    def test_frozen_dns_id_raises(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        with pytest.raises(Exception):
            s.dns_id = 999  # type: ignore[misc]

    def test_frozen_ip_addr_raises(self) -> None:
        s = DnsServer.model_validate(_SERVER_ROW)
        with pytest.raises(Exception):
            from ipaddress import IPv4Address
            s.ip_addr = IPv4Address("1.2.3.4")  # type: ignore[misc]

    def test_empty_class_params(self) -> None:
        s = DnsServer.model_validate({
            **_SERVER_ROW,
            "dns_class_parameters": "",
            "dns_class_parameters_properties": "",
            "dns_class_parameters_inheritance_source": "",
        })
        assert len(s.class_params) == 0


class TestDnsServerBuildRequest:
    def test_build_class_request_list(self) -> None:
        verb, path, _ = DnsServer.build_class_request("list")
        assert verb == "GET"
        assert path == "rest/dns_server_list"

    def test_build_class_request_info(self) -> None:
        verb, path, params = DnsServer.build_class_request("info", id=3)
        assert verb == "GET"
        assert path == "rest/dns_server_info"
        assert params["dns_id"] == "3"

    def test_build_class_request_count(self) -> None:
        verb, path, _ = DnsServer.build_class_request("count")
        assert verb == "GET"
        assert path == "rest/dns_server_count"


def test_dns_server_has_no_add_path() -> None:
    assert "add" not in DnsServer.solid_config.paths
    assert "delete" not in DnsServer.solid_config.paths


def test_dns_server_tags_prefix() -> None:
    assert DnsServer.solid_config.tags_prefix == "dns"


@respx.mock
def test_dns_server_list() -> None:
    respx.get(f"{BASE}rest/dns_server_list").mock(
        return_value=httpx.Response(200, json=[_SERVER_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        servers = s.list(DnsServer)
    assert len(servers) == 1
    assert servers[0].dns_id == 3
    assert servers[0].dns_name == "ns1.example.com"


@respx.mock
def test_dns_server_get() -> None:
    respx.get(f"{BASE}rest/dns_server_info").mock(
        return_value=httpx.Response(200, json=[_SERVER_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        server = s.get(DnsServer, 3)
    assert server.dns_id == 3


@respx.mock
def test_dns_server_list_with_where() -> None:
    route = respx.get(f"{BASE}rest/dns_server_list").mock(
        return_value=httpx.Response(200, json=[_SERVER_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(DnsServer, where="dns_name='ns1.example.com'")
    assert route.calls.last.request.url.params["WHERE"] == "dns_name='ns1.example.com'"


@respx.mock
def test_dns_server_expression_builder() -> None:
    route = respx.get(f"{BASE}rest/dns_server_list").mock(
        return_value=httpx.Response(200, json=[_SERVER_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(DnsServer, where=DnsServer.c.dns_name == "ns1.example.com")
    assert route.calls.last.request.url.params["WHERE"] == "dns_name='ns1.example.com'"
