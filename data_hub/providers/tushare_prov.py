# -*- coding: utf-8 -*-
"""
Tushare Pro 数据源适配器
当用户已在设置页配置有效 Tushare Token 时，作为全市场日线/基础指标主源及个股前复权终极兜底。
若未配置 Token 或配额/权限不足，抛出清晰异常交由 data_hub 自动切换到免 Token 备选通道。
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from data_hub.providers import normalize_ticker


def _get_pool():
    from tushare_client import TusharePool

    return TusharePool()


def fetch_daily_all_date(trade_date: str, fields: Optional[str] = None) -> pd.DataFrame:
    """通过 Tushare Pro 按交易日抓取全市场 A 股行情。"""
    pro = _get_pool()
    kwargs = {"trade_date": str(trade_date)}
    if fields:
        kwargs["fields"] = fields
    df = pro.daily(**kwargs)
    if df is None or df.empty:
        raise ValueError(f"Tushare daily({trade_date}) 返回为空")
    return df


def fetch_market_daily_basic(trade_date: str) -> pd.DataFrame:
    """通过 Tushare Pro 按交易日抓取全市场 daily_basic 基础指标。"""
    pro = _get_pool()
    df = pro.daily_basic(trade_date=str(trade_date))
    if df is None or df.empty:
        raise ValueError(f"Tushare daily_basic({trade_date}) 返回为空")
    return df


def fetch_stock_qfq_daily(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """通过 Tushare Pro (daily + adj_factor) 计算前复权历史日线，作为免 V8/防封终极兜底。"""
    full_code, _, _ = normalize_ticker(symbol)
    sd = str(start_date).replace("-", "")[:8]
    ed = str(end_date).replace("-", "")[:8]
    pro = _get_pool()

    raw = pro.daily(ts_code=full_code, start_date=sd, end_date=ed)
    if raw is None or raw.empty:
        raise ValueError(f"Tushare 个股日线为空: {full_code}")
    adj = pro.adj_factor(ts_code=full_code, start_date=sd, end_date=ed)

    df = raw.copy()
    if adj is not None and not adj.empty and "adj_factor" in adj.columns:
        df = df.merge(adj[["trade_date", "adj_factor"]], on="trade_date", how="left")
        df["adj_factor"] = pd.to_numeric(df["adj_factor"], errors="coerce").ffill().bfill().fillna(1.0)
        latest_factor = float(df.sort_values("trade_date")["adj_factor"].iloc[-1]) or 1.0
        ratio = df["adj_factor"] / latest_factor
    else:
        ratio = 1.0

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce").dt.date
    out["open"] = (pd.to_numeric(df["open"], errors="coerce") * ratio).round(2)
    out["high"] = (pd.to_numeric(df["high"], errors="coerce") * ratio).round(2)
    out["low"] = (pd.to_numeric(df["low"], errors="coerce") * ratio).round(2)
    out["close"] = (pd.to_numeric(df["close"], errors="coerce") * ratio).round(2)
    # Tushare vol 单位为手，amount 单位为千元
    out["volume"] = pd.to_numeric(df["vol"], errors="coerce") * 100.0
    out["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000.0
    out["outstanding_share"] = 0.0
    out["turnover"] = 0.0
    out = out.dropna(subset=["date", "open", "high", "low", "close", "volume", "amount"])
    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    if out.empty:
        raise ValueError(f"Tushare 前复权日线解析为空: {full_code}")
    return out
