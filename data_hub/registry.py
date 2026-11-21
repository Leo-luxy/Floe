# -*- coding: utf-8 -*-
"""
data_hub 能力注册中心与多源自动降级引擎
所有采集脚本、选股流程与 API 服务统一通过 `data_hub.fetch(capability, **kwargs)` 取数，
由本模块集中维护「能力 -> 数据源优先级链」、熔断隔离与透明降级日志。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from data_hub.providers import eastmoney, exchange, sina, tencent, ths, tushare_prov
from data_hub.transport import get_circuit_breaker

logger = logging.getLogger("data_hub")


class DataHubError(RuntimeError):
    """当某项能力的所有候选数据源（包括熔断跳过与降级尝试）均不可用时抛出。"""

    def __init__(self, capability: str, errors: Optional[Dict[str, str]] = None, message: str = "") -> None:
        self.capability = capability
        self.errors: Dict[str, str] = dict(errors or {})
        detail = "; ".join(f"{src}: {err}" for src, err in self.errors.items())
        full_msg = message or f"能力 '{capability}' 所有数据源均不可用 ({detail})"
        super().__init__(full_msg)


# 能力默认是否允许返回空数据（非网络错误时直接视作该标的客观无数据，如未开通两融/未入通）
_ALLOW_EMPTY_DEFAULTS: Dict[str, bool] = {
    "stock_margin": True,
    "stock_ex_dividend": True,
    "stock_profit_forecast_em": True,
    "stock_profit_forecast_ths": True,
    "stock_org_holdings": True,
    "stock_north_holdings": True,
    "stock_shareholder_num": True,
    "stock_shareholder_num_detail": True,
    "stock_shareholders": True,
    "stock_company_basic": True,
    "stock_scale_comparison": True,
    "stock_main_business": True,
    "stock_research_reports": True,
    "stock_financial_report": True,
    "stock_financial_abstract": True,
    "stock_financial_indicator": True,
    "stock_em_financial": True,
    "stock_f10_report": True,
    "shenwan_cons": True,
    "sector_board_changes": True,
    "sector_fund_flow": True,
}


CAPABILITY_REGISTRY: Dict[str, List[Dict[str, Any]]] = {}


def register_provider(
    capability: str,
    name: str,
    fn: Callable[..., Any],
    *,
    priority: Optional[int] = None,
    replace: bool = True,
    description: str = "",
) -> None:
    """注册或替换某个能力下的数据源适配器。"""
    chain = CAPABILITY_REGISTRY.setdefault(capability, [])
    if replace:
        chain[:] = [item for item in chain if item.get("name") != name]
    entry = {
        "name": str(name),
        "fn": fn,
        "description": description,
    }
    if priority is None or priority >= len(chain):
        chain.append(entry)
    else:
        chain.insert(max(0, int(priority)), entry)


def get_provider_chain(capability: str) -> List[Dict[str, Any]]:
    """返回指定能力的数据源优先级链（只读拷贝）。"""
    if capability not in CAPABILITY_REGISTRY:
        raise KeyError(f"未注册的 data_hub 能力: {capability}")
    return [dict(item) for item in CAPABILITY_REGISTRY[capability]]


def list_capabilities() -> Dict[str, List[str]]:
    """列出全部已注册能力及其数据源优先级顺序。"""
    return {cap: [item["name"] for item in chain] for cap, chain in CAPABILITY_REGISTRY.items()}


def _is_empty_result(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, pd.DataFrame):
        return val.empty
    if isinstance(val, (dict, list, tuple, set)):
        return len(val) == 0
    return False


def fetch_with_source(
    capability: str,
    *,
    allow_empty: Optional[bool] = None,
    on_fallback: Optional[Callable[[str, str, Exception], None]] = None,
    **kwargs: Any,
) -> Tuple[Any, str]:
    """按注册优先级依次尝试数据源，返回 (数据结果, 实际命中的数据源名称)。"""
    if capability not in CAPABILITY_REGISTRY:
        raise KeyError(f"未注册的 data_hub 能力: {capability}")

    chain = CAPABILITY_REGISTRY[capability]
    if not chain:
        raise DataHubError(capability, {}, f"能力 '{capability}' 未配置任何数据源")

    eff_allow_empty = _ALLOW_EMPTY_DEFAULTS.get(capability, False) if allow_empty is None else bool(allow_empty)
    breaker = get_circuit_breaker()
    errors: Dict[str, str] = {}
    last_exc: Optional[Exception] = None

    for idx, entry in enumerate(chain):
        source_name = str(entry["name"])
        cap_key = f"{capability}:{source_name}"
        fn = entry["fn"]
        if breaker.is_open(source_name) or breaker.is_open(cap_key):
            errors[source_name] = "熔断冷却中（跳过）"
            continue

        try:
            result = fn(**kwargs)
            if not eff_allow_empty and _is_empty_result(result):
                raise ValueError(f"数据源 {source_name} 返回空数据")

            breaker.record_success(cap_key)
            if isinstance(result, pd.DataFrame):
                try:
                    result.attrs["data_hub_source"] = source_name
                except Exception:
                    pass
            return result, source_name
        except Exception as exc:
            last_exc = exc
            errors[source_name] = f"{type(exc).__name__}: {exc}"
            # 按能力粒度隔离熔断，避免冷门子接口误伤同源核心行情通道
            breaker.record_failure(cap_key, exc=exc, trip=True)
            next_source = chain[idx + 1]["name"] if idx + 1 < len(chain) else None
            if next_source:
                msg = f"[{capability}] 源 '{source_name}' 失败（{exc}），自动切换备选 '{next_source}'"
                logger.warning(msg)
                if on_fallback is not None:
                    try:
                        on_fallback(source_name, str(next_source), exc)
                    except Exception:
                        pass

    raise DataHubError(capability, errors) from last_exc


def fetch(
    capability: str,
    *,
    allow_empty: Optional[bool] = None,
    on_fallback: Optional[Callable[[str, str, Exception], None]] = None,
    **kwargs: Any,
) -> Any:
    """按注册优先级获取能力数据，自动完成故障切换与熔断跳过。"""
    result, _ = fetch_with_source(
        capability,
        allow_empty=allow_empty,
        on_fallback=on_fallback,
        **kwargs,
    )
    return result


def _init_default_registry() -> None:
    """初始化全项目统一能力路由表。"""
    # 1. 个股行情与实时报价
    register_provider("stock_qfq_daily", "sina", sina.fetch_stock_qfq_daily)
    register_provider("stock_qfq_daily", "eastmoney", eastmoney.fetch_stock_qfq_daily)
    register_provider("stock_qfq_daily", "tencent", tencent.fetch_stock_qfq_daily)
    register_provider("stock_qfq_daily", "tushare", tushare_prov.fetch_stock_qfq_daily)

    register_provider("stock_realtime_quote", "eastmoney", eastmoney.fetch_realtime_quote)
    register_provider("stock_realtime_quote", "tencent", tencent.fetch_realtime_quote)
    register_provider("stock_realtime_quote", "sina", sina.fetch_realtime_quote)

    # 2. 全市场日线与选股基础指标
    register_provider("market_daily_all", "tushare", tushare_prov.fetch_daily_all_date)
    register_provider("market_daily_basic", "tushare", tushare_prov.fetch_market_daily_basic)
    register_provider("market_daily_basic_fallback", "tencent", tencent.fetch_market_daily_basic_batch)

    # 3. 融资融券（东财单股直查为主，交易所单边按日为备选）
    register_provider("stock_margin", "eastmoney", eastmoney.fetch_stock_margin)
    register_provider("stock_margin", "exchange", exchange.fetch_stock_margin_exchange)

    # 4. 分红 / 盈利预测（全市场 6h 缓存 + 单股接口）
    register_provider("stock_ex_dividend", "eastmoney", eastmoney.fetch_stock_ex_dividend)
    register_provider("stock_profit_forecast_em", "eastmoney", eastmoney.fetch_stock_profit_forecast_em)
    register_provider("stock_profit_forecast_ths", "ths", ths.fetch_profit_forecast)

    # 5. 股东 / 机构 / 北向 / 基础资料 / 研报
    register_provider("stock_org_holdings", "eastmoney", eastmoney.fetch_org_holdings)
    register_provider("stock_north_holdings", "eastmoney", eastmoney.fetch_north_holdings)
    register_provider("stock_shareholder_num", "eastmoney", eastmoney.fetch_shareholder_num_dc)
    register_provider("stock_shareholder_num_detail", "eastmoney", eastmoney.fetch_shareholder_num_detail_em)
    register_provider("stock_shareholders", "eastmoney", eastmoney.fetch_shareholders_dc)
    register_provider("stock_company_basic", "eastmoney", eastmoney.fetch_company_basic_dc)
    register_provider("stock_scale_comparison", "eastmoney", eastmoney.fetch_scale_comparison)
    register_provider("stock_main_business", "ths", ths.fetch_main_business)
    register_provider("stock_research_reports", "eastmoney", eastmoney.fetch_research_reports)

    # 6. 财务报表与指标（共享短 TTL 缓存）
    register_provider("stock_financial_report", "sina", sina.fetch_financial_report_cached)
    register_provider("stock_financial_abstract", "sina", sina.fetch_financial_abstract_cached)
    register_provider("stock_financial_indicator", "sina", sina.fetch_financial_analysis_indicator)
    register_provider("stock_main_shareholders_basic", "sina", sina.fetch_main_stock_holder)
    register_provider("stock_main_shareholders_basic", "eastmoney", eastmoney.fetch_main_shareholders_sina_compat)
    register_provider("stock_em_financial", "eastmoney", eastmoney.fetch_em_financial_table)
    register_provider("stock_f10_report", "eastmoney", eastmoney.fetch_f10_report)

    # 7. 估值与资金流向
    register_provider("stock_valuation", "eastmoney", eastmoney.fetch_valuation_em)
    register_provider("stock_valuation", "legu", exchange.fetch_valuation_legu)
    register_provider("stock_fund_flow", "eastmoney", eastmoney.fetch_fund_flow_em)

    # 8. 申万行业与板块/指数行情
    register_provider("shenwan_levels", "eastmoney", eastmoney.fetch_shenwan_levels_cached)
    register_provider("shenwan_cons", "eastmoney", eastmoney.fetch_shenwan_cons_cached)
    register_provider("broad_index_daily", "sina", sina.fetch_broad_index_daily)
    register_provider("broad_index_daily", "eastmoney", eastmoney.fetch_broad_index_daily)
    register_provider("sector_board_list", "eastmoney", eastmoney.fetch_sector_board_list)
    register_provider("sector_board_list", "ths", ths.fetch_board_list)
    register_provider("sector_board_daily", "eastmoney", eastmoney.fetch_sector_board_daily)
    register_provider("sector_board_daily_ths", "ths", ths.fetch_board_daily)
    register_provider("sector_board_constituents", "eastmoney", eastmoney.fetch_sector_board_constituents)
    register_provider("sector_board_changes", "eastmoney", eastmoney.fetch_board_changes)
    register_provider("sector_fund_flow", "eastmoney", eastmoney.fetch_sector_fund_flow)
    register_provider("hk_index_list", "eastmoney", eastmoney.fetch_hk_index_list)
    register_provider("hk_index_daily", "eastmoney", eastmoney.fetch_hk_index_daily)


_init_default_registry()
