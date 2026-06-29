"""Tests for BaseSession.reset() and SolidServerModel invalidation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from eip_pydantic import InvalidatedError, Session
from eip_pydantic.exceptions import ApiError
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet


BASE = "https://solidserver.example.com/"
HOST = "solidserver.example.com"
CREDS = ("admin", "secret")

_SPACE_ROW: dict[str, str] = {
    "errno": "0",
    "site_id": "7",
    "site_name": "global",
    "row_enabled": "1",
    "multistatus": "",
    "tree_level": "0",
    "tree_path": "global#",
    "tree_id_path": "#7#",
    "site_class_parameters": "",
    "site_class_parameters_properties": "",
    "site_class_parameters_inheritance_source": "",
}

_SUBNET_ROW: dict[str, str] = {
    "errno": "0",
    "subnet_id": "1",
    "subnet_name": "test-net",
    "site_id": "7",
    "start_hostaddr": "10.0.0.0",
    "start_ip_addr": "0a000000",
    "subnet_size": "256",
    "row_enabled": "1",
    "is_terminal": "0",
    "lock_network_broadcast": "0",
    "is_in_orphan": "0",
    "subnet_class_name": "",
    "subnet_class_parameters": "",
    "subnet_class_parameters_properties": "",
}


# ---------------------------------------------------------------------------
# invalidate() / is_invalidated on the model
# ---------------------------------------------------------------------------


def test_freshly_loaded_object_is_not_invalidated() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    assert not sn.is_invalidated


def test_invalidate_sets_flag() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.invalidate()
    assert sn.is_invalidated


def test_invalidated_object_raises_on_setattr() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.invalidate()
    with pytest.raises(InvalidatedError):
        sn.subnet_name = "new-name"


def test_invalidated_object_raises_on_build_request() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.invalidate()
    with pytest.raises(InvalidatedError):
        sn.build_request("update")


def test_invalidated_object_raises_on_write_params() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.invalidate()
    with pytest.raises(InvalidatedError):
        sn.write_params()


def test_invalidated_object_raises_on_apply_response() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.invalidate()
    with pytest.raises(InvalidatedError):
        sn.apply_response("update", {})


def test_invalidated_object_fields_still_readable() -> None:
    """Field values survive invalidation for post-mortem inspection."""
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.subnet_name = "renamed"
    sn.invalidate()
    assert sn.subnet_name == "renamed"
    assert sn.subnet_id == 1


def test_invalidated_error_carries_obj_reference() -> None:
    sn = Subnet.model_validate(_SUBNET_ROW)
    sn.invalidate()
    exc = pytest.raises(InvalidatedError, sn.build_request, "update")
    assert exc.value.obj is sn


def test_invalidated_error_message_contains_class_name() -> None:
    sp = Space.model_validate(_SPACE_ROW)
    sp.invalidate()
    exc = pytest.raises(InvalidatedError, sp.build_request, "update")
    assert "Space" in str(exc.value)


# ---------------------------------------------------------------------------
# BaseSession.reset() — cache objects
# ---------------------------------------------------------------------------


@respx.mock
def test_reset_clears_cache() -> None:
    respx.get(f"{BASE}rest/ip_site_list").mock(
        return_value=httpx.Response(200, json=[_SPACE_ROW]),
    )
    with Session(HOST, *CREDS) as s:
        spaces = s.list(Space)
        assert len(s._cache) == 1
        s.reset()
        assert len(s._cache) == 0
        assert len(s._new) == 0
        _ = spaces  # reference kept; no flush on exit (reset cleared)


def test_reset_invalidates_cached_objects() -> None:
    with Session(HOST, *CREDS) as s:
        sn = Subnet.model_validate(_SUBNET_ROW)
        s._put_cache(sn)
        s.reset()
        assert sn.is_invalidated


def test_reset_invalidates_new_objects() -> None:
    with Session(HOST, *CREDS) as s:
        sn = Subnet.model_validate(_SUBNET_ROW)
        s._new.append(sn)
        s.reset()
        assert sn.is_invalidated
        assert len(s._new) == 0


def test_reset_clears_last_flush() -> None:
    with Session(HOST, *CREDS) as s:
        s.last_flush = [MagicMock()]  # type: ignore[list-item]
        s.reset()
        assert s.last_flush == []


def test_reset_leaves_session_usable() -> None:
    """After reset(), the session accepts new objects normally."""
    with Session(HOST, *CREDS) as s:
        sn1 = Subnet.model_validate(_SUBNET_ROW)
        s._put_cache(sn1)
        s.reset()

        sn2 = Subnet.model_validate({**_SUBNET_ROW, "subnet_id": "99"})
        s._put_cache(sn2)
        assert len(s._cache) == 1
        assert (Subnet, 99) in s._cache


def test_reset_on_empty_session_is_a_no_op() -> None:
    with Session(HOST, *CREDS) as s:
        s.reset()  # must not raise
        assert s._cache == {}
        assert s._new == []
        assert s.last_flush == []


# ---------------------------------------------------------------------------
# Typical error-recovery pattern
# ---------------------------------------------------------------------------


@respx.mock
def test_reset_after_failed_flush() -> None:
    """Typical pattern: flush raises, caller resets, session is like new."""
    respx.post(f"{BASE}rest/ip_site_add").mock(
        return_value=httpx.Response(400, text="Bad Request"),
    )
    s = Session(HOST, *CREDS)
    try:
        sp = s.create(Space, site_name="test-space")
        with pytest.raises(ApiError):
            s.flush()

        # sp is in unknown state — reset invalidates it and clears session
        s.reset()
        assert sp.is_invalidated
        assert len(s._new) == 0
        assert len(s._cache) == 0

        # session is usable again — create without flushing to keep test self-contained
        sp2 = s.create(Space, site_name="test-space-2")
        assert sp2.is_new
        assert not sp2.is_invalidated
        s._new.clear()  # don't flush on close
    finally:
        s._client.close()
