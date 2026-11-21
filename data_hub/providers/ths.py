# -*- coding: utf-8 -*-
"""
同花顺数据源适配器
收口：个股主营业务描述、同花顺盈利预测、同花顺行业/概念板块列表（含缓存）及历史日线（东方财富板块兜底）。
"""

from __future__ import annotations

from typing import Optional

import akshare as ak
import pandas as pd

from data_hub import market_cache
from data_hub.providers import normalize_ticker
from data_hub.transport import call_akshare


def fetch_main_business(ticker: str) -> pd.DataFrame:
    """获取同花顺公司主营业务构成/介绍。"""
    _, code, _ = normalize_ticker(ticker)
    df = call_akshare(ak.stock_zyjs_ths, symbol=code)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def fetch_profit_forecast(ticker: str) -> pd.DataFrame:
    """获取同花顺机构盈利预测（天然按单只股票查询，延迟极低）。"""
    _, code, _ = normalize_ticker(ticker)
    df = call_akshare(ak.stock_profit_forecast_ths, symbol=code)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def fetch_board_list(board_type: str = "industry") -> pd.DataFrame:
    """获取同花顺行业或概念板块列表（1 小时共享缓存）。"""
    if board_type == "concept":
        return market_cache.get_or_fetch_df(
            "market_ths_concept_boards",
            lambda: call_akshare(ak.stock_board_concept_name_ths),
            ttl_seconds=3600.0,
        )
    return market_cache.get_or_fetch_df(
        "market_ths_industry_boards",
        lambda: call_akshare(ak.stock_board_industry_name_ths),
        ttl_seconds=3600.0,
    )


def fetch_board_daily(
    board_name: str,
    start_date: str,
    end_date: str,
    board_type: str = "industry",
) -> pd.DataFrame:
    """获取同花顺行业或概念板块指数历史日线，并补齐标准成交量/成交额列。"""
    if board_type == "concept":
        df = call_akshare(
            ak.stock_board_concept_index_ths,
            symbol=board_name,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        df = call_akshare(
            ak.stock_board_industry_index_ths,
            symbol=board_name,
            start_date=start_date,
            end_date=end_date,
        )
    if df is None or df.empty:
        raise ValueError(f"同花顺板块日线为空: {board_name}")
    out = df.copy()
    if "成交量" not in out.columns and "volume" not in out.columns:
        out["成交量"] = 1
    if "成交额" not in out.columns and "amount" not in out.columns:
        out["成交额"] = 0
    return out
