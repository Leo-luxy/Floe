# -*- coding: utf-8 -*-
"""
腾讯财经数据源适配器
提供：纯 JSON 前复权历史日线（免 V8 解密）、单股实时行情、全市场同日批量行情（用于 step2_daily_basic 免积分兜底）。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import requests

import net_guard
from data_hub.providers import normalize_ticker, to_prefix_symbol
from data_hub.transport import get_transport


def _parse_optional_float(raw_val: Any, multiplier: float = 1.0) -> Optional[float]:
    text = str(raw_val or "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _fmt_date_dash(date_str: str) -> str:
    compact = str(date_str).replace("-", "").strip()[:8]
    if len(compact) == 8 and compact.isdigit():
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
    return str(date_str)


# ============================================================
# 1. 纯 HTTP JSON 前复权历史日线（无需 V8 / mini_racer）
# ============================================================
def fetch_stock_qfq_daily(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """从腾讯 web.ifzq.gtimg.cn 分片回溯抓取前复权历史日线，完全不依赖 JS 引擎。"""
    tx = get_transport()
    tx_sym = to_prefix_symbol(symbol)
    sd_dash = _fmt_date_dash(start_date)
    ed_dash = _fmt_date_dash(end_date)

    collected_rows: List[List[Any]] = []
    cur_end = ed_dash
    max_chunks = 8  # 每片最多 ~640 交易日（约 2.6 年），8 片可覆盖 20 年以上

    for _ in range(max_chunks):
        param = f"{tx_sym},day,{sd_dash},{cur_end},640,qfq"
        payload = tx.request_json(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": param},
            headers={"Referer": "https://gu.qq.com/"},
        )
        stock_data = ((payload or {}).get("data") or {}).get(tx_sym) or {}
        bars = stock_data.get("qfqday") or stock_data.get("day") or []
        if not bars:
            break
        collected_rows.extend(bars)
        earliest = str(bars[0][0])[:10]
        if earliest <= sd_dash or len(bars) < 600:
            break
        try:
            prev_dt = datetime.strptime(earliest, "%Y-%m-%d") - timedelta(days=1)
            next_end = prev_dt.strftime("%Y-%m-%d")
        except Exception:
            break
        if next_end >= cur_end or next_end < sd_dash:
            break
        cur_end = next_end

    if not collected_rows:
        raise ValueError(f"腾讯前复权日线为空: {symbol}")

    parsed: List[Dict[str, Any]] = []
    for row in collected_rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        dt_str = str(row[0])[:10]
        if dt_str < sd_dash or dt_str > ed_dash:
            continue
        try:
            o_val = round(float(row[1]), 2)
            c_val = round(float(row[2]), 2)
            h_val = round(float(row[3]), 2)
            l_val = round(float(row[4]), 2)
            # 腾讯日线第 6 列为成交量（单位：手），乘以 100 统一为「股」
            v_val = float(row[5]) * 100.0
            avg_px = (o_val + h_val + l_val + c_val) / 4.0
            amt_val = round(avg_px * v_val, 2)
        except Exception:
            continue
        parsed.append(
            {
                "date": dt_str,
                "open": o_val,
                "high": h_val,
                "low": l_val,
                "close": c_val,
                "volume": v_val,
                "amount": amt_val,
                "outstanding_share": 0.0,
                "turnover": 0.0,
            }
        )

    if not parsed:
        raise ValueError(f"腾讯前复权日线有效记录为空: {symbol}")

    out = pd.DataFrame(parsed)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date
    out = out.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return out


# ============================================================
# 2. 个股实时行情
# ============================================================
def fetch_realtime_quote(ticker: str, require_price: bool = False) -> Dict[str, Any]:
    """腾讯 qt.gtimg.cn 单股实时行情；使用 urllib.request.urlopen 兼容测试拦截。"""
    full_code, _, _ = normalize_ticker(ticker)
    tx_sym = to_prefix_symbol(full_code)
    url = f"https://qt.gtimg.cn/q={tx_sym}"
    text = get_transport().urlopen_text(
        url,
        headers={"Referer": "https://gu.qq.com/"},
        encoding="gbk",
        timeout=8.0,
    )
    if "~" not in text:
        raise ValueError(f"腾讯实时行情格式异常: {ticker}")
    rhs = text.split("=", 1)[1] if "=" in text else text
    parts = rhs.strip().strip(";").strip('"').split("~")
    if len(parts) < 5 or not parts[1].strip():
        raise ValueError(f"腾讯实时行情无有效名称/价格: {ticker}")

    name = parts[1].strip()
    live_price = _parse_optional_float(parts[3])
    prev_close = _parse_optional_float(parts[4])
    change = _parse_optional_float(parts[31]) if len(parts) > 31 else None
    pct_change = _parse_optional_float(parts[32]) if len(parts) > 32 else None

    price: Optional[float] = None
    price_tag = "实时现价"
    if live_price is not None and live_price > 0:
        price = round(live_price, 4)
        price_tag = "实时现价"
    elif prev_close is not None and prev_close > 0:
        price = round(prev_close, 4)
        price_tag = "昨收价"

    if require_price and price is None:
        raise ValueError(f"腾讯实时行情缺少有效价格: {ticker}")

    return {
        "ticker": full_code,
        "name": name,
        "price": price,
        "prev_close": round(prev_close, 4) if prev_close is not None else None,
        "change": round(change, 4) if change is not None else None,
        "pct_change": round(pct_change, 4) if pct_change is not None else None,
        "price_tag": price_tag,
        "source": "tencent",
    }


# ============================================================
# 3. 全市场同日基础指标批量抓取（step2_daily_basic 兜底）
# ============================================================
def fetch_market_daily_basic_batch(
    trade_date: str,
    df_daily: pd.DataFrame,
    batch_size: int = 600,
    session_factory: Optional[Callable[[], requests.Session]] = None,
) -> Tuple[Optional[pd.DataFrame], str]:
    """通过腾讯 qt.gtimg.cn 批量网关抓取同日基础指标，并执行严格日期与全覆盖门禁。"""
    target_codes = list(df_daily["ts_code"].astype(str))
    if not target_codes:
        return None, "行情列表为空"

    vol_map: Dict[str, float] = {}
    if "vol" in df_daily.columns:
        vols = pd.to_numeric(df_daily["vol"], errors="coerce").fillna(0.0)
        for ts_code, vol_val in zip(df_daily["ts_code"].astype(str), vols):
            vol_map[ts_code] = float(vol_val)

    gt_codes: List[str] = []
    for ts_code in target_codes:
        code6, market = ts_code.split(".")
        prefix = "sh" if market.upper() == "SH" else "sz"
        gt_codes.append(prefix + code6)

    if session_factory is not None:
        sess = session_factory()
    else:
        sess = requests.Session()
        if not get_transport()._is_proxy_mode():
            sess.trust_env = False
        sess.headers.update({"User-Agent": "Mozilla/5.0"})

    parsed_rows: Dict[str, Dict[str, Any]] = {}
    observed_dates: List[str] = []

    try:
        for start in range(0, len(gt_codes), batch_size):
            chunk = ",".join(gt_codes[start : start + batch_size])
            resp = net_guard.retry_on_proxy_error(
                sess.get, f"https://qt.gtimg.cn/q={chunk}", timeout=12
            )
            resp.raise_for_status()
            resp.encoding = "gbk"
            for raw_line in resp.text.strip().split(";"):
                if "~" not in raw_line or "=" not in raw_line:
                    continue
                lhs, rhs = raw_line.split("=", 1)
                parts = rhs.strip().strip('"').split("~")
                if len(parts) < 50:
                    continue
                sym = lhs.strip().split("_")[-1]
                if len(sym) != 8 or sym[:2] not in ("sh", "sz"):
                    continue
                ts_code = f"{sym[2:]}.{'SH' if sym.startswith('sh') else 'SZ'}"
                raw_ts = str(parts[30] or "").strip()
                q_date = raw_ts[:8] if len(raw_ts) >= 8 and raw_ts[:8].isdigit() else ""
                if q_date:
                    observed_dates.append(q_date)
                parsed_rows[ts_code] = {
                    "ts_code": ts_code,
                    "trade_date": str(trade_date),
                    "quote_date": q_date,
                    "turnover_rate": _parse_optional_float(parts[38]),
                    "turnover_rate_f": None,
                    "volume_ratio": _parse_optional_float(parts[49]),
                    "pe": None,
                    "pe_ttm": _parse_optional_float(parts[39]),
                    "pb": _parse_optional_float(parts[46]),
                    "ps": None,
                    "ps_ttm": None,
                    "dv_ratio": None,
                    "dv_ttm": None,
                    "total_share": None,
                    "float_share": None,
                    "free_share": None,
                    "total_mv": _parse_optional_float(parts[45], 10000.0),
                    "circ_mv": _parse_optional_float(parts[44], 10000.0),
                }
    except Exception as exc:
        return None, f"公开批量行情网关请求失败: {exc}"

    if not observed_dates:
        return None, "公开批量行情网关未返回有效交易时间戳"

    dominant_date = Counter(observed_dates).most_common(1)[0][0]
    if dominant_date != str(trade_date):
        return None, f"公开网关当前交易日为 {dominant_date}，与请求交易日 {trade_date} 不一致，禁止跨日混用"

    missing_codes = set(target_codes) - set(parsed_rows.keys())
    if missing_codes:
        return None, f"公开网关缺少 {len(missing_codes)} 只股票的基础指标"

    for ts_code in target_codes:
        item = parsed_rows[ts_code]
        q_date = item["quote_date"]
        if q_date and q_date > str(trade_date):
            return None, f"{ts_code} 行情日期 {q_date} 晚于目标交易日 {trade_date}，禁止混日"
        if vol_map.get(ts_code, 0.0) > 0 and q_date != str(trade_date):
            return None, f"{ts_code} 当日有成交但基础指标日期为 {q_date or '空'}（期望 {trade_date}）"
        if item["total_mv"] is None or item["turnover_rate"] is None:
            if vol_map.get(ts_code, 0.0) > 0:
                return None, f"{ts_code} 缺少总市值或换手率字段"

    ordered = []
    for ts_code in target_codes:
        row = dict(parsed_rows[ts_code])
        row.pop("quote_date", None)
        ordered.append(row)
    return pd.DataFrame(ordered), ""
