"""Live integration tests for IPAM subnet services.

These tests require a real SolidServer.  Copy .env.example → .env with valid
credentials; the tests skip automatically if the variables are absent.

Run with:
    poetry run pytest tests/integration/ -v
"""

import pytest

from eip_pydantic import AsyncSession, Session
from eip_pydantic.models.subnet import Subnet



# ---------------------------------------------------------------------------
# Sync tests
# ---------------------------------------------------------------------------


def test_subnet_list_returns_subnets(session: Session) -> None:
    subnets = session.list(Subnet, limit=10)
    assert isinstance(subnets, list)
    assert len(subnets) > 0, "Expected at least one subnet in the database"
    for s in subnets:
        assert isinstance(s, Subnet)
        assert s.subnet_id, "subnet_id must be non-zero"


def test_subnet_list_with_where(session: Session) -> None:
    all_subnets = session.list(Subnet, limit=1)
    if not all_subnets:
        pytest.skip("No subnets available to test WHERE clause")
    first = all_subnets[0]
    filtered = session.list(Subnet, where=f"subnet_id='{first.subnet_id}'")
    assert len(filtered) == 1
    assert filtered[0].subnet_id == first.subnet_id


def test_subnet_list_with_limit(session: Session) -> None:
    five = session.list(Subnet, limit=5)
    assert len(five) <= 5


def test_subnet_list_with_orderby(session: Session) -> None:
    subnets = session.list(Subnet, limit=10, orderby="start_ip_addr ASC")
    assert isinstance(subnets, list)


def test_subnet_info(session: Session) -> None:
    subnets = session.list(Subnet, limit=1)
    if not subnets:
        pytest.skip("No subnets available to test subnet info")
    subnet_id = subnets[0].subnet_id
    assert subnet_id is not None
    info = session.get(Subnet, subnet_id)
    assert isinstance(info, Subnet)
    assert info.subnet_id == subnet_id


def test_subnet_info_has_ip_addresses(session: Session) -> None:
    subnets = session.list(Subnet, limit=1)
    if not subnets:
        pytest.skip("No subnets available")
    assert subnets[0].subnet_id is not None
    info = session.get(Subnet, subnets[0].subnet_id)
    # Subnet encodes its address range in the IPv4Network field; network_address
    # and broadcast_address give the start and end respectively.
    assert info.subnet.network_address is not None
    assert info.subnet.broadcast_address is not None


def test_subnet_class_params_parseable(session: Session) -> None:
    subnets = session.list(Subnet, limit=20)
    from eip_pydantic import ClassParamDict
    for s in subnets:
        assert isinstance(s.class_params, ClassParamDict)


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------


async def test_async_subnet_list(async_session: AsyncSession) -> None:
    subnets = await async_session.list(Subnet, limit=10)
    assert isinstance(subnets, list)
    assert len(subnets) > 0
    for s in subnets:
        assert isinstance(s, Subnet)
        assert s.subnet_id


async def test_async_subnet_info(async_session: AsyncSession) -> None:
    subnets = await async_session.list(Subnet, limit=1)
    if not subnets:
        pytest.skip("No subnets available")
    assert subnets[0].subnet_id is not None
    info = await async_session.get(Subnet, subnets[0].subnet_id)
    assert isinstance(info, Subnet)
    assert info.subnet_id == subnets[0].subnet_id
