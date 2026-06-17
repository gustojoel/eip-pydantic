"""Unit tests for ClassParamDict behavior and edge cases."""

import pytest

from eip_pydantic.class_params import ClassParamDict


def test_from_blobs_defaults_and_sources() -> None:
    cp = ClassParamDict.from_blobs(
        params_blob="a=1&b=2&c=3",
        props_blob="a=inherited,restrict&b=set",
        sources_blob="a=real_site,7&b=real_site",
        api_prefix="site",
    )

    assert cp["a"] == "1"
    assert cp["b"] == "2"
    assert cp["c"] == "3"
    assert cp.is_inherited("a")
    assert cp.is_restrict("a")
    assert cp.is_set("b")
    assert cp.is_propagate("b")
    assert cp.is_set("c")
    assert cp.is_propagate("c")
    assert cp.source("a") == ("real_site", "7")
    assert cp.source("b") == ("real_site", "")
    assert cp.api_prefix == "site"


def test_mapping_interface_basics() -> None:
    cp = ClassParamDict.empty()
    cp["k1"] = "v1"
    cp["k2"] = "v2"

    assert "k1" in cp
    assert len(cp) == 2
    assert sorted(list(iter(cp))) == ["k1", "k2"]
    assert sorted(list(cp.items())) == [("k1", "v1"), ("k2", "v2")]
    assert "ClassParamDict" in repr(cp)


def test_setitem_existing_key_preserves_propagation_and_updates_inheritance() -> None:
    cp = ClassParamDict.from_blobs("x=old", "x=inherited,restrict")
    cp["x"] = "new"

    assert cp["x"] == "new"
    assert cp.is_inherited_or_set("x")
    assert cp.is_restrict("x")


def test_set_explicit_modes_and_delete_lifecycle() -> None:
    cp = ClassParamDict.empty()
    cp.set("z", "100", inherited_or_set=False, restrict=True)

    assert cp.is_set("z")
    assert cp.is_restrict("z")

    del cp["z"]
    assert "z" not in cp
    assert cp.deleted == frozenset({"z"})

    cp.clear_pending_deletes()
    assert cp.deleted == frozenset()


def test_set_and_delete_are_blocked_when_frozen() -> None:
    frozen_cp = ClassParamDict.from_blobs("a=1", "a=set,propagate", frozen=True)

    with pytest.raises(TypeError, match="read-only"):
        frozen_cp["a"] = "2"

    with pytest.raises(TypeError, match="read-only"):
        frozen_cp.set("a", "2")

    with pytest.raises(TypeError, match="read-only"):
        frozen_cp.delete("a")


def test_wire_callback_notified_on_mutation() -> None:
    cp = ClassParamDict.empty()
    hits = {"count": 0}

    def _cb() -> None:
        hits["count"] += 1

    cp.wire_callback(_cb)
    cp["a"] = "1"
    cp.set("b", "2")
    cp.delete("a")

    assert hits["count"] == 3


def test_blob_serialization_and_prefix_setter() -> None:
    cp = ClassParamDict.empty()
    cp.api_prefix = "pool"
    cp.set("owner", "ops", inherited_or_set=True, restrict=False)

    assert cp.api_prefix == "pool"
    assert cp.to_params_blob() == "owner=ops"
    assert cp.to_properties_blob() == "owner=inherited_or_set%2Cpropagate"


def test_source_missing_key_raises_key_error() -> None:
    cp = ClassParamDict.empty()
    with pytest.raises(KeyError):
        cp.source("missing")
