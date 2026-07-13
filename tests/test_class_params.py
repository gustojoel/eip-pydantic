"""Unit tests for ClassParamDict behavior and edge cases."""

import pytest

from eip_pydantic.class_params import ClassParamDict, VALID_INHERITANCE_MODES, VALID_PROPAGATION_MODES



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
    assert sorted(iter(cp)) == ["k1", "k2"]
    assert sorted(cp.items()) == [("k1", "v1"), ("k2", "v2")]
    assert "ClassParamDict" in repr(cp)


def test_get_returns_value_or_default() -> None:
    cp = ClassParamDict.empty()
    cp["k1"] = "v1"

    assert cp.get("k1") == "v1"
    assert cp.get("missing") is None
    assert cp.get("missing", "fallback") == "fallback"


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


# ---------------------------------------------------------------------------
# Full round-trip (de)serialisation — to_full_dict / from_full_dict / from_any
# ---------------------------------------------------------------------------

def test_to_full_dict_puts_values_at_top_level() -> None:
    cp = ClassParamDict.from_blobs(
        params_blob="a=1&b=2",
        props_blob="a=set,restrict&b=inherited,propagate",
        sources_blob="b=real_site,7",
        api_prefix="site",
    )
    del cp["a"]

    assert cp.to_full_dict() == {
        "b": "2",
        "$propagation": {"b": "inherited,propagate"},
        "$source": {"b": "real_site,7"},
    }


def test_to_full_dict_omits_reserved_keys_when_nothing_to_say() -> None:
    cp = ClassParamDict.empty()
    cp["a"] = "1"

    assert cp.to_full_dict() == {"a": "1", "$propagation": {"a": "inherited_or_set,propagate"}}


def test_to_full_dict_does_not_serialise_frozen() -> None:
    """frozen is deliberately not part of the wire format — like other
    read-only fields on these models, the caller is expected to know which
    ClassParamDict fields are frozen rather than have it re-derived from JSON."""
    frozen = ClassParamDict.from_blobs("a=1", "a=set,propagate", frozen=True)

    assert "$frozen" not in frozen.to_full_dict()
    assert "frozen" not in frozen.to_full_dict()


def test_to_full_dict_drops_pending_deletes() -> None:
    cp = ClassParamDict.empty()
    cp.set("a", "1")
    cp.set("b", "2")
    del cp["a"]

    full = cp.to_full_dict()

    assert "a" not in full
    assert full == {"b": "2", "$propagation": {"b": "inherited_or_set,propagate"}}


def test_from_full_dict_round_trips_props_and_sources() -> None:
    original = ClassParamDict.from_blobs(
        params_blob="a=1&b=2",
        props_blob="a=set,restrict&b=inherited,propagate",
        sources_blob="b=real_site,7",
        api_prefix="site",
    )

    rebuilt = ClassParamDict.from_full_dict(original.to_full_dict(), api_prefix="site")

    assert dict(rebuilt.items()) == dict(original.items())
    assert rebuilt.is_set("a")
    assert rebuilt.is_restrict("a")
    assert rebuilt.is_inherited("b")
    assert rebuilt.is_propagate("b")
    assert rebuilt.source("b") == original.source("b")
    assert rebuilt.api_prefix == "site"


def test_from_full_dict_result_is_always_unfrozen() -> None:
    """to_full_dict() doesn't serialise frozen, so a frozen source's round-trip
    always comes back mutable — the caller is expected to know which fields
    are frozen, same as any other read-only field on these models."""
    frozen = ClassParamDict.from_blobs("a=1", "a=set,propagate", frozen=True)

    rebuilt = ClassParamDict.from_full_dict(frozen.to_full_dict())

    assert rebuilt.frozen is False
    rebuilt["a"] = "2"  # would raise TypeError if still frozen


def test_from_full_dict_does_not_resurrect_deleted_keys() -> None:
    original = ClassParamDict.empty()
    original.set("a", "1")
    original.set("b", "2")
    del original["a"]

    rebuilt = ClassParamDict.from_full_dict(original.to_full_dict())

    assert rebuilt.deleted == frozenset()
    assert "a" not in rebuilt
    assert "b" in rebuilt


def test_from_full_dict_omitted_props_default_to_set_and_propagate() -> None:
    cp = ClassParamDict.from_full_dict({"a": "1"})

    assert cp.is_set("a")
    assert cp.is_propagate("a")


def test_from_full_dict_omitted_propagation_defaults_to_propagate() -> None:
    cp = ClassParamDict.from_full_dict({"a": "1", "$propagation": {"a": "inherited"}})

    assert cp.is_inherited("a")
    assert cp.is_propagate("a")


