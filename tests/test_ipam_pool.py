"""Unit tests for the Pool model and ip_pool_* API methods.

Wire-format fixtures use RFC 5737 address ranges (192.0.2.x) and are based on
the actual ip_pool_list / ip_pool_info response shape observed against a live server.

Key coercion facts verified here:
  - start_ip_addr / end_ip_addr / subnet_start_ip_addr / subnet_end_ip_addr arrive as 8-char hex strings
    (pool_start_ip_addr / pool_end_ip_addr / start_hostaddr / end_hostaddr are consumed and dropped)
  - pool_size is derived from start_ip_addr + end_ip_addr when missing, and vice-versa
  - pool_read_only is a boolean (bool coercion: "0"/"1")
  - row_enabled is a RowEnabled int enum ("0"/"1"/"2")
  - parent_subnet_id / vlsm_subnet_id / vlsm_block_id use "0" as FK-null sentinel (nz_int → None)
  - subnet_class_parameters / subnet_class_parameters_properties are info-only fields
"""

from ipaddress import IPv4Address

import httpx
import pytest
import respx

from eip_pydantic import Session
from eip_pydantic.models.base import RowEnabled
from eip_pydantic.models.pool import Pool



HOST = "solidserver.example.com"
CREDS = ("admin", "secret")
BASE = "https://solidserver.example.com/"

# ---------------------------------------------------------------------------
# Wire-format fixtures
# Hex IPs (RFC 5737): 192.0.2.x = c0000200 range
#   pool start 192.0.2.10  → c000020a
#   pool end   192.0.2.239 → c00002ef
#   subnet     192.0.2.0   → c0000200 – 192.0.2.255 → c00002ff
#   parent     192.0.0.0   → c0000000 – 192.0.255.255 → c000ffff
# ---------------------------------------------------------------------------

