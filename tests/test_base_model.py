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


# ---------------------------------------------------------------------------
# build_class_request / build_request / parse_response / apply_response
# ---------------------------------------------------------------------------

def test_build_class_request_unknown_op_raises() -> None:
    with pytest.raises(ValueError, match="Unknown class operation"):
        SolidServerModel.build_class_request("frobnicate")


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


def test_as_hex_ipv4_invalid_returns_none() -> None:
    assert SolidServerModel._as_hex_ipv4("zzzzzzzz") is None


def test_as_dotted_ipv4_invalid_returns_none() -> None:
    assert SolidServerModel._as_dotted_ipv4("999.999.999.999") is None


def test_as_datetime_invalid_returns_none() -> None:
    assert SolidServerModel._as_datetime("not-a-timestamp") is None
