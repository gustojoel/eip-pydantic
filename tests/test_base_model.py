"""Tests for SolidServerModel class-parameter handling."""

from __future__ import annotations

from ipaddress import IPv4Address

import pytest
from pydantic import Field

from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.base import SolidServerConfig, SolidServerModel



class _Site(SolidServerModel):
    _class_param_prefix = "site"
    site_id: str = "1"
    site_name: str = "prod"


class _Scope(SolidServerModel):
    _class_param_prefix = "dhcpscope"


class _PrefixModel(SolidServerModel):
    solid_config = SolidServerConfig(class_param_prefix="prefix")
    class_params: ClassParamDict = Field(default_factory=ClassParamDict.empty)


def test_c_must_be_accessed_on_class() -> None:
    obj = _Site.model_validate({"site_id": "1", "site_name": "prod"})
    with pytest.raises(AttributeError, match="c must be accessed on the class"):
        _ = obj.c


def test_tagged_class_parameters() -> None:
    obj = _Scope.model_validate({
        "dhcpscope_id": "951",
        "dhcpscope_class_parameters": "information=important%20data",
        "tag_dhcpscope_information": "important data",
        "tag_dhcpscope_description": "accounting dept",
    })
    assert obj.tagged_class_parameters == {
        "dhcpscope_information": "important data",
        "dhcpscope_description": "accounting dept",
    }


def test_tagged_class_parameters_empty() -> None:
    obj = _Site.model_validate({"site_id": "1", "site_name": "prod"})
    assert obj.tagged_class_parameters == {}


def test_tagged_class_parameters_empty_no_base_model() -> None:
    obj = SolidServerModel.model_validate({"some_field": "value"})
    assert obj.tagged_class_parameters == {}


# ---------------------------------------------------------------------------
# write_params base implementation
# ---------------------------------------------------------------------------

def test_write_params_base_returns_empty() -> None:
    obj = SolidServerModel.model_validate({})
    assert obj.write_params() == {}


def test_model_post_init_sets_missing_class_param_prefix() -> None:
    obj = _PrefixModel.model_validate({})
    assert obj.class_params.api_prefix == "prefix"


def test_coerce_class_params_noop_when_prefix_is_none() -> None:
    """A model with no class_param_prefix (the base-class default) doesn't
    support class parameters at all, so _coerce_class_params must leave
    out["class_params"] untouched rather than inventing an empty one."""
    out: dict[str, object] = {}
    SolidServerModel._coerce_class_params(out, {})
    assert "class_params" not in out


# ---------------------------------------------------------------------------
# build_class_request / build_request / parse_response / apply_response
# ---------------------------------------------------------------------------

def test_build_class_request_unknown_op_raises() -> None:
    with pytest.raises(ValueError, match="Unknown class operation"):
        SolidServerModel.build_class_request("frobnicate")


def test_build_class_request_list_select_raises() -> None:
    with pytest.raises(ValueError, match="'select' parameter is not supported"):
        SolidServerModel.build_class_request("list", select="site_name")


def test_build_request_info_no_id_raises() -> None:
    obj = SolidServerModel.model_validate({})
    with pytest.raises(ValueError, match="no id"):
        obj.build_request("info")


def test_build_request_update_no_id_raises() -> None:
    obj = SolidServerModel.model_validate({})
    with pytest.raises(ValueError, match="no id"):
        obj.build_request("update")


def test_build_request_delete_no_id_raises() -> None:
    obj = SolidServerModel.model_validate({})
    with pytest.raises(ValueError, match="no id"):
        obj.build_request("delete")


def test_build_request_unknown_op_raises() -> None:
    obj = SolidServerModel.model_validate({})
    with pytest.raises(ValueError, match="Unknown instance operation"):
        obj.build_request("frobnicate")


def test_parse_response_unknown_op_raises() -> None:
    with pytest.raises(ValueError, match="Unknown parse operation"):
        SolidServerModel.parse_response("frobnicate", [])


def test_apply_response_delete_noop() -> None:
    obj = SolidServerModel.model_validate({})
    obj.apply_response("delete", {})  # should not raise or mutate


def test_apply_response_unknown_op_raises() -> None:
    obj = SolidServerModel.model_validate({})
    with pytest.raises(ValueError, match="Unknown apply operation"):
        obj.apply_response("frobnicate", {})


# ---------------------------------------------------------------------------
# Reverse-coercion helpers
# ---------------------------------------------------------------------------

def test_to_bool_str_none() -> None:
    assert SolidServerModel._to_bool_str(None) == ""


# ---------------------------------------------------------------------------
# Forward-coercion error branches
# ---------------------------------------------------------------------------

