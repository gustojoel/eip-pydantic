"""Unit tests for the IpAddress model and ip_address_* / ip_add / ip_delete API methods.

Wire-format fixtures use RFC 5737 address ranges (192.0.2.x) and are based on
the actual ip_address_list / ip_address_info response shape observed against a live server.

Key coercion facts verified here:
  - ip_addr / free_start_ip_addr / free_end_ip_addr / pool_start_ip_addr /
    pool_end_ip_addr / subnet_start_ip_addr / subnet_end_ip_addr /
    parent_subnet_start_ip_addr / parent_subnet_end_ip_addr arrive as 8-char hex strings
  - hostaddr / subnet_start_hostaddr / subnet_end_hostaddr /
    parent_subnet_start_hostaddr / parent_subnet_end_hostaddr arrive as dotted-decimal
  - site_is_template / subnet_is_terminal / lock_network_broadcast / pool_read_only
    are booleans ("0"/"1")
  - site_id / subnet_id / pool_id / parent_subnet_id / parent_vlsm_subnet_id /
    dhcphost_id / dhcplease_id / hostdev_id / hostiface_id use "0" as FK-null (nz_int → None)
  - last_seen / dhcplease_end_time are datetime fields (unix epoch strings)
  - ip_add uses "hostaddr" (not deprecated "ip_addr") for create operations
"""

from datetime import UTC, datetime
from ipaddress import IPv4Address

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.models.address import IpAddress



HOST = "solidserver.example.com"
CREDS = ("admin", "secret")
BASE = "https://solidserver.example.com/"

# ---------------------------------------------------------------------------
# Wire-format fixtures
# Hex IPs (RFC 5737): 192.0.2.x = c0000200 range
#   ip       192.0.2.5    → c0000205
#   pool     192.0.2.10   → c000020a  –  192.0.2.239 → c00002ef
#   subnet   192.0.2.0    → c0000200  –  192.0.2.255 → c00002ff
#   parent   192.0.0.0    → c0000000  –  192.0.255.255 → c000ffff
# ---------------------------------------------------------------------------

_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "type": "ip",
    "free_start_ip_addr": "c0000205",
    "free_end_ip_addr": "c0000205",
    "free_scope_size": "0",
    "ip_id": "1001",
    "ip_addr": "c0000205",
    "hostaddr": "192.0.2.5",
    "name": "web-01",
    "mac_addr": "aa:bb:cc:dd:ee:ff",
    "ip_class_name": "server",
    "ip_class_parameters": "dns_update=1&gateway=192.0.2.254",
    "ip_class_parameters_properties": "dns_update=set,restrict&gateway=inherited,restrict",
    "ip_class_parameters_inheritance_source": "dns_update=real_ip,1001&gateway=real_network,7",
    "ip_alias": "",
    "site_id": "2",
    "site_name": "global",
    "site_description": "Global space",
    "site_is_template": "0",
    "site_class_name": "",
    "site_class_parameters": "dns_id=0",
    "site_class_parameters_properties": "dns_id=set,propagate",
    "tree_level": "0",
    "tree_path": "global#",
    "tree_id_path": "#2#",
    "parent_subnet_id": "42",
    "parent_subnet_name": "corp-block",
    "parent_subnet_size": "65536",
    "parent_vlsm_subnet_id": "0",
    "parent_subnet_class_name": "",
    "parent_subnet_start_ip_addr": "c0000000",
    "parent_subnet_start_hostaddr": "192.0.0.0",
    "parent_subnet_end_ip_addr": "c000ffff",
    "parent_subnet_end_hostaddr": "192.0.255.255",
    "subnet_id": "7",
    "subnet_name": "dmz-servers",
    "subnet_start_ip_addr": "c0000200",
    "subnet_start_hostaddr": "192.0.2.0",
    "subnet_end_ip_addr": "c00002ff",
    "subnet_end_hostaddr": "192.0.2.255",
    "subnet_size": "256",
    "subnet_is_terminal": "1",
    "lock_network_broadcast": "1",
    "subnet_class_name": "production",
    "subnet_class_parameters": "environment=production",
    "subnet_class_parameters_properties": "environment=set,propagate",
    "pool_id": "11",
    "pool_name": "test-pool",
    "pool_read_only": "0",
    "pool_row_enabled": "1",
    "pool_size": "230",
    "pool_start_ip_addr": "c000020a",
    "pool_end_ip_addr": "c00002ef",
    "pool_class_name": "DHCP",
    "pool_class_parameters": "dhcprange=1",
    "pool_class_parameters_properties": "dhcprange=set,propagate",
    "iplnetdev_name": "",
    "iplnetdev_id": "0",
    "iplport_name": "",
    "iplport_slotnumber": "",
    "iplport_portnumber": "",
    "iplport_ifvlan": "",
    "hostdev_name": "#",
    "hostdev_id": "0",
    "hostiface_name": "#",
    "hostiface_id": "0",
    "tag_pool_dhcprange": "0",
    "tag_container_dhcpstatic": "0",
    "dhcphost_id": "0",
    "dhcplease_id": "0",
    "last_seen": "",
    "dhcplease_end_time": "",
    "multistatus": "",
    "trace_creation_date": "1700000000",
    "trace_last_update_date": "1700010000",
    "trace_creation_usr_id": "3",
    "trace_creation_origin_usr_id": "0",
    "trace_creation_origin": "",
    "trace_creation_exec_stack": "",
    "trace_creation_usr_login": "admin",
    "trace_creation_origin_usr_login": "#",
}

