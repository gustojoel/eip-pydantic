"""eip-pydantic — typed Python SDK for the EfficientIP SolidServer REST API.

The main entry points are :class:`Session` (sync) and :class:`AsyncSession` (async).
Model classes (:class:`Space`, :class:`Subnet`, :class:`Pool`, :class:`IpAddress`,
:class:`Vrf`) represent API objects and handle wire-format coercion automatically.
"""
from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.client import AsyncEipClient, EipClient
from eip_pydantic.exceptions import ApiError, AuthenticationError, InternalError, NotFoundError, SolidServerError
from eip_pydantic.expressions import ColumnExpr, Condition, OrderByExpr, and_all
from eip_pydantic.session import AsyncSession, BaseSession, FlushRecord, Session



__all__ = [
    "ApiError",
    "AsyncEipClient",
    "AsyncSession",
    "AuthenticationError",
    "BaseSession",
    "ClassParamDict",
    "ColumnExpr",
    "Condition",
    "EipClient",
    "FlushRecord",
    "InternalError",
    "NotFoundError",
    "OrderByExpr",
    "Session",
    "SolidServerError",
    "and_all",
]
