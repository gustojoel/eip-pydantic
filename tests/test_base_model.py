"""Tests for SolidServerModel class-parameter handling."""

from __future__ import annotations

import pytest

from eip_pydantic.models.base import SolidServerModel



class _Site(SolidServerModel):
    _class_param_prefix = "site"
    site_id: str = "1"
    site_name: str = "prod"


class _Scope(SolidServerModel):
    _class_param_prefix = "dhcpscope"


def test_class_parameters_declared_field() -> None:
    obj = _Site.model_validate({
        "site_id": "1",
        "site_name": "prod",
        "site_class_parameters": "env=production&owner=ops%20team",
    })
    assert obj.class_parameters == {"env": "production", "owner": "ops team"}


def test_class_parameters_as_extra_field() -> None:
    # class_parameters arrives but is not declared on the model
    obj = _Scope.model_validate({
        "dhcpscope_id": "951",
        "dhcpscope_class_parameters": "ipam_replication=0&information=important%20data",
    })
    assert obj.class_parameters == {"ipam_replication": "0", "information": "important data"}


def test_class_parameters_empty() -> None:
    obj = _Site.model_validate({"site_id": "1", "site_name": "prod"})
    assert obj.class_parameters == {}


def test_class_parameters_properties() -> None:
    obj = _Scope.model_validate({
        "dhcpscope_class_parameters_properties": "ipam_replication=set,propagate&information=inherited",
    })
    assert obj.class_parameters_properties == {
        "ipam_replication": ("set", "propagate"),
        "information": ("inherited",),
    }


def test_class_parameters_inheritance_source() -> None:
    obj = _Scope.model_validate({
        "dhcpscope_class_parameters_inheritance_source": (
            "ipam_replication=real_dhcp,19&information=real_dhcpscope,951"
        ),
    })
    assert obj.class_parameters_inheritance_source == {
        "ipam_replication": ("real_dhcp", "19"),
        "information": ("real_dhcpscope", "951"),
    }


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


def test_no_prefix_returns_empty_dicts() -> None:
    obj = SolidServerModel.model_validate({"some_field": "value"})
    assert obj.class_parameters == {}
    assert obj.class_parameters_properties == {}
    assert obj.class_parameters_inheritance_source == {}
    assert obj.tagged_class_parameters == {}


def test_class_parameters_properties_empty_when_field_absent() -> None:
    obj = _Site.model_validate({"site_id": "1", "site_name": "prod"})
    assert obj.class_parameters_properties == {}


def test_class_parameters_inheritance_source_empty_when_field_absent() -> None:
    obj = _Site.model_validate({"site_id": "1", "site_name": "prod"})
    assert obj.class_parameters_inheritance_source == {}


# ---------------------------------------------------------------------------
# set/delete class parameter — no-prefix guard
# ---------------------------------------------------------------------------

def test_set_class_parameter_no_prefix_raises() -> None:
    obj = SolidServerModel.model_validate({})
    with pytest.raises(TypeError, match="no class parameter prefix"):
        obj.set_class_parameter("key", "val")


def test_delete_class_parameter_no_prefix_raises() -> None:
    obj = SolidServerModel.model_validate({})
    with pytest.raises(TypeError, match="no class parameter prefix"):
        obj.delete_class_parameter("key")


# ---------------------------------------------------------------------------
# write_params base implementation
# ---------------------------------------------------------------------------

def test_write_params_base_returns_empty() -> None:
    obj = SolidServerModel.model_validate({})
    assert obj.write_params() == {}


# ---------------------------------------------------------------------------
# build_class_request / build_request / parse_response / apply_response
# ---------------------------------------------------------------------------

def test_build_class_request_unknown_op_raises() -> None:
    with pytest.raises(ValueError, match="Unknown class operation"):
        SolidServerModel.build_class_request("count")


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
        SolidServerModel.parse_response("count", [])


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


def test_as_hex_ipv4_invalid_returns_none() -> None:
    assert SolidServerModel._as_hex_ipv4("zzzzzzzz") is None


def test_as_dotted_ipv4_invalid_returns_none() -> None:
    assert SolidServerModel._as_dotted_ipv4("999.999.999.999") is None


def test_as_datetime_invalid_returns_none() -> None:
    assert SolidServerModel._as_datetime("not-a-timestamp") is None
