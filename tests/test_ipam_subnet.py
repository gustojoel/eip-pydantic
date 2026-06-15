"""Unit tests for the Subnet model and ipam.subnet_* API methods.

Wire-format fixtures are based on real ip_block_subnet_list / ip_block_subnet_info
responses with names, IDs and IP addresses anonymised (RFC 5737 test ranges).

Key coercion facts verified here:
  - start_ip_addr / end_ip_addr arrive as 8-char hex strings
  - start_hostaddr / end_hostaddr arrive as dotted-decimal strings
  - subnet_level "0" means block-type (not null) — plain int, NOT NzInt
  - parent_subnet_id "0" means no parent — NzInt → None
  - vlmdomain_id / vlmvlan_id etc. use "0" as FK null — NzInt → None
  - site_class_parameters and parent_subnet_class_parameters are _info-only
"""

from datetime import UTC, datetime
from ipaddress import IPv4Address

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.subnet import Subnet



HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

BASE = "https://solidserver.example.com/"

# ---------------------------------------------------------------------------
# Wire-format fixtures
# ---------------------------------------------------------------------------

# /24 subnet (256 addresses) within space 7, no parent block
_SUBNET_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "subnet_id": "42",
    "type": "subnet",
    "subnet_name": "dmz-servers",
    "subnet_level": "1",
    "subnet_path": "global > dmz-servers",
    # start 10.0.2.0  →  hex "0a000200"
    "start_ip_addr": "0a000200",
    "start_hostaddr": "10.0.2.0",
    # end 10.0.2.255  →  hex "0a0002ff"
    "end_ip_addr": "0a0002ff",
    "end_hostaddr": "10.0.2.255",
    "subnet_size": "256",
    "subnet_is_valid": "1",
    "row_enabled": "1",
    "is_terminal": "1",
    "is_in_orphan": "0",
    "lock_network_broadcast": "0",
    "waiting_state": "",
    "waiting_status": "0",
    "multistatus": "",
    "subnet_allocated_size": "64",
    "subnet_allocated_percent": "25.0",
    "subnet_used_size": "16",
    "subnet_used_percent": "6.25",
    "subnet_ip_used_size": "14",
    "subnet_ip_used_percent": "5.47",
    "subnet_ip_free_size": "240",
    "subnet_class_name": "",
    "subnet_class_parameters": "environment=production&owner=ops",
    "subnet_class_parameters_properties": "environment=set,propagate&owner=set,propagate",
    "subnet_class_parameters_inheritance_source": "environment=real_site,7&owner=real_site,7",
    "site_id": "7",
    "site_name": "global",
    "site_description": "Global address space",
    "site_is_template": "0",
    "site_class_name": "",
    "site_parent_site_id": "0",
    "tree_level": "1",
    "tree_path": "global#",
    "tree_id_path": "#7#42#",
    # no parent block
    "parent_subnet_id": "0",
    "parent_subnet_name": "#",
    "parent_start_ip_addr": "00000000",
    "parent_end_ip_addr": "00000000",
    "parent_subnet_size": "0",
    "parent_subnet_level": "0",
    "parent_subnet_path": "#",
    "parent_subnet_class_name": "#",
    "parent_is_terminal": "0",
    "parent_vlsm_subnet_id": "0",
    "parent_site_id": "7",
    "parent_site_name": "#",
    # no VLSM cross-link
    "vlsm_block_id": "0",
    "vlsm_subnet_id": "0",
    "vlsm_site_id": "0",
    "vlsm_site_name": "#",
    # no VLAN association
    "vlmvlan_id": "0",
    "vlmvlan_vlan_id": "0",
    "vlmvlan_name": "#",
    "vlmdomain_id": "0",
    "vlmdomain_name": "#",
    "vlmrange_id": "0",
    "vlmrange_name": "#",
    # audit trail
    "trace_creation_date": "1700000000",
    "trace_last_update_date": "1700010000",
    "trace_creation_usr_id": "3",
    "trace_creation_origin_usr_id": "0",
    "trace_creation_origin": "",
    "trace_creation_exec_stack": "",
    "trace_creation_usr_login": "admin",
    "trace_creation_origin_usr_login": "#",
}