_LIST_ROW: dict[str, str] = {
    "errno": "0",
    "pool_id": "11",
    "pool_name": "test-pool",
    "pool_read_only": "0",
    "start_ip_addr": "c000020a",
    "start_hostaddr": "192.0.2.10",
    "end_ip_addr": "c00002ef",
    "end_hostaddr": "192.0.2.239",
    "pool_start_ip_addr": "c000020a",
    "pool_end_ip_addr": "c00002ef",
    "pool_size": "230",
    "pool_class_name": "DHCP",
    "pool_class_parameters": "dhcprange=1&gateway=192.0.2.254",
    "pool_class_parameters_properties": "dhcprange=set,propagate&gateway=set,propagate",
    "pool_class_parameters_inheritance_source": "dhcprange=real_pool,11&gateway=real_network,7",
    "parent_subnet_id": "42",
    "parent_subnet_name": "corp-block",
    "parent_subnet_size": "65536",
    "parent_subnet_class_name": "",
    "vlsm_subnet_id": "0",
    "vlsm_block_id": "0",
    "subnet_id": "7",
    "subnet_name": "dmz-servers",
    "subnet_start_ip_addr": "c0000200",
    "subnet_end_ip_addr": "c00002ff",
    "subnet_size": "256",
    "subnet_class_name": "production",
    "site_id": "2",
    "site_name": "global",
    "site_description": "Global space",
    "site_is_template": "0",
    "site_class_name": "",
    "site_class_parameters": "",
    "site_class_parameters_properties": "",
    "tree_path": "global#",
    "row_enabled": "1",
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

# ip_pool_info adds subnet class-param blobs (absent from ip_pool_list)
_INFO_ROW: dict[str, str] = {
    **_LIST_ROW,
    "subnet_class_parameters": "environment=production&owner=ops",
    "subnet_class_parameters_properties": "environment=set,propagate&owner=set,propagate",
}

_READONLY_ROW: dict[str, str] = {
    **_LIST_ROW,
    "pool_id": "22",
    "pool_read_only": "1",
    "row_enabled": "2",
}

_NO_PARENT_ROW: dict[str, str] = {
    **_LIST_ROW,
    "parent_subnet_id": "0",
    "parent_subnet_name": "#",
    "parent_subnet_size": "0",
}

# ---------------------------------------------------------------------------
# Coercion tests
# ---------------------------------------------------------------------------


def test_pool_hex_ip_start() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.start_ip_addr == IPv4Address("192.0.2.10")


def test_pool_hex_ip_end() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.end_ip_addr == IPv4Address("192.0.2.239")


def test_pool_hex_ip_subnet_start() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.subnet_start_ip_addr == IPv4Address("192.0.2.0")


def test_pool_hex_ip_subnet_end() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.subnet_end_ip_addr == IPv4Address("192.0.2.255")


def test_pool_pool_size_derived_from_start_and_end() -> None:
    # pool_size can be computed from start + end when absent in wire data
    row = {k: v for k, v in _LIST_ROW.items() if k != "pool_size"}
    p = Pool.model_validate(row)
    assert p.pool_size == 230  # int("c00002ef") - int("c000020a") + 1


def test_pool_end_ip_derived_from_start_and_size() -> None:
    # end_ip_addr can be computed from start + pool_size when absent in wire data
    row = {k: v for k, v in _LIST_ROW.items() if k != "end_ip_addr"}
    p = Pool.model_validate(row)
    assert p.end_ip_addr == IPv4Address("192.0.2.239")


def test_pool_int_fields() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.pool_id == 11
    assert p.pool_size == 230
    assert p.subnet_size == 256
    assert p.parent_subnet_size == 65536
    assert p.errno == 0


def test_pool_nz_int_subnet_id_present() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.subnet_id == 7


def test_pool_nz_int_parent_subnet_id_present() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.parent_subnet_id == 42


def test_pool_nz_int_parent_subnet_absent_when_zero() -> None:
    p = Pool.model_validate(_NO_PARENT_ROW)
    assert p.parent_subnet_id is None


def test_pool_nz_int_vlsm_ids_absent_when_zero() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.vlsm_subnet_id is None
    assert p.vlsm_block_id is None


def test_pool_nz_int_trace_origin_absent_when_zero() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.trace_creation_origin_usr_id is None


def test_pool_bool_read_only_false() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.pool_read_only is False


def test_pool_bool_read_only_true() -> None:
    p = Pool.model_validate(_READONLY_ROW)
    assert p.pool_read_only is True


def test_pool_bool_site_not_template() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.site_is_template is False


def test_pool_bool_site_is_template() -> None:
    p = Pool.model_validate({**_LIST_ROW, "site_is_template": "1"})
    assert p.site_is_template is True


def test_pool_row_enabled_enabled() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.row_enabled == RowEnabled.ENABLED


def test_pool_row_enabled_unmanaged() -> None:
    p = Pool.model_validate(_READONLY_ROW)
    assert p.row_enabled == RowEnabled.UNMANAGED


def test_pool_row_enabled_deleted() -> None:
    p = Pool.model_validate({**_LIST_ROW, "row_enabled": "0"})
    assert p.row_enabled == RowEnabled.DELETED


def test_pool_string_sentinel_empty_to_none() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.site_class_name is None       # "" → None
    assert p.multistatus is None           # "" → None
    assert p.parent_subnet_class_name is None


def test_pool_string_sentinel_hash_to_none() -> None:
    p = Pool.model_validate(_NO_PARENT_ROW)
    assert p.parent_subnet_name is None    # "#" → None
    assert p.trace_creation_origin_usr_login is None


def test_pool_string_fields_preserved() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.pool_name == "test-pool"
    assert p.subnet_name == "dmz-servers"
    assert p.site_name == "global"
    assert p.tree_path == "global#"


def test_pool_class_params_values() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.class_params["dhcprange"] == "1"
    assert p.class_params["gateway"] == "192.0.2.254"


def test_pool_class_params_inheritance() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.class_params.is_set("dhcprange")
    assert p.class_params.is_propagate("dhcprange")


def test_pool_class_params_sources() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.class_params.source("dhcprange") == ("real_pool", "11")
    assert p.class_params.source("gateway") == ("real_network", "7")


def test_pool_info_subnet_class_params_present() -> None:
    p = Pool.model_validate(_INFO_ROW)
    assert p.subnet_class_params is not None
    assert p.subnet_class_params["environment"] == "production"
    assert p.subnet_class_params["owner"] == "ops"


def test_pool_info_subnet_class_params_absent_in_list() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.subnet_class_params is None


def test_pool_no_model_extra_on_list_row() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert not p.model_extra


def test_pool_no_model_extra_on_info_row() -> None:
    p = Pool.model_validate(_INFO_ROW)
    assert not p.model_extra


def test_pool_coerce_non_dict_passthrough() -> None:
    sentinel = object()
    assert Pool._coerce(sentinel) is sentinel


def test_pool_unknown_extra_is_preserved() -> None:
    p = Pool.model_validate({**_LIST_ROW, "custom_marker": "keep-me"})
    assert p.model_extra is not None
    assert p.model_extra["custom_marker"] == "keep-me"


# ---------------------------------------------------------------------------
# write_params / dirty tracking
# ---------------------------------------------------------------------------


def test_pool_write_params_pool_name() -> None:
    p = Pool.model_validate(_LIST_ROW)
    p.pool_name = "renamed"
    assert p.write_params() == {"pool_name": "renamed"}


def test_pool_write_params_pool_read_only_true() -> None:
    p = Pool.model_validate(_LIST_ROW)
    p.pool_read_only = True
    assert p.write_params() == {"pool_read_only": "1"}


def test_pool_write_params_pool_read_only_false() -> None:
    p = Pool.model_validate(_LIST_ROW)
    p.pool_read_only = True
    p.pool_read_only = False
    assert p.write_params() == {"pool_read_only": "0"}


def test_pool_write_params_row_enabled() -> None:
    p = Pool.model_validate(_LIST_ROW)
    p.row_enabled = RowEnabled.UNMANAGED
    assert p.write_params() == {"row_enabled": "2"}


def test_pool_write_params_class_params() -> None:
    p = Pool.model_validate(_LIST_ROW)
    p.pool_class_name = "new-class"
    p.class_params["key"] = "val"
    result = p.write_params()
    assert result["pool_class_name"] == "new-class"
    assert "key=val" in result["pool_class_parameters"]


def test_pool_write_params_none_value_becomes_empty_string() -> None:
    p = Pool.model_validate(_LIST_ROW)
    p.pool_class_name = None
    assert p.write_params() == {"pool_class_name": ""}


def test_pool_write_params_ignores_address_range_fields_when_dirty_manually() -> None:
    p = Pool.model_validate(_LIST_ROW)
    p._dirty.update({"start_ip_addr", "end_ip_addr", "pool_size"})
    assert p.write_params() == {}


def test_pool_not_dirty_initially() -> None:
    p = Pool.model_validate(_LIST_ROW)
    assert p.write_params() == {}


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------


def test_pool_build_request_create_injects_addresses() -> None:
    p = Pool.model_validate(_LIST_ROW)
    verb, path, params = p.build_request("create")
    assert verb == "POST"
    assert path == "rest/ip_pool_add"
    assert params["start_addr"] == "192.0.2.10"
    assert params["end_addr"] == "192.0.2.239"
    assert params["subnet_id"] == "7"


def test_pool_build_request_create_includes_dirty_fields() -> None:
    p = Pool.model_validate(_LIST_ROW)
    p.pool_name = "new-pool"
    _, _, params = p.build_request("create")
    assert params["pool_name"] == "new-pool"


def test_pool_build_request_create_missing_start_raises() -> None:
    # start_ip_addr is a required model field; construction fails when absent
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Pool.model_validate({k: v for k, v in _LIST_ROW.items() if k != "start_ip_addr"})


def test_pool_build_request_create_missing_end_raises() -> None:
    # end_ip_addr must either be in the data or derivable from pool_size + start_ip_addr;
    # absent both → ValidationError on the required field
    from pydantic import ValidationError
    row = {k: v for k, v in _LIST_ROW.items() if k not in ("end_ip_addr", "pool_size")}
    with pytest.raises(ValidationError):
        Pool.model_validate(row)


def test_pool_build_request_create_missing_identifier_raises() -> None:
    # site_id / site_name / subnet_id: all three absent → ValueError from build_request
    p = Pool.model_validate({**_LIST_ROW, "subnet_id": "0", "site_id": "0", "site_name": ""})
    with pytest.raises(ValueError, match="site_id"):
        p.build_request("create")


def test_pool_build_request_update_delegates_to_base() -> None:
    p = Pool.model_validate(_LIST_ROW)
    p.pool_name = "updated"
    verb, path, params = p.build_request("update")
    assert verb == "PUT"
    assert path == "rest/ip_pool_add"
    assert params["pool_id"] == "11"
    assert params["pool_name"] == "updated"


def test_pool_build_request_delete_delegates_to_base() -> None:
    p = Pool.model_validate(_LIST_ROW)
    verb, path, params = p.build_request("delete")
    assert verb == "DELETE"
    assert path == "rest/ip_pool_delete"
    assert params["pool_id"] == "11"


# ---------------------------------------------------------------------------
# Session / respx API-layer tests
# ---------------------------------------------------------------------------


@respx.mock
def test_pool_list_returns_list_of_pools() -> None:
    respx.get(f"{BASE}rest/ip_pool_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW, _READONLY_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        pools = s.list(Pool)
    assert len(pools) == 2
    assert all(isinstance(p, Pool) for p in pools)
    assert pools[0].pool_id == 11
    assert pools[1].pool_id == 22


@respx.mock
def test_pool_info_returns_single_pool() -> None:
    respx.get(f"{BASE}rest/ip_pool_info").mock(
        return_value=httpx.Response(200, json=[_INFO_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        p = s.get(Pool, 11)
    assert isinstance(p, Pool)
    assert p.pool_id == 11
    assert p.subnet_class_params is not None
    assert p.subnet_class_params["environment"] == "production"


@respx.mock
def test_pool_list_sends_where_param() -> None:
    route = respx.get(f"{BASE}rest/ip_pool_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Pool, where="subnet_id='7'")
    assert route.calls.last.request.url.params["WHERE"] == "subnet_id='7'"


@respx.mock
def test_pool_list_sends_limit_param() -> None:
    route = respx.get(f"{BASE}rest/ip_pool_list").mock(
        return_value=httpx.Response(200, json=[_LIST_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        s.list(Pool, limit=10)
    assert route.calls.last.request.url.params["limit"] == "10"
