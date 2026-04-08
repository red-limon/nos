"""
Base link package — Link / LinkResult in ``link``; AlwaysLink, ChainLink in dedicated modules.
"""

from .failure_policy import OnNodeFailure, OnRouteFailure
from .link import Link, LinkResult
from .always_link import AlwaysLink
from .chain_link import ChainLink

__all__ = [
    "Link",
    "LinkResult",
    "AlwaysLink",
    "ChainLink",
    "OnNodeFailure",
    "OnRouteFailure",
]