# ip_block_subnet_info adds site and parent class-param blobs
_SUBNET_INFO_ROW: dict[str, str] = {
    **_SUBNET_LIST_ROW,
    "site_class_parameters": "dns_id=0&rev_dns_id=0",
    "site_class_parameters_properties": "dns_id=set,propagate&rev_dns_id=set,propagate",
    "parent_subnet_class_parameters": "",
    "parent_subnet_class_parameters_properties": "",
}

# Block-type network: subnet_level=0, no parent, type="block"
_BLOCK_LIST_ROW: dict[str, str] = {
    **_SUBNET_LIST_ROW,
    "subnet_id": "10",
    "type": "block",
    "subnet_name": "corp-block",
    "subnet_level": "0",
    # start 10.0.0.0 → "0a000000"
    "start_ip_addr": "0a000000",
    "start_hostaddr": "10.0.0.0",
    # end 10.0.255.255 → "0a00ffff"
    "end_ip_addr": "0a00ffff",
    "end_hostaddr": "10.0.255.255",
    "subnet_size": "65536",
    "is_terminal": "0",
    "parent_subnet_id": "0",
}

# Subnet with VLAN association
_VLAN_SUBNET_ROW: dict[str, str] = {
    **_SUBNET_LIST_ROW,
    "subnet_id": "55",
    "subnet_name": "vlan100-user",
    "vlmvlan_id": "8",
    "vlmvlan_vlan_id": "100",
    "vlmvlan_name": "user-vlan",
    "vlmdomain_id": "3",
    "vlmdomain_name": "core-domain",
    "vlmrange_id": "2",
    "vlmrange_name": "user-range",
}

# Subnet with a parent block
_CHILD_SUBNET_ROW: dict[str, str] = {
    **_SUBNET_LIST_ROW,
    "subnet_id": "43",
    "subnet_name": "dmz-mgmt",
    "subnet_level": "2",
    "parent_subnet_id": "10",
    "parent_subnet_name": "corp-block",
    "parent_start_ip_addr": "0a000000",
    "parent_end_ip_addr": "0a00ffff",
    "parent_subnet_size": "65536",
    "parent_subnet_level": "0",
}

# ---------------------------------------------------------------------------
# IP address coercion — hex-encoded fields (start_ip_addr, end_ip_addr, parent_*)
# ---------------------------------------------------------------------------


def test_subnet_hex_ip_start() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.start_ip_addr == IPv4Address("10.0.2.0")


def test_subnet_hex_ip_end() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.end_ip_addr == IPv4Address("10.0.2.255")


def test_subnet_hex_ip_parent_start() -> None:
    s = Subnet.model_validate(_CHILD_SUBNET_ROW)
    assert s.parent_start_ip_addr == IPv4Address("10.0.0.0")


def test_subnet_hex_ip_parent_end() -> None:
    s = Subnet.model_validate(_CHILD_SUBNET_ROW)
    assert s.parent_end_ip_addr == IPv4Address("10.0.255.255")


def test_subnet_hex_ip_all_zeros_is_zero_address() -> None:
    # "00000000" decodes to 0.0.0.0 — valid address, not None
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.parent_start_ip_addr == IPv4Address("0.0.0.0")


def test_subnet_hex_ip_8char_dotted_not_confused() -> None:
    # "10.0.2.0" is 8 chars — must NOT be parsed as hex; uses dotted-decimal path
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.start_hostaddr == IPv4Address("10.0.2.0")


# ---------------------------------------------------------------------------
# IP address coercion — dotted-decimal fields (start_hostaddr, end_hostaddr)
# ---------------------------------------------------------------------------


def test_subnet_dotted_ip_start_hostaddr() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.start_hostaddr == IPv4Address("10.0.2.0")


def test_subnet_dotted_ip_end_hostaddr() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.end_hostaddr == IPv4Address("10.0.2.255")


