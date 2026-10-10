"""
QMT adapter (wired into `_libnautilus` by nautilus-qmt overlay).

This is an independent community project. It is not affiliated with, endorsed
by, or maintained by Nautech Systems Pty Ltd or the NautilusTrader project.
"""

from __future__ import annotations

from nautilus_trader._fixup import fixup_module_names
from nautilus_trader._libnautilus.qmt import *
from nautilus_trader.adapters.qmt.calendar import QmtTradingCalendar

__all__ = [
    "QmtAccountKind",
    "QmtDataClientConfig",
    "QmtDataClientFactory",
    "QmtExecutionClientConfig",
    "QmtExecutionClientFactory",
    "QmtFormulaConfig",
    "QmtInstrumentProviderConfig",
    "QmtTradingCalendar",
    "QmtTradingMode",
    "QmtTransport",
]

fixup_module_names(globals(), __name__)
del fixup_module_names
