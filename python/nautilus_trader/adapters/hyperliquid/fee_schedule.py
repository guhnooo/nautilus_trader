"""Hyperliquid adapter 的逐标的 HIP-3 费率扩展。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from nautilus_trader.model import DataType

HYPERLIQUID_HIP3_FEE_SCHEDULE_TYPE = "HyperliquidHip3FeeSchedule"
# 有效费率公式绑定知识库事实记录；官方公式变化时必须更新该 fact 并重新验证，
# 不得静默沿用旧公式。
# fact_id: hyperliquid.hip3.fee_schedule
# source: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees
FEE_SCHEDULE_FACT_ID = "hyperliquid.hip3.fee_schedule"
GROWTH_MODE_FEE_SCALE = Decimal("0.1")
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParsedUserFees:
    """账户级用户费率档位。"""

    taker_rate: Decimal
    maker_rate: Decimal
    active_referral_discount: Decimal


@dataclass(frozen=True, slots=True)
class ParsedMarketFee:
    """单个 HIP-3 market 的 deployer/growth 配置。"""

    coin: str
    deployer_fee_scale: Decimal
    growth_mode: bool
    last_fee_scale_change_time: str | None


@dataclass(frozen=True, slots=True)
class ParsedFeeEntry:
    """单个 HIP-3 instrument 的有效费率。"""

    instrument_id: str
    coin: str
    deployer_fee_scale: Decimal
    growth_mode: bool
    last_fee_scale_change_time: str | None
    effective_taker_rate: Decimal
    effective_maker_rate: Decimal


def hip3_fee_schedule_data_type(dex: str) -> DataType:
    """构造带 dex 路由信息的 custom data 类型。"""

    return DataType(
        HYPERLIQUID_HIP3_FEE_SCHEDULE_TYPE,
        metadata={"dex": dex},
    )


def _as_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, float):
        raise TypeError(f"{field} 不允许使用二进制浮点")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError(f"{field} 必须是有限十进制")
    return parsed


def parse_user_fees(payload: Mapping[str, Any]) -> ParsedUserFees:
    """解析 adapter userFees 返回值。"""

    try:
        taker_rate = _as_decimal(payload["userCrossRate"], field="userCrossRate")
        maker_rate = _as_decimal(payload["userAddRate"], field="userAddRate")
    except KeyError as exc:
        raise ValueError(f"Hyperliquid userFees 缺少字段: {exc.args[0]}") from exc
    referral = _as_decimal(
        payload.get("activeReferralDiscount", "0"),
        field="activeReferralDiscount",
    )
    if taker_rate < 0:
        raise ValueError("userCrossRate 不得为负")
    if not Decimal(0) <= referral < Decimal(1):
        raise ValueError("activeReferralDiscount 必须位于 [0, 1)")
    return ParsedUserFees(
        taker_rate=taker_rate,
        maker_rate=maker_rate,
        active_referral_discount=referral,
    )


def parse_market_fees(
    payload: Mapping[str, Any], *, dex: str
) -> dict[str, ParsedMarketFee]:
    """解析 meta(dex) 的逐标的 deployer/growth 配置。"""

    universe = payload.get("universe")
    if not isinstance(universe, list):
        raise TypeError("Hyperliquid meta response 缺少 universe")
    result: dict[str, ParsedMarketFee] = {}
    for item in universe:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.startswith(f"{dex}:"):
            continue
        if "deployerFeeScale" not in item:
            raise ValueError(f"{name}: 缺少 deployerFeeScale")
        deployer = _as_decimal(
            item["deployerFeeScale"], field=f"{name}.deployerFeeScale"
        )
        if deployer < 0:
            raise ValueError(f"{name}: deployerFeeScale 不得为负")
        growth_raw = item.get("growthMode")
        if growth_raw in (None, False, "disabled"):
            growth_mode = False
        elif growth_raw in (True, "enabled"):
            growth_mode = True
        else:
            raise ValueError(f"{name}: 不支持的 growthMode {growth_raw!r}")
        last_change = item.get("lastFeeScaleChangeTime")
        result[name] = ParsedMarketFee(
            coin=name,
            deployer_fee_scale=deployer,
            growth_mode=growth_mode,
            last_fee_scale_change_time=str(last_change)
            if last_change is not None
            else None,
        )
    if not result:
        raise ValueError(f"Hyperliquid dex {dex} 没有可解析的 market fee metadata")
    return result


def effective_hip3_fee(
    user: ParsedUserFees,
    market: ParsedMarketFee,
) -> tuple[Decimal, Decimal]:
    """按官方费率公式计算单个 HIP-3 market 的有效费率。

    公式来源见 ``FEE_SCHEDULE_FACT_ID``；参数越界时 fail-closed。
    """

    if not (Decimal(0) < GROWTH_MODE_FEE_SCALE <= Decimal(1)):
        raise ValueError("GROWTH_MODE_FEE_SCALE 必须位于 (0, 1]")
    growth_scale = GROWTH_MODE_FEE_SCALE if market.growth_mode else Decimal(1)
    deployer = market.deployer_fee_scale
    hip3_scale = (
        deployer + Decimal(1) if deployer < Decimal(1) else deployer * Decimal(2)
    )
    referral_scale = Decimal(1) - user.active_referral_discount
    taker = user.taker_rate * growth_scale * hip3_scale * referral_scale
    maker_before_scale = user.maker_rate * growth_scale
    maker = (
        maker_before_scale * hip3_scale * referral_scale
        if maker_before_scale > Decimal(0)
        else maker_before_scale
    )
    return taker, maker


async def load_hip3_fee_schedule(
    client: Any,
    *,
    dex: str = "xyz",
) -> object:
    """通过 Hyperliquid adapter 获取一个 HIP-3 dex 的类型化费率快照。"""

    logger.info(json.dumps({"event": "hip3_fee_schedule_load_started", "dex": dex}))
    try:
        raw_user_fees = await client.info_user_fees()
        user_payload = (
            json.loads(raw_user_fees)
            if isinstance(raw_user_fees, str)
            else raw_user_fees
        )
        user = parse_user_fees(user_payload)

        raw_market_meta = await client.info_meta_for_dex(dex)
        market_payload = (
            json.loads(raw_market_meta)
            if isinstance(raw_market_meta, str)
            else raw_market_meta
        )
        markets = parse_market_fees(market_payload, dex=dex)
    except Exception:
        logger.exception(
            json.dumps({"event": "hip3_fee_schedule_load_failed", "dex": dex})
        )
        raise

    entries: list[ParsedFeeEntry] = []
    for market in markets.values():
        taker, maker = effective_hip3_fee(user, market)
        entries.append(
            ParsedFeeEntry(
                instrument_id=f"{market.coin}-USD-PERP.HYPERLIQUID",
                coin=market.coin,
                deployer_fee_scale=market.deployer_fee_scale,
                growth_mode=market.growth_mode,
                last_fee_scale_change_time=market.last_fee_scale_change_time,
                effective_taker_rate=taker,
                effective_maker_rate=maker,
            )
        )
    ts_event = time.time_ns()
    # 进入 Nautilus 的必须是 adapter 规范化后的 custom_data 领域类型。
    from nautilus_trader.adapters.hyperliquid import HyperliquidHip3FeeSchedule

    ts_init = time.time_ns()
    logger.info(
        json.dumps(
            {
                "event": "hip3_fee_schedule_load_succeeded",
                "dex": dex,
                "market_count": len(markets),
                "entry_count": len(entries),
                "ts_event": ts_event,
            }
        )
    )
    return HyperliquidHip3FeeSchedule(
        dex=dex,
        user_taker_rate=str(user.taker_rate),
        user_maker_rate=str(user.maker_rate),
        active_referral_discount=str(user.active_referral_discount),
        entries=[
            {
                "instrument_id": entry.instrument_id,
                "coin": entry.coin,
                "deployer_fee_scale": str(entry.deployer_fee_scale),
                "growth_mode": entry.growth_mode,
                "last_fee_scale_change_time": entry.last_fee_scale_change_time,
                "effective_taker_rate": str(entry.effective_taker_rate),
                "effective_maker_rate": str(entry.effective_maker_rate),
            }
            for entry in entries
        ],
        ts_event=ts_event,
        ts_init=ts_init,
        source="hyperliquid.info.userFees+meta",
    )