# ---------------------------------------------------------------------------
# Integer and NzInt coercion
# ---------------------------------------------------------------------------


def test_subnet_level_zero_is_int_not_none() -> None:
    # subnet_level=0 means "block type" — must NOT be treated as FK null
    s = Subnet.model_validate(_BLOCK_LIST_ROW)
    assert s.subnet_level == 0


def test_subnet_level_nonzero() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.subnet_level == 1


def test_subnet_parent_id_zero_becomes_none() -> None:
    # parent_subnet_id uses NzInt: "0" → None
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.parent_subnet_id is None


def test_subnet_parent_id_nonzero_preserved() -> None:
    s = Subnet.model_validate(_CHILD_SUBNET_ROW)
    assert s.parent_subnet_id == 10


def test_subnet_vlmdomain_id_zero_is_none() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.vlmdomain_id is None


def test_subnet_vlmvlan_id_nonzero_preserved() -> None:
    s = Subnet.model_validate(_VLAN_SUBNET_ROW)
    assert s.vlmvlan_id == 8
    assert s.vlmvlan_vlan_id == 100
    assert s.vlmdomain_id == 3
    assert s.vlmrange_id == 2


def test_subnet_site_id_plain_int() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.site_id == 7


def test_subnet_size_int() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.subnet_size == 256


def test_subnet_errno_zero() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.errno == 0


def test_subnet_trace_usr_id_nonzero() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.trace_creation_usr_id == 3


def test_subnet_trace_origin_usr_id_zero_is_none() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.trace_creation_origin_usr_id is None


# ---------------------------------------------------------------------------
# Float coercion
# ---------------------------------------------------------------------------


def test_subnet_allocated_percent() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.subnet_allocated_percent == 25.0


def test_subnet_used_percent() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.subnet_used_percent == pytest.approx(6.25)


def test_subnet_ip_used_percent() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.subnet_ip_used_percent == pytest.approx(5.47)


# ---------------------------------------------------------------------------
# Bool coercion
# ---------------------------------------------------------------------------


def test_subnet_is_terminal_true() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.is_terminal is True


def test_subnet_is_terminal_false() -> None:
    s = Subnet.model_validate(_BLOCK_LIST_ROW)
    assert s.is_terminal is False


def test_subnet_is_in_orphan_false() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.is_in_orphan is False


def test_subnet_is_valid_true() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.subnet_is_valid is True


# ---------------------------------------------------------------------------
# RowEnabled enum
# ---------------------------------------------------------------------------


def test_subnet_row_enabled_enabled() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.row_enabled == RowEnabled.ENABLED


def test_subnet_row_enabled_deleted() -> None:
    s = Subnet.model_validate({**_SUBNET_LIST_ROW, "row_enabled": "0"})
    assert s.row_enabled == RowEnabled.DELETED


def test_subnet_row_enabled_unmanaged() -> None:
    s = Subnet.model_validate({**_SUBNET_LIST_ROW, "row_enabled": "2"})
    assert s.row_enabled == RowEnabled.UNMANAGED


# ---------------------------------------------------------------------------
# Datetime coercion
# ---------------------------------------------------------------------------


def test_subnet_trace_creation_date() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    expected = datetime.fromtimestamp(1700000000, tz=UTC)
    assert s.trace_creation_date == expected


def test_subnet_trace_last_update_date() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    expected = datetime.fromtimestamp(1700010000, tz=UTC)
    assert s.trace_last_update_date == expected


# ---------------------------------------------------------------------------
# String sentinel stripping
# ---------------------------------------------------------------------------


def test_subnet_empty_string_to_none() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.subnet_class_name is None      # "" → None
    assert s.waiting_state is None          # "" → None
    assert s.trace_creation_origin is None  # "" → None


def test_subnet_hash_sentinel_to_none() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.parent_subnet_name is None     # "#" → None
    assert s.vlsm_site_name is None         # "#" → None
    assert s.vlmdomain_name is None         # "#" → None