def test_from_full_dict_omitted_optional_keys() -> None:
    cp = ClassParamDict.from_full_dict({"a": "1"})

    assert cp.frozen is False
    assert cp.deleted == frozenset()
    with pytest.raises(KeyError):
        cp.source("a")


@pytest.mark.parametrize("bad_mode", ["", "bogus", "SET", "SETTING"])
def test_from_full_dict_invalid_inheritance_mode_raises(bad_mode: str) -> None:
    with pytest.raises(ValueError, match="Invalid inheritance mode"):
        ClassParamDict.from_full_dict({"a": "1", "$propagation": {"a": f"{bad_mode},propagate"}})


@pytest.mark.parametrize("bad_mode", ["", "bogus", "RESTRICT"])
def test_from_full_dict_invalid_propagation_mode_raises(bad_mode: str) -> None:
    with pytest.raises(ValueError, match="Invalid propagation mode"):
        ClassParamDict.from_full_dict({"a": "1", "$propagation": {"a": f"set,{bad_mode}"}})


@pytest.mark.parametrize("mode", sorted(VALID_INHERITANCE_MODES))
def test_from_full_dict_accepts_all_valid_inheritance_modes(mode: str) -> None:
    cp = ClassParamDict.from_full_dict({"a": "1", "$propagation": {"a": f"{mode},propagate"}})
    assert cp._props["a"][0] == mode  # noqa: SLF001


@pytest.mark.parametrize("mode", sorted(VALID_PROPAGATION_MODES))
def test_from_full_dict_accepts_all_valid_propagation_modes(mode: str) -> None:
    cp = ClassParamDict.from_full_dict({"a": "1", "$propagation": {"a": f"set,{mode}"}})
    assert cp._props["a"][1] == mode  # noqa: SLF001


def test_from_any_passes_through_existing_instance() -> None:
    cp = ClassParamDict.empty()
    assert ClassParamDict.from_any(cp) is cp


def test_from_any_dispatches_full_dict_shape() -> None:
    cp = ClassParamDict.from_any({"a": "1", "$propagation": {"a": "set,restrict"}})
    assert cp.is_set("a")
    assert cp.is_restrict("a")


def test_from_any_dispatches_plain_dict_shape() -> None:
    cp = ClassParamDict.from_any({"a": "1", "b": "2"})
    assert dict(cp.items()) == {"a": "1", "b": "2"}
    assert cp.is_inherited_or_set("a")
    assert cp.is_propagate("a")


def test_from_any_plain_dict_defaults_differ_from_full_dict_defaults() -> None:
    """A plain dict (no reserved keys) defaults every key to
    inherited_or_set/propagate, matching __setitem__; a full dict (has a
    reserved key, even for an unrelated param) defaults an unlisted key to
    set/propagate instead, matching from_blobs. Presence of any '$'-prefixed
    key is what distinguishes the two shapes."""
    plain = ClassParamDict.from_any({"a": "1"})
    full = ClassParamDict.from_any({"a": "1", "b": "2", "$propagation": {"b": "set,restrict"}})

    assert plain.is_inherited_or_set("a")
    assert full.is_set("a")  # "a" has no $propagation entry, but dict is still "full" mode


def test_from_any_rejects_reserved_key_as_param_name() -> None:
    """Documented limitation: a class parameter literally named '$propagation'
    or '$source' cannot round-trip through the plain-dict path, since either
    key flips detection to full-dict mode and is consumed as metadata instead
    of a param value."""
    cp = ClassParamDict.from_any({"a": "1", "$source": {}})
    assert "$source" not in cp
    assert dict(cp.items()) == {"a": "1"}


@pytest.mark.parametrize("reserved_key", ["$propagation", "$source"])
def test_from_full_dict_rejects_non_dict_reserved_value(reserved_key: str) -> None:
    with pytest.raises(TypeError, match="must be a dict") as exc_info:
        ClassParamDict.from_full_dict({"a": "1", reserved_key: "not-a-dict"})
    assert reserved_key in str(exc_info.value)


def test_from_any_invalid_type_raises_type_error() -> None:
    with pytest.raises(TypeError, match="Cannot construct ClassParamDict"):
        ClassParamDict.from_any(42)


def test_from_any_propagates_invalid_inheritance_error() -> None:
    with pytest.raises(ValueError, match="Invalid inheritance mode"):
        ClassParamDict.from_any({"a": "1", "$propagation": {"a": "bogus,propagate"}})