# Address with no pool, no parent, DHCP lease
_FREE_ROW: dict[str, str] = {
    **_LIST_ROW,
    "ip_id": "0",
    "type": "free",
    "free_start_ip_addr": "c0000206",
    "free_end_ip_addr": "c0000209",
    "free_scope_size": "4",
    "ip_addr": "c0000206",
    "hostaddr": "192.0.2.6",
    "name": "",
    "mac_addr": "",
    "pool_id": "0",
    "pool_name": "#",
    "parent_subnet_id": "0",
    "dhcphost_id": "99",
    "dhcplease_id": "77",
    "last_seen": "1700005000",
    "dhcplease_end_time": "1700099999",
}

# ---------------------------------------------------------------------------
# Coercion tests — IP addresses
# ---------------------------------------------------------------------------


def test_address_hex_ip_addr() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.ip_addr == IPv4Address("192.0.2.5")


def test_address_dotted_hostaddr() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.hostaddr == IPv4Address("192.0.2.5")


def test_address_hex_free_start_end() -> None:
    a = IpAddress.model_validate(_FREE_ROW)
    assert a.free_start_ip_addr == IPv4Address("192.0.2.6")
    assert a.free_end_ip_addr == IPv4Address("192.0.2.9")


def test_address_hex_pool_ips() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.pool_start_ip_addr == IPv4Address("192.0.2.10")
    assert a.pool_end_ip_addr == IPv4Address("192.0.2.239")


def test_address_hex_subnet_ips() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.subnet_start_ip_addr == IPv4Address("192.0.2.0")
    assert a.subnet_end_ip_addr == IPv4Address("192.0.2.255")


def test_address_dotted_subnet_hostaddrs() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.subnet_start_hostaddr == IPv4Address("192.0.2.0")
    assert a.subnet_end_hostaddr == IPv4Address("192.0.2.255")


def test_address_hex_parent_subnet_ips() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.parent_subnet_start_ip_addr == IPv4Address("192.0.0.0")
    assert a.parent_subnet_end_ip_addr == IPv4Address("192.0.255.255")


def test_address_dotted_parent_subnet_hostaddrs() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.parent_subnet_start_hostaddr == IPv4Address("192.0.0.0")
    assert a.parent_subnet_end_hostaddr == IPv4Address("192.0.255.255")


# ---------------------------------------------------------------------------
# Coercion tests — integer fields
# ---------------------------------------------------------------------------


def test_address_int_fields() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.ip_id == 1001
    assert a.free_scope_size == 0
    assert a.tree_level == 0
    assert a.subnet_size == 256
    assert a.parent_subnet_size == 65536
    assert a.pool_size == 230
    assert a.errno == 0


def test_address_int_free_scope_size() -> None:
    a = IpAddress.model_validate(_FREE_ROW)
    assert a.free_scope_size == 4


def test_address_nz_int_site_id_present() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.site_id == 2


def test_address_nz_int_subnet_id_present() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.subnet_id == 7


def test_address_nz_int_pool_id_present() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.pool_id == 11


def test_address_nz_int_pool_id_absent_when_zero() -> None:
    a = IpAddress.model_validate(_FREE_ROW)
    assert a.pool_id is None


def test_address_nz_int_parent_subnet_present() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.parent_subnet_id == 42