def test_subnet_string_fields_preserved() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.subnet_name == "dmz-servers"
    assert s.site_name == "global"
    assert s.trace_creation_usr_login == "admin"


# ---------------------------------------------------------------------------
# Info-only fields
# ---------------------------------------------------------------------------


def test_subnet_info_site_class_parameters_present() -> None:
    s = Subnet.model_validate(_SUBNET_INFO_ROW)
    assert s.site_class_parameters is not None
    assert s.site_class_parameters.startswith("dns_id=")


def test_subnet_info_parent_class_parameters_empty_string_to_none() -> None:
    s = Subnet.model_validate(_SUBNET_INFO_ROW)
    assert s.parent_subnet_class_parameters is None  # "" → None


def test_subnet_list_row_has_no_info_only_fields() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.site_class_parameters is None
    assert s.parent_subnet_class_parameters is None


# ---------------------------------------------------------------------------
# Class parameters
# ---------------------------------------------------------------------------


def test_subnet_class_parameters_property() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.class_parameters == {"environment": "production", "owner": "ops"}


def test_subnet_class_parameters_properties_property() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.class_parameters_properties == {
        "environment": ("set", "propagate"),
        "owner": ("set", "propagate"),
    }


def test_subnet_class_parameters_inheritance_source_property() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert s.class_parameters_inheritance_source == {
        "environment": ("real_site", "7"),
        "owner": ("real_site", "7"),
    }


# ---------------------------------------------------------------------------
# model_extra passthrough
# ---------------------------------------------------------------------------


def test_subnet_tag_fields_pass_through() -> None:
    row = {**_SUBNET_LIST_ROW, "tag_network_owner": "netops", "tag_network_env": "prod"}
    s = Subnet.model_validate(row)
    assert s.tagged_class_parameters == {
        "network_owner": "netops",
        "network_env": "prod",
    }


def test_subnet_no_model_extra_on_clean_list_row() -> None:
    s = Subnet.model_validate(_SUBNET_LIST_ROW)
    assert not s.model_extra


def test_subnet_no_model_extra_on_info_row() -> None:
    s = Subnet.model_validate(_SUBNET_INFO_ROW)
    assert not s.model_extra


# ---------------------------------------------------------------------------
# API-layer tests (respx)
# ---------------------------------------------------------------------------


@respx.mock
def test_subnet_list_returns_list_of_subnets() -> None:
    respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_LIST_ROW, _BLOCK_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        subnets = s.list(Subnet)
    assert len(subnets) == 2
    assert all(isinstance(sn, Subnet) for sn in subnets)
    assert subnets[0].subnet_id == 42
    assert subnets[1].subnet_id == 10


@respx.mock
def test_subnet_info_returns_single_subnet() -> None:
    respx.get(f"{BASE}rest/ip_block_subnet_info").mock(
        return_value=httpx.Response(200, json=[_SUBNET_INFO_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        sn = s.get(Subnet, 42)
    assert isinstance(sn, Subnet)
    assert sn.subnet_id == 42
    assert sn.site_class_parameters is not None


@respx.mock
def test_subnet_list_sends_where_param() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Subnet, where="site_id='7'")
    assert route.calls.last.request.url.params["WHERE"] == "site_id='7'"


@respx.mock
def test_subnet_list_sends_limit_and_orderby() -> None:
    route = respx.get(f"{BASE}rest/ip_block_subnet_list").mock(
        return_value=httpx.Response(200, json=[_SUBNET_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Subnet, limit=10, orderby="start_ip_addr ASC")
    params = route.calls.last.request.url.params
    assert params["limit"] == "10"
    assert params["ORDERBY"] == "start_ip_addr ASC"


def test_subnet_build_request_create_missing_fields_raises() -> None:
    sn = Subnet.model_validate({"subnet_id": "42"})
    with pytest.raises(ValueError, match="start_hostaddr"):
        sn.build_request("create")


def test_subnet_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert Subnet._coerce(sentinel) is sentinel
