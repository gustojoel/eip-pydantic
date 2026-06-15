"""Tests for SolidServerModel class-parameter handling."""

from __future__ import annotations

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