def test_address_nz_int_parent_subnet_absent_when_zero() -> None:
    a = IpAddress.model_validate(_FREE_ROW)
    assert a.parent_subnet_id is None


def test_address_nz_int_parent_vlsm_absent_when_zero() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.parent_vlsm_subnet_id is None


def test_address_nz_int_dhcp_ids_present() -> None:
    a = IpAddress.model_validate(_FREE_ROW)
    assert a.dhcphost_id == 99
    assert a.dhcplease_id == 77


def test_address_nz_int_dhcp_ids_absent_when_zero() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.dhcphost_id is None
    assert a.dhcplease_id is None


def test_address_nz_int_device_ids_absent_when_zero() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.hostdev_id is None
    assert a.hostiface_id is None
    assert a.iplnetdev_id is None


def test_address_nz_int_trace_origin_absent_when_zero() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.trace_creation_origin_usr_id is None


# ---------------------------------------------------------------------------
# Coercion tests — booleans
# ---------------------------------------------------------------------------


def test_address_bool_not_template() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.site_is_template is False


def test_address_bool_is_template() -> None:
    a = IpAddress.model_validate({**_LIST_ROW, "site_is_template": "1"})
    assert a.site_is_template is True


def test_address_bool_subnet_is_terminal() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.subnet_is_terminal is True


def test_address_bool_lock_network_broadcast() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.lock_network_broadcast is True


def test_address_bool_pool_read_only_false() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.pool_read_only is False


def test_address_bool_pool_read_only_true() -> None:
    a = IpAddress.model_validate({**_LIST_ROW, "pool_read_only": "1"})
    assert a.pool_read_only is True


# ---------------------------------------------------------------------------
# Coercion tests — strings
# ---------------------------------------------------------------------------


def test_address_type_field_ip() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.type == "ip"


def test_address_type_field_free() -> None:
    a = IpAddress.model_validate(_FREE_ROW)
    assert a.type == "free"


def test_address_string_sentinel_empty_to_none() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.ip_alias is None          # "" → None
    assert a.multistatus is None       # "" → None
    assert a.site_class_name is None


def test_address_string_sentinel_hash_to_none() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.hostdev_name is None      # "#" → None
    assert a.hostiface_name is None    # "#" → None
    assert a.trace_creation_origin_usr_login is None


def test_address_string_fields_preserved() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.name == "web-01"
    assert a.mac_addr == "aa:bb:cc:dd:ee:ff"
    assert a.subnet_name == "dmz-servers"
    assert a.tree_path == "global#"
    assert a.tree_id_path == "#2#"


def test_address_tag_fields() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.tag_pool_dhcprange == "0"
    assert a.tag_container_dhcpstatic == "0"


# ---------------------------------------------------------------------------
# Coercion tests — datetime fields
# ---------------------------------------------------------------------------


def test_address_trace_creation_date() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.trace_creation_date == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)


def test_address_trace_last_update_date() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.trace_last_update_date is not None
    assert a.trace_last_update_date > a.trace_creation_date  # type: ignore[operator]


def test_address_last_seen_absent_when_empty() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.last_seen is None


def test_address_last_seen_present() -> None:
    a = IpAddress.model_validate(_FREE_ROW)
    assert a.last_seen == datetime.fromtimestamp(1700005000, tz=UTC)


def test_address_dhcplease_end_time_absent_when_empty() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.dhcplease_end_time is None


def test_address_dhcplease_end_time_present() -> None:
    a = IpAddress.model_validate(_FREE_ROW)
    assert a.dhcplease_end_time == datetime.fromtimestamp(1700099999, tz=UTC)


# ---------------------------------------------------------------------------
# Class parameter properties
# ---------------------------------------------------------------------------


def test_address_class_params_values() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.class_params["dns_update"] == "1"
    assert a.class_params["gateway"] == "192.0.2.254"


def test_address_class_params_inheritance() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.class_params.is_set("dns_update")
    assert a.class_params.is_restrict("dns_update")
    assert a.class_params.is_inherited("gateway")


# ---------------------------------------------------------------------------
# model_extra / unknown fields
# ---------------------------------------------------------------------------


def test_address_no_model_extra_on_list_row() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert not a.model_extra


def test_address_unknown_extra_field_captured() -> None:
    row = {**_LIST_ROW, "future_field": "value"}
    a = IpAddress.model_validate(row)
    assert a.model_extra is not None
    assert "future_field" in a.model_extra


