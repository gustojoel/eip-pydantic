"""Shared fixtures for live integration tests.

Copy .env.example to .env and fill in your credentials before running:

    poetry run pytest tests/integration/ -v
"""

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from dotenv import load_dotenv

from eip_pydantic import AsyncSession, Session

load_dotenv()

_HOST = os.getenv("EIP_HOST", "")
_USERNAME = os.getenv("EIP_USERNAME", "")
_PASSWORD = os.getenv("EIP_PASSWORD", "")
_VERIFY = os.getenv("EIP_VERIFY", "true").lower() != "false"

_CREDS_AVAILABLE = bool(_HOST and _USERNAME and _PASSWORD)


def _skip_if_no_creds() -> None:
    if not _CREDS_AVAILABLE:
        pytest.skip("EIP_HOST / EIP_USERNAME / EIP_PASSWORD not set in .env")


@pytest.fixture(scope="session")
def session() -> Iterator[Session]:
    _skip_if_no_creds()
    with Session(_HOST, _USERNAME, _PASSWORD, verify=_VERIFY) as s:
        yield s


@pytest.fixture
async def async_session() -> AsyncIterator[AsyncSession]:
    _skip_if_no_creds()
    async with AsyncSession(_HOST, _USERNAME, _PASSWORD, verify=_VERIFY) as s:
        yield s
