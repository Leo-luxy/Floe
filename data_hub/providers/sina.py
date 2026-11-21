# -*- coding: utf-8 -*-
"""
新浪财经数据源适配器
提供：实时行情（第三顺位兜底）、前复权历史日线（委托 KLC 解密或 akshare）、
三大财务报表（利润表/资产负债表/现金流量表，含短 TTL 进程/跨进程共享缓存）、
财务摘要与分析指标、主股东、大盘及港股指数日线。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import akshare as ak
import pandas as pd

from data_hub import market_cache
from data_hub.providers import normalize_ticker, to_prefix_symbol
from data_hub.transport import call_akshare, get_transport


def _safe_float(v: Any) -> Optional[float]:
    try:
        val = float(v)
        return val
    except Exception:
        return None


# ============================================================
# 1. 个股实时行情
# ============================================================
def fetch_realtime_quote(ticker: str, require_price: bool = False) -> Dict[str, Any]:
    """新浪财经 hq.sinajs.cn 实时行情；使用 urllib.request.urlopen 兼容测试拦截。"""
    full_code, _, _ = normalize_ticker(ticker)
    sina_sym = to_prefix_symbol(full_code)
    url = f"https://hq.sinajs.cn/list={sina_sym}"
    text = get_transport().urlopen_text(
        url,
        headers={"Referer": "https://finance.sina.com.cn"},
        encoding="gbk",
        timeout=8.0,
    )
    if '="' not in text:
        raise ValueError(f"新浪实时行情格式异常: {ticker}")
    raw = text.split('="', 1)[1].split('"', 1)[0]
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) < 4 or not parts[0]:
        raise ValueError(f"新浪实时行情无有效数据: {ticker}")

    name = parts[0]
    prev_close = _safe_float(parts[2])
    price = _safe_float(parts[3])
    price_tag = "实时现价"
    if (price is None or price <= 0) and prev_close is not None and prev_close > 0:
        price = prev_close
        price_tag = "昨收价"
    if require_price and (price is None or price <= 0):
        raise ValueError(f"新浪实时行情缺少有效价格: {ticker}")
    change = round(price - prev_close, 4) if (price is not None and prev_close) else None
    pct_change = (
        round((change / prev_close) * 100.0, 4)
        if (change is not None and prev_close and prev_close > 0)
        else None
    )
    return {
        "ticker": full_code,
        "name": name,
        "price": round(price, 4) if price is not None else None,
        "prev_close": round(prev_close, 4) if prev_close is not None else None,
        "change": change,
        "pct_change": pct_change,
        "price_tag": price_tag,
        "source": "sina",
    }


# ============================================================
# 2. 个股前复权历史日线
# ============================================================
def fetch_stock_qfq_daily(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """调用主采集器 Sina KLC 前复权实现（含 V8 延迟导入与统一网络护盾）。"""
    # 延迟导入避免模块加载循环，且复用 data_collector 中经单测充分验证的 KLC 解码逻辑
    import data_collector

    sina_sym = to_prefix_symbol(symbol)
    sd = str(start_date).replace("-", "")[:8]
    ed = str(end_date).replace("-", "")[:8]
    df = call_akshare(
        data_collector.stock_zh_a_daily,
        symbol=sina_sym,
        start_date=sd,
        end_date=ed,
        adjust="qfq",
    )
    if df is None or df.empty:
        raise ValueError(f"新浪前复权日线返回为空: {symbol}")
    return df


# ============================================================
# 3. 财务三表 / 财务摘要 / 财务指标（短 TTL 缓存消除双脚本重复拉取）
# ============================================================
def fetch_financial_report_cached(
    ticker: str,
    report_type: str,
    *,
    ttl_seconds: float = 600.0,
) -> pd.DataFrame:
    """获取新浪财务报表（利润表 / 资产负债表 / 现金流量表），600s 内同进程/多脚本共享缓存。"""
    _, code, exch = normalize_ticker(ticker)
    sina_sym = f"{exch}{code}"
    type_tag = {
        "利润表": "profit",
        "资产负债表": "balance",
        "现金流量表": "cashflow",
    }.get(report_type, "other")
    cache_key = f"stock_{code}_sina_{type_tag}"
    return market_cache.get_or_fetch_df(
        cache_key,
        lambda: call_akshare(ak.stock_financial_report_sina, stock=sina_sym, symbol=report_type),
        ttl_seconds=ttl_seconds,
        dtype={"报告日": str, "公告日期": str, "更新日期": str},
    )


def fetch_financial_abstract_cached(
    ticker: str,
    *,
    ttl_seconds: float = 600.0,
) -> pd.DataFrame:
    """获取财务摘要（同花顺/新浪汇总），共享短缓存避免多次采集重拉。"""
    _, code, _ = normalize_ticker(ticker)
    return market_cache.get_or_fetch_df(
        f"stock_{code}_fin_abstract",
        lambda: call_akshare(ak.stock_financial_abstract, symbol=code),
        ttl_seconds=ttl_seconds,
        dtype={"选项": str, "指标": str},
    )


def fetch_financial_analysis_indicator(ticker: str) -> pd.DataFrame:
    """获取新浪主要财务分析指标表。"""
    _, code, _ = normalize_ticker(ticker)
    return call_akshare(ak.stock_financial_analysis_indicator, symbol=code)


def fetch_main_stock_holder(ticker: str) -> pd.DataFrame:
    """获取新浪前十大股东数据。"""
    _, code, _ = normalize_ticker(ticker)
    return call_akshare(ak.stock_main_stock_holder, stock=code)


# ============================================================
# 4. 指数日线（大盘 / 中证 / 港股）
# ============================================================
def fetch_broad_index_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """从新浪获取 A 股大盘/中证指数或港股指数历史日线，并裁剪日期区间。"""
    if symbol.startswith("hk_"):
        hk_code = symbol[3:]
        df = call_akshare(ak.stock_hk_index_daily_sina, symbol=hk_code)
    else:
        df = call_akshare(ak.stock_zh_index_daily, symbol=symbol)

    if df is None or df.empty:
        raise ValueError(f"新浪指数日线返回为空: {symbol}")

    out = df.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        sd = pd.to_datetime(start_date, errors="coerce")
        ed = pd.to_datetime(end_date, errors="coerce")
        if pd.notna(sd) and pd.notna(ed):
            out = out[(out["date"] >= sd) & (out["date"] <= ed)]
    if out.empty:
        raise ValueError(f"新浪指数日线过滤日期后为空: {symbol}")
    return out.reset_index(drop=True)
