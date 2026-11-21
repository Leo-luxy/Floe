# -*- coding: utf-8 -*-
"""
数据源适配器包（providers）
提供统一股票代码标准化与日期辅助工具。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Tuple


def normalize_ticker(symbol: str) -> Tuple[str, str, str]:
    """将任意格式股票代码统一解析为 (标准后缀代码, 6位纯代码, 小写交易所代码)。

    例如：
      '300433.SZ' -> ('300433.SZ', '300433', 'sz')
      'sh600519'  -> ('600519.SH', '600519', 'sh')
      '002668'    -> ('002668.SZ', '002668', 'sz')
    """
    raw = str(symbol or "").strip()
    upper = raw.upper()
    if "." in upper:
        code, exch = upper.split(".", 1)
        code = code.zfill(6)
        exch_u = exch if exch in ("SH", "SZ", "BJ") else _infer_exchange(code)
        return f"{code}.{exch_u}", code, exch_u.lower()
    if upper.startswith(("SH", "SZ", "BJ")) and len(upper) >= 8:
        exch_u = upper[:2]
        code = upper[2:].zfill(6)
        return f"{code}.{exch_u}", code, exch_u.lower()
    code = upper.zfill(6)
    exch_u = _infer_exchange(code)
    return f"{code}.{exch_u}", code, exch_u.lower()


def _infer_exchange(code: str) -> str:
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("4", "8", "92")):
        return "BJ"
    return "SZ"


def to_em_secid(symbol: str) -> str:
    """转换为东方财富 push2 接口使用的 secid（1.600519 / 0.002668）。"""
    _, code, exch = normalize_ticker(symbol)
    market_num = "1" if exch == "sh" else "0"
    return f"{market_num}.{code}"


def to_prefix_symbol(symbol: str) -> str:
    """转换为腾讯/新浪前缀代码（sh600519 / sz002668）。"""
    _, code, exch = normalize_ticker(symbol)
    return f"{exch}{code}"


def recent_quarter_dates(years: int = 3) -> List[str]:
    """按时间倒序生成最近 N 年内截至今日的季度报告期末日期列表。"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().year
    candidates: List[str] = []
    for y in range(current_year, current_year - max(1, years) - 1, -1):
        for suffix in ("12-31", "09-30", "06-30", "03-31"):
            dt_str = f"{y}-{suffix}"
            if dt_str <= today_str:
                candidates.append(dt_str)
    return candidates