def test_address_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert IpAddress._coerce(sentinel) is sentinel


# ---------------------------------------------------------------------------
# write_params / dirty tracking
# ---------------------------------------------------------------------------


def test_address_write_params_name() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    a.name = "renamed"
    assert a.write_params() == {"name": "renamed"}


def test_address_write_params_mac_addr() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    a.mac_addr = "11:22:33:44:55:66"
    assert a.write_params() == {"mac_addr": "11:22:33:44:55:66"}


def test_address_write_params_ip_class_name() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    a.ip_class_name = "workstation"
    assert a.write_params() == {"ip_class_name": "workstation"}


def test_address_write_params_multiple_fields() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    a.name = "db-01"
    a.mac_addr = "de:ad:be:ef:00:01"
    result = a.write_params()
    assert result["name"] == "db-01"
    assert result["mac_addr"] == "de:ad:be:ef:00:01"


def test_address_write_params_none_becomes_empty_string() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    a.name = None
    assert a.write_params() == {"name": ""}


def test_address_not_dirty_initially() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    assert a.write_params() == {}


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------


def test_address_build_request_create_uses_hostaddr() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    verb, path, params = a.build_request("create")
    assert verb == "POST"
    assert path == "rest/ip_add"
    assert params["hostaddr"] == "192.0.2.5"
    assert "ip_addr" not in params           # deprecated param must NOT be sent


def test_address_build_request_create_injects_site_id() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    _, _, params = a.build_request("create")
    assert params["site_id"] == "2"


def test_address_build_request_create_injects_subnet_id_when_present() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    _, _, params = a.build_request("create")
    assert params["subnet_id"] == "7"


def test_address_build_request_create_no_subnet_id_when_absent() -> None:
    a = IpAddress.model_validate({**_LIST_ROW, "subnet_id": "0"})
    _, _, params = a.build_request("create")
    assert "subnet_id" not in params


def test_address_build_request_create_includes_dirty_fields() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    a.name = "new-host"
    _, _, params = a.build_request("create")
    assert params["name"] == "new-host"


def test_address_build_request_create_missing_hostaddr_raises() -> None:
    # hostaddr is a required model field; empty string → None → ValidationError at construction
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        IpAddress.model_validate({**_LIST_ROW, "hostaddr": ""})


def test_address_build_request_create_missing_site_id_raises() -> None:
    # must clear both site_id and site_name to trigger the build_request guard
    a = IpAddress.model_validate({**_LIST_ROW, "site_id": "0", "site_name": ""})
    with pytest.raises(ValueError, match="site_id"):
        a.build_request("create")


def test_address_build_request_update_delegates_to_base() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    a.name = "updated"
    verb, path, params = a.build_request("update")
    assert verb == "PUT"
    assert path == "rest/ip_add"
    assert params["ip_id"] == "1001"
    assert params["name"] == "updated"


def test_address_build_request_delete_delegates_to_base() -> None:
    a = IpAddress.model_validate(_LIST_ROW)
    verb, path, params = a.build_request("delete")
    assert verb == "DELETE"
    assert path == "rest/ip_delete"
    assert params["ip_id"] == "1001"


# ---------------------------------------------------------------------------
# Session / respx API-layer tests
# ---------------------------------------------------------------------------


@respx.mock
def test_address_list_returns_list_of_addresses() -> None:
    respx.get(f"{BASE}rest/ip_address_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW, _FREE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        addresses = s.list(IpAddress)
    assert len(addresses) == 2
    assert all(isinstance(a, IpAddress) for a in addresses)
    assert addresses[0].ip_id == 1001
    assert addresses[0].type == "ip"
    assert addresses[1].type == "free"


@respx.mock
def test_address_info_returns_single_address() -> None:
    respx.get(f"{BASE}rest/ip_address_info").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        a = s.get(IpAddress, 1001)
    assert isinstance(a, IpAddress)
    assert a.ip_id == 1001
    assert a.hostaddr == IPv4Address("192.0.2.5")


@respx.mock
def test_address_list_sends_where_param() -> None:
    route = respx.get(f"{BASE}rest/ip_address_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(IpAddress, where="type='ip'")
    assert route.calls.last.request.url.params["WHERE"] == "type='ip'"


@respx.mock
def test_address_list_sends_limit_param() -> None:
    route = respx.get(f"{BASE}rest/ip_address_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(IpAddress, limit=5)
    assert route.calls.last.request.url.params["limit"] == "5"
