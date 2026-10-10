"""
Futu OpenD adapter (wired into `_libnautilus` by nautilus-futu overlay).

This is an independent community project. It is not affiliated with, endorsed
by, or maintained by Nautech Systems Pty Ltd or the NautilusTrader project.
"""

from __future__ import annotations

from nautilus_trader._fixup import fixup_module_names
from nautilus_trader._libnautilus.futu import *  # noqa: F403


__all__ = [
    "FutuBorrowSnapshot",
    "FutuDataClientConfig",
    "FutuDataClientFactory",
    "FutuExecutionClientConfig",
    "FutuExecutionClientFactory",
    "FutuInstrumentProviderConfig",
    "FutuUsMarketState",
    "FutuTrdEnv",
    "PyFutuClient",
]

fixup_module_names(globals(), __name__)
del fixup_module_names
