# -*- coding: utf-8 -*-
"""
交易所官方公开网关适配器（上交所 SSE / 深交所 SZSE / 乐咕估值备用源）
用于：东财单股融资融券接口失效时按股票所属单个交易所回溯补齐（绝不混查两个交易所），
以及估值主源不可用时的备选通道。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd

from data_hub.providers import normalize_ticker
from data_hub.transport import call_akshare


def fetch_stock_margin_exchange(
    ticker: str,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_days: int = 30,
) -> pd.DataFrame:
    """仅向目标股票所属的单一交易所按日拉取融资融券明细，作为东财单股通道的降级备选。"""
    _, code, exch = normalize_ticker(ticker)
    if exch not in ("sh", "sz"):
        return pd.DataFrame(
            columns=["证券代码", "证券简称", "融资买入额", "融资余额", "融券卖出量", "融券余量", "融券余额", "融资融券余额", "date"]
        )

    ed_dt = datetime.strptime(str(end_date).replace("-", "")[:8], "%Y%m%d") if end_date else datetime.now()
    sd_dt = datetime.strptime(str(start_date).replace("-", "")[:8], "%Y%m%d") if start_date else (ed_dt - timedelta(days=45))
    if (ed_dt - sd_dt).days > max_days * 2:
        sd_dt = ed_dt - timedelta(days=max_days * 2)

    all_rows = []
    cur = sd_dt
    step_count = 0
    while cur <= ed_dt and step_count < max_days:
        if cur.weekday() < 5:
            d_str = cur.strftime("%Y%m%d")
            step_count += 1
            try:
                if exch == "sh":
                    df = call_akshare(ak.stock_margin_detail_sse, date=d_str)
                    if df is not None and not df.empty and "标的证券代码" in df.columns:
                        sub = df[df["标的证券代码"].astype(str).str.zfill(6) == code]
                        if not sub.empty:
                            sub = sub.rename(
                                columns={
                                    "标的证券代码": "证券代码",
                                    "标的证券简称": "证券简称",
                                }
                            ).copy()
                            if "融资融券余额" not in sub.columns:
                                sub["融资融券余额"] = (
                                    pd.to_numeric(sub.get("融资余额"), errors="coerce").fillna(0)
                                    + pd.to_numeric(sub.get("融券余额"), errors="coerce").fillna(0)
                                )
                            sub["date"] = d_str
                            all_rows.append(sub)
                else:
                    df = call_akshare(ak.stock_margin_detail_szse, date=d_str)
                    if df is not None and not df.empty and "证券代码" in df.columns:
                        sub = df[df["证券代码"].astype(str).str.zfill(6) == code].copy()
                        if not sub.empty:
                            if "融资融券余额" not in sub.columns:
                                sub["融资融券余额"] = (
                                    pd.to_numeric(sub.get("融资余额"), errors="coerce").fillna(0)
                                    + pd.to_numeric(sub.get("融券余额"), errors="coerce").fillna(0)
                                )
                            sub["date"] = d_str
                            all_rows.append(sub)
            except Exception:
                pass
        cur += timedelta(days=1)

    cols = ["证券代码", "证券简称", "融资买入额", "融资余额", "融券卖出量", "融券余量", "融券余额", "融资融券余额", "date"]
    if not all_rows:
        return pd.DataFrame(columns=cols)
    merged = pd.concat(all_rows, ignore_index=True)
    for c in cols:
        if c not in merged.columns:
            merged[c] = 0.0
    return merged[cols].drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)


def fetch_valuation_legu(ticker: str) -> pd.DataFrame:
    """使用 akshare 乐咕接口获取历史 PE/PB 估值（东财 stock_value_em 的备选）。"""
    _, code, _ = normalize_ticker(ticker)
    df = call_akshare(ak.stock_a_pe, symbol=code)
    if df is None or df.empty:
        raise ValueError(f"乐咕估值数据为空: {ticker}")
    return df