def test_as_int_invalid_returns_none() -> None:
    assert SolidServerModel._as_int("not-a-number") is None


def test_as_nz_int_invalid_returns_none() -> None:
    assert SolidServerModel._as_nz_int("not-a-number") is None


def test_as_float_invalid_returns_none() -> None:
    assert SolidServerModel._as_float("not-a-float") is None


def test_as_bool_type_error_returns_none() -> None:
    class _BadStr:
        def __str__(self) -> str:
            raise TypeError("bad str")

    assert SolidServerModel._as_bool(_BadStr()) is None


def test_as_hex_ipv4_invalid_returns_none() -> None:
    assert SolidServerModel._as_hex_ipv4("zzzzzzzz") is None


def test_as_dotted_ipv4_invalid_returns_none() -> None:
    assert SolidServerModel._as_dotted_ipv4("999.999.999.999") is None


def test_as_hex_or_dotted_ipv4_none_and_sentinels_return_none() -> None:
    assert SolidServerModel._as_hex_or_dotted_ipv4(None) is None
    assert SolidServerModel._as_hex_or_dotted_ipv4("") is None
    assert SolidServerModel._as_hex_or_dotted_ipv4("#") is None


def test_as_hex_or_dotted_ipv4_passes_through_ipv4address() -> None:
    addr = IPv4Address("10.0.0.1")
    assert SolidServerModel._as_hex_or_dotted_ipv4(addr) is addr


def test_as_hex_or_dotted_ipv4_detects_hex() -> None:
    assert SolidServerModel._as_hex_or_dotted_ipv4("0a541400") == IPv4Address("10.84.20.0")


def test_as_hex_or_dotted_ipv4_detects_dotted() -> None:
    assert SolidServerModel._as_hex_or_dotted_ipv4("10.84.20.0") == IPv4Address("10.84.20.0")


def test_as_hex_or_dotted_ipv4_invalid_returns_none() -> None:
    assert SolidServerModel._as_hex_or_dotted_ipv4("not-an-address") is None


def test_as_datetime_invalid_returns_none() -> None:
    assert SolidServerModel._as_datetime("not-a-timestamp") is None


# ---------------------------------------------------------------------------
# ClassParamDict field <-> Pydantic (de)serialisation
# ---------------------------------------------------------------------------

def test_model_dump_json_does_not_raise() -> None:
    obj = _PrefixModel.model_validate({"class_params": {"a": "1"}})
    obj.model_dump_json()


def test_model_dump_python_mode_returns_class_param_dict_unchanged() -> None:
    obj = _PrefixModel.model_validate({})
    dumped = obj.model_dump()
    assert dumped["class_params"] is obj.class_params


def test_model_dump_json_round_trips_inheritance_propagation_and_sources() -> None:
    obj = _PrefixModel.model_validate({
        "class_params": ClassParamDict.from_blobs(
            params_blob="a=1&b=2",
            props_blob="a=set,restrict&b=inherited,propagate",
            sources_blob="b=real_site,7",
            api_prefix="prefix",
        ),
    })

    restored = _PrefixModel.model_validate_json(obj.model_dump_json())

    assert dict(restored.class_params.items()) == dict(obj.class_params.items())
    assert restored.class_params.is_set("a")
    assert restored.class_params.is_restrict("a")
    assert restored.class_params.is_inherited("b")
    assert restored.class_params.is_propagate("b")
    assert restored.class_params.source("b") == obj.class_params.source("b")


def test_model_dump_json_drops_pending_deletes() -> None:
    """A flush is presumed to have already reconciled staged deletions, so the
    restored object has no memory of 'a' being pending deletion — it's simply
    absent, same as if it had never been staged."""
    obj = _PrefixModel.model_validate({
        "class_params": ClassParamDict.from_blobs(params_blob="a=1&b=2", props_blob=None, api_prefix="prefix"),
    })
    del obj.class_params["a"]

    restored = _PrefixModel.model_validate_json(obj.model_dump_json())

    assert restored.class_params.deleted == frozenset()
    assert "a" not in restored.class_params
    assert "b" in restored.class_params


def test_model_validate_plain_dict_class_params_still_works() -> None:
    obj = _PrefixModel.model_validate({"class_params": {"k": "v"}})
    assert obj.class_params["k"] == "v"
    assert obj.class_params.is_inherited_or_set("k")


def test_model_validate_json_invalid_inheritance_mode_raises_validation_error() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Invalid inheritance mode"):
        _PrefixModel.model_validate_json(
            '{"class_params": {"a": "1", "$propagation": {"a": "bogus,propagate"}}}',
        )
