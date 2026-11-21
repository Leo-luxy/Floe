# -*- coding: utf-8 -*-
"""
东方财富数据源适配器
收口：前复权日线、实时行情、单股融资融券、F10 财务/估值/成长/杜邦/同行/市场表现、
股东户数、前十大股东、机构持股、北向持股、公司基础信息、研究报告、全市场分红/盈利预测与板块数据。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import akshare as ak
import pandas as pd

from data_hub import market_cache
from data_hub.providers import (
    normalize_ticker,
    recent_quarter_dates,
    to_em_secid,
)
from data_hub.transport import (
    DEFAULT_TIMEOUT,
    call_akshare,
    fetch_eastmoney_datacenter,
    get_transport,
)

SECURITIES_DATACENTER_V1 = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
SECURITIES_DATACENTER_LEGACY = "https://datacenter.eastmoney.com/securities/api/data/get"


def _f10_headers() -> Dict[str, str]:
    return {
        "Host": "datacenter.eastmoney.com",
        "Origin": "https://emweb.securities.eastmoney.com",
        "Referer": "https://emweb.securities.eastmoney.com/",
        "Priority": "u=3, I",
    }


def fetch_f10_datacenter(
    report_name: str,
    *,
    filter_expr: str = "",
    columns: str = "ALL",
    sort_columns: str = "",
    sort_types: str = "",
    page_size: int = 500,
    max_pages: int = 10,
    legacy_sty: Optional[str] = None,
    sort_field_legacy: str = "REPORT_DATE",
    timeout: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """统一拉取 datacenter.eastmoney.com HSF10 接口，支持 v1 与旧版 sty 协议及自动分页。"""
    tx = get_transport()
    headers = _f10_headers()
    rows: List[Dict[str, Any]] = []
    for page in range(1, max(1, int(max_pages)) + 1):
        if legacy_sty:
            url = SECURITIES_DATACENTER_LEGACY
            params: Dict[str, Any] = {
                "type": report_name,
                "sty": legacy_sty,
                "quoteColumns": "",
                "filter": filter_expr,
                "p": page,
                "ps": int(page_size),
                "sr": -1,
                "st": sort_field_legacy,
                "source": "HSF10",
                "client": "PC",
                "v": str(int(time.time() * 1000)),
            }
        else:
            url = SECURITIES_DATACENTER_V1
            params = {
                "reportName": report_name,
                "columns": columns or "ALL",
                "quoteColumns": "",
                "filter": filter_expr,
                "pageNumber": page,
                "pageSize": int(page_size),
                "source": "HSF10",
                "client": "PC",
                "v": str(int(time.time() * 1000)),
            }
            if sort_columns:
                params["sortColumns"] = sort_columns
            if sort_types != "":
                params["sortTypes"] = sort_types

        payload = tx.request_json(
            url,
            params=params,
            headers=headers,
            timeout=timeout or DEFAULT_TIMEOUT,
        )
        if not isinstance(payload, dict):
            break
        code = payload.get("code")
        if payload.get("success") is False and code not in (0, 9201, None):
            msg = payload.get("message") or f"code={code}"
            raise RuntimeError(f"东财 F10 接口异常 ({report_name}): {msg}")
        result = payload.get("result")
        if not isinstance(result, dict):
            break
        data = result.get("data")
        if not isinstance(data, list) or not data:
            break
        rows.extend(item for item in data if isinstance(item, dict))
        total_pages = int(result.get("pages") or 1)
        if page >= total_pages or len(data) < page_size:
            break
    return rows


# ============================================================
# 1. 个股前复权历史行情
# ============================================================
def fetch_stock_qfq_daily(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """从东方财富获取前复权日线，并标准化为与新浪完全一致的 9 列结构与单位（volume=股, turnover=小数）。"""
    _, code, _ = normalize_ticker(symbol)
    sd = str(start_date).replace("-", "")[:8]
    ed = str(end_date).replace("-", "")[:8]
    raw = call_akshare(
        ak.stock_zh_a_hist,
        symbol=code,
        period="daily",
        start_date=sd,
        end_date=ed,
        adjust="qfq",
    )
    if raw is None or raw.empty:
        raise ValueError(f"东方财富前复权日线为空: {symbol}")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(raw["日期"], errors="coerce").dt.date
    out["open"] = pd.to_numeric(raw["开盘"], errors="coerce").round(2)
    out["high"] = pd.to_numeric(raw["最高"], errors="coerce").round(2)
    out["low"] = pd.to_numeric(raw["最低"], errors="coerce").round(2)
    out["close"] = pd.to_numeric(raw["收盘"], errors="coerce").round(2)
    # 东财成交量单位为「手」，乘以 100 转换为与新浪一致的「股」
    out["volume"] = pd.to_numeric(raw["成交量"], errors="coerce") * 100.0
    out["amount"] = pd.to_numeric(raw["成交额"], errors="coerce").fillna(0.0)
    tr_pct = pd.to_numeric(raw.get("换手率"), errors="coerce")
    out["turnover"] = (tr_pct / 100.0).fillna(0.0)
    out["outstanding_share"] = [
        (vol / tr) if (pd.notna(tr) and tr > 0 and pd.notna(vol)) else 0.0
        for vol, tr in zip(out["volume"], out["turnover"])
    ]
    out = out[["date", "open", "high", "low", "close", "volume", "amount", "outstanding_share", "turnover"]]
    out = out.dropna(subset=["date", "open", "high", "low", "close", "volume", "amount"])
    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    if out.empty:
        raise ValueError(f"东方财富前复权日线解析为空: {symbol}")
    return out


# ============================================================
# 2. 个股实时行情
# ============================================================
def fetch_realtime_quote(ticker: str, require_price: bool = False) -> Dict[str, Any]:
    """东方财富 push2 实时行情（fltt=2 直接返回元单位浮点数）；使用 urllib.request.urlopen 兼容测试拦截。"""
    secid = to_em_secid(ticker)
    full_code, _, _ = normalize_ticker(ticker)
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={secid}&fltt=2&invt=2&fields=f43,f44,f45,f46,f57,f58,f60,f169,f170"
    )
    text = get_transport().urlopen_text(
        url,
        headers={"Referer": "https://quote.eastmoney.com/"},
        encoding="utf-8",
        timeout=8.0,
    )
    payload = json.loads(text)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError(f"东方财富实时行情无有效数据: {ticker}")

    name = str(data.get("f58") or "").strip()
    if name == "-":
        name = ""

    def _to_float(v: Any) -> Optional[float]:
        try:
            if v is None or v == "-":
                return None
            return round(float(v), 4)
        except Exception:
            return None

    live_price = _to_float(data.get("f43"))
    prev_close = _to_float(data.get("f60"))
    pct_change = _to_float(data.get("f170"))
    change = _to_float(data.get("f169"))

    price: Optional[float] = None
    price_tag = "实时现价"
    if live_price is not None and live_price > 0:
        price = live_price
        price_tag = "实时现价"
    elif prev_close is not None and prev_close > 0:
        price = prev_close
        price_tag = "昨收价"

    if require_price and price is None:
        raise ValueError(f"东方财富实时行情缺少有效价格: {ticker}")
    if not name and price is None:
        raise ValueError(f"东方财富实时行情无有效名称/价格: {ticker}")

    return {
        "ticker": full_code,
        "name": name,
        "price": price,
        "prev_close": prev_close,
        "change": change,
        "pct_change": pct_change,
        "price_tag": price_tag,
        "source": "eastmoney",
    }


# ============================================================
# 3. 单股融资融券历史
# ============================================================
def fetch_stock_margin(
    ticker: str,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_pages: int = 4,
) -> pd.DataFrame:
    """按单只股票精确拉取东财融资融券历史明细，保持下游既有 9 列格式。"""
    _, code, _ = normalize_ticker(ticker)
    rows = fetch_eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX",
        filter_expr=f'(SCODE="{code}")',
        columns="DATE,SCODE,SECNAME,RZMRE,RZYE,RQMCL,RQYL,RQYE,RZRQYE",
        sort_columns="DATE",
        sort_types="-1",
        page_size=250,
        max_pages=max_pages,
    )
    columns = [
        "证券代码",
        "证券简称",
        "融资买入额",
        "融资余额",
        "融券卖出量",
        "融券余量",
        "融券余额",
        "融资融券余额",
        "date",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)

    records: List[Dict[str, Any]] = []
    sd_compact = str(start_date).replace("-", "")[:8] if start_date else None
    ed_compact = str(end_date).replace("-", "")[:8] if end_date else None
    for item in rows:
        raw_dt = str(item.get("DATE") or "")[:10].replace("-", "")
        if len(raw_dt) != 8 or not raw_dt.isdigit():
            continue
        if sd_compact and raw_dt < sd_compact:
            continue
        if ed_compact and raw_dt > ed_compact:
            continue
        records.append(
            {
                "证券代码": str(item.get("SCODE") or code).zfill(6),
                "证券简称": str(item.get("SECNAME") or ""),
                "融资买入额": item.get("RZMRE"),
                "融资余额": item.get("RZYE"),
                "融券卖出量": item.get("RQMCL"),
                "融券余量": item.get("RQYL"),
                "融券余额": item.get("RQYE"),
                "融资融券余额": item.get("RZRQYE"),
                "date": raw_dt,
            }
        )
    if not records:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(records, columns=columns)
    df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
    return df


# ============================================================
# 4. 除权除息 / 分红（全市场缓存 + 单股接口双通道）
# ============================================================
def fetch_stock_ex_dividend(ticker: str) -> pd.DataFrame:
    """获取单只股票除权除息汇总；优先使用全市场 6h 本地共享缓存，失败则降级单股分红接口。"""
    _, code, _ = normalize_ticker(ticker)
    try:
        all_df = market_cache.get_or_fetch_df(
            "market_history_dividend",
            lambda: call_akshare(ak.stock_history_dividend),
            ttl_seconds=21600.0,
        )
        if all_df is not None and not all_df.empty and "代码" in all_df.columns:
            code_series = all_df["代码"].astype(str).str.strip().str.zfill(6)
            matched = all_df[code_series == code].copy()
            if not matched.empty:
                return matched.reset_index(drop=True)
    except Exception:
        pass

    # 降级：直接查询单股分红送转详情并聚合为兼容格式
    rows = fetch_eastmoney_datacenter(
        "RPT_SHAREBONUS_DET",
        filter_expr=f'(SECURITY_CODE="{code}")',
        sort_columns="REPORT_DATE",
        sort_types="-1",
        page_size=200,
        max_pages=2,
    )
    if not rows:
        return pd.DataFrame(
            columns=["代码", "名称", "上市日期", "累计股息", "年均股息", "分红次数", "融资总额", "融资次数"]
        )
    name = str(rows[0].get("SECURITY_NAME_ABBR") or "")
    bonuses = []
    for r in rows:
        val = r.get("PRETAX_BONUS_RMB")
        if val is not None:
            try:
                bonuses.append(float(val))
            except Exception:
                pass
    total_div = round(sum(bonuses), 4)
    div_cnt = len(bonuses)
    avg_div = round(total_div / div_cnt, 4) if div_cnt > 0 else 0.0
    return pd.DataFrame(
        [
            {
                "代码": code,
                "名称": name,
                "上市日期": "",
                "累计股息": total_div,
                "年均股息": avg_div,
                "分红次数": div_cnt,
                "融资总额": 0.0,
                "融资次数": 0,
            }
        ]
    )


def fetch_stock_profit_forecast_em(ticker: str) -> pd.DataFrame:
    """获取东方财富盈利预测（全市场 6h 缓存，避免每只股票拉 5000+ 行全表）。"""
    _, code, _ = normalize_ticker(ticker)
    all_df = market_cache.get_or_fetch_df(
        "market_profit_forecast_em",
        lambda: call_akshare(ak.stock_profit_forecast_em, symbol=""),
        ttl_seconds=21600.0,
    )
    if all_df is None or all_df.empty or "代码" not in all_df.columns:
        return pd.DataFrame()
    code_series = all_df["代码"].astype(str).str.strip().str.zfill(6)
    return all_df[code_series == code].reset_index(drop=True)


# ============================================================
# 5. 机构持股 / 股东户数 / 前十大股东 / 北向持股 / 公司基础信息
# ============================================================
def fetch_org_holdings(ticker: str, report_date: Optional[str] = None) -> pd.DataFrame:
    """动态探测最新报告期并拉取机构持股明细（严禁写死单一历史年份）。"""
    full_code, _, _ = normalize_ticker(ticker)
    candidates = [report_date] if report_date else []
    if not candidates:
        # 先直接不限 REPORT_DATE 拉少量最新记录以自动发现最新可用报告期
        try:
            probe_rows = fetch_f10_datacenter(
                "RPT_MAIN_ORGHOLDDETAIL",
                filter_expr=f'(SECUCODE="{full_code}")',
                sort_columns="REPORT_DATE",
                sort_types="-1",
                page_size=200,
                max_pages=2,
            )
            if probe_rows:
                latest_dt = str(probe_rows[0].get("REPORT_DATE") or "")[:10]
                if latest_dt:
                    same_period = [r for r in probe_rows if str(r.get("REPORT_DATE") or "")[:10] == latest_dt]
                    if len(probe_rows) < 200:
                        return pd.DataFrame(same_period)
                    candidates = [latest_dt]
        except Exception:
            pass
    if not candidates:
        candidates = recent_quarter_dates(years=3)

    for dt_str in candidates:
        try:
            rows = fetch_f10_datacenter(
                "RPT_MAIN_ORGHOLDDETAIL",
                filter_expr=f'(SECUCODE="{full_code}")(REPORT_DATE=\'{dt_str}\')',
                sort_columns="HOLD_VALUE",
                sort_types="-1",
                page_size=200,
                max_pages=5,
            )
            if rows:
                return pd.DataFrame(rows)
        except Exception:
            continue
    return pd.DataFrame()


def fetch_north_holdings(ticker: str) -> pd.DataFrame:
    """获取北向（陆股通）季度持股历史记录。"""
    full_code, _, _ = normalize_ticker(ticker)
    rows = fetch_f10_datacenter(
        "RPT_MUTUAL_STOCK_HOLDRANKN_NEW",
        filter_expr=f'(SECUCODE="{full_code}")',
        sort_columns="TRADE_DATE",
        sort_types="-1",
        page_size=200,
        max_pages=3,
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ticker"] = full_code
    return df


def fetch_shareholder_num_dc(ticker: str) -> pd.DataFrame:
    """从东财 F10 获取股东户数历史。"""
    full_code, _, _ = normalize_ticker(ticker)
    rows = fetch_f10_datacenter(
        "RPT_F10_EH_HOLDERNUM",
        filter_expr=f'(SECUCODE="{full_code}")',
        sort_columns="END_DATE",
        sort_types="-1",
        page_size=200,
        max_pages=3,
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_shareholder_num_detail_em(ticker: str) -> pd.DataFrame:
    """通过 akshare 获取股东户数补充详情（带增减比例、户均市值等字段）。"""
    _, code, _ = normalize_ticker(ticker)
    df = call_akshare(ak.stock_zh_a_gdhs_detail_em, symbol=code)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def fetch_shareholders_dc(ticker: str, max_periods: int = 8) -> pd.DataFrame:
    """从东财 F10 获取前十大股东历史记录（按报告期倒序，不阻塞睡眠）。"""
    full_code, _, _ = normalize_ticker(ticker)
    rows = fetch_f10_datacenter(
        "RPT_F10_EH_HOLDERS",
        filter_expr=f'(SECUCODE="{full_code}")',
        sort_columns="END_DATE,HOLDER_RANK",
        sort_types="-1,1",
        page_size=200,
        max_pages=5,
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "END_DATE" in df.columns and max_periods > 0:
        dates = sorted(df["END_DATE"].dropna().astype(str).unique(), reverse=True)[:max_periods]
        df = df[df["END_DATE"].astype(str).isin(dates)]
    return df.reset_index(drop=True)


def fetch_company_basic_dc(ticker: str) -> Dict[str, Any]:
    """获取东方财富公司基本信息字典。"""
    full_code, _, _ = normalize_ticker(ticker)
    rows = fetch_f10_datacenter(
        "RPT_F10_BASIC_ORGINFO",
        filter_expr=f'(SECUCODE="{full_code}")',
        page_size=5,
        max_pages=1,
    )
    return rows[0] if rows else {}


def fetch_scale_comparison(ticker: str) -> pd.DataFrame:
    """获取东财同行规模对比表。"""
    full_code, _, _ = normalize_ticker(ticker)
    df = call_akshare(ak.stock_zh_scale_comparison_em, symbol=full_code)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def fetch_research_reports(ticker: str) -> pd.DataFrame:
    """获取东方财富个股研报。"""
    _, code, _ = normalize_ticker(ticker)
    df = call_akshare(ak.stock_research_report_em, symbol=code)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def fetch_valuation_em(ticker: str) -> pd.DataFrame:
    """从东方财富获取历史估值序列（PE/PB/PS/总市值）。"""
    _, code, _ = normalize_ticker(ticker)
    df = call_akshare(ak.stock_value_em, symbol=code)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def fetch_fund_flow_em(ticker: str) -> pd.DataFrame:
    """从东方财富获取个股历史资金流向；优先 akshare，失败直连 push2his fflowkline。"""
    _, code, exch = normalize_ticker(ticker)
    try:
        df = call_akshare(ak.stock_individual_fund_flow, stock=code, market=exch)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # 直连东财 push2his 资金流接口兜底
    secid = to_em_secid(ticker)
    payload = get_transport().request_json(
        "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
        params={
            "lmt": 0,
            "klt": 101,
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        },
        headers={"Referer": "https://data.eastmoney.com/"},
    )
    klines = ((payload or {}).get("data") or {}).get("klines") or []
    if not klines:
        raise ValueError(f"东财资金流向为空: {ticker}")
    rows = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 13:
            continue
        rows.append(
            {
                "日期": parts[0],
                "主力净流入-净额": float(parts[1] or 0),
                "小单净流入-净额": float(parts[2] or 0),
                "中单净流入-净额": float(parts[3] or 0),
                "大单净流入-净额": float(parts[4] or 0),
                "超大单净流入-净额": float(parts[5] or 0),
                "主力净流入-净占比": float(parts[6] or 0),
                "小单净流入-净占比": float(parts[7] or 0),
                "中单净流入-净占比": float(parts[8] or 0),
                "大单净流入-净占比": float(parts[9] or 0),
                "超大单净流入-净占比": float(parts[10] or 0),
                "收盘价": float(parts[11] or 0),
                "涨跌幅": float(parts[12] or 0),
            }
        )
    return pd.DataFrame(rows)


# ============================================================
# 6. 东方财富 F10 财务数据（杜邦 / 成长率 / 主要指标）与行业对比五表
# ============================================================
def fetch_em_financial_table(ticker: str, kind: str, page_size: int = 200) -> pd.DataFrame:
    """获取东财 F10 财务表：kind 支持 'dupont' | 'growth' | 'main'。"""
    full_code, _, _ = normalize_ticker(ticker)
    if kind == "dupont":
        rows = fetch_f10_datacenter(
            "RPT_F10_FINANCE_DUPONT",
            filter_expr=f'(SECUCODE="{full_code}")',
            page_size=page_size,
            max_pages=2,
            legacy_sty="APP_F10_FINANCE_DUPONT",
        )
    elif kind == "growth":
        rows = fetch_f10_datacenter(
            "RPT_F10_FINANCE_GRATIO",
            filter_expr=f'(SECUCODE="{full_code}")',
            sort_columns="REPORT_DATE,INTERFACE_TYPE",
            sort_types="-1,1",
            page_size=page_size,
            max_pages=2,
        )
    elif kind == "main":
        rows = fetch_f10_datacenter(
            "RPT_F10_FINANCE_MAINFINADATA",
            filter_expr=f'(SECUCODE="{full_code}")',
            page_size=page_size,
            max_pages=2,
            legacy_sty="APP_F10_MAINFINADATA",
        )
    else:
        raise ValueError(f"不支持的东财财务类型: {kind}")
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_f10_report(ticker: str, report_type: str) -> List[Dict[str, Any]]:
    """获取 eastmoney_fetcher.py 使用的 5 类行业/市场 F10 报告原始记录。"""
    full_code, _, _ = normalize_ticker(ticker)
    if report_type == "market_performance":
        return fetch_f10_datacenter(
            "RPT_PCF10_INDUSTRY_MARKET",
            filter_expr=f'(SECUCODE="{full_code}")',
            sort_columns="PAIMING",
            sort_types="1",
            page_size=100,
            max_pages=2,
        )
    if report_type == "industry_valuation":
        return fetch_f10_datacenter(
            "RPT_PCF10_INDUSTRY_CVALUE",
            filter_expr=f'(SECUCODE="{full_code}")',
            sort_columns="PAIMING",
            sort_types="1",
            page_size=100,
            max_pages=2,
        )
    if report_type == "industry_peers":
        cols = (
            "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,ORG_CODE,CORRE_SECUCODE,"
            "CORRE_SECURITY_CODE,CORRE_SECURITY_NAME,CORRE_ORG_CODE,TOTAL_CAP,FREECAP,"
            "TOTAL_OPERATEINCOME,NETPROFIT,REPORT_TYPE,TOTAL_CAP_RANK,FREECAP_RANK,"
            "TOTAL_OPERATEINCOME_RANK,NETPROFIT_RANK"
        )
        return fetch_f10_datacenter(
            "RPT_PCF10_INDUSTRY_MARKET",
            columns=cols,
            filter_expr=(
                f'(SECUCODE="{full_code}")(CORRE_SECUCODE<>"{full_code}")'
                f'(CORRE_SECUCODE<>"行业平均")(CORRE_SECUCODE<>"行业中值")'
            ),
            sort_columns="NETPROFIT",
            sort_types="-1",
            page_size=5,
            max_pages=1,
        )
    if report_type == "industry_growth":
        return fetch_f10_datacenter(
            "RPT_PCF10_INDUSTRY_GROWTH",
            filter_expr=f'(SECUCODE="{full_code}")',
            sort_columns="PAIMING",
            sort_types="1",
            page_size=100,
            max_pages=2,
        )
    if report_type == "dupont":
        return fetch_f10_datacenter(
            "RPT_PCF10_INDUSTRY_DBFX",
            filter_expr=f'(SECUCODE="{full_code}")',
            sort_columns="PAIMING",
            sort_types="1",
            page_size=100,
            max_pages=2,
        )
    raise ValueError(f"未知的 F10 报告类型: {report_type}")


# ============================================================
# 7. 申万行业 & 板块指数/榜单（带全市场共享缓存）
# ============================================================
def fetch_shenwan_levels_cached(force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
    """拉取并缓存申万一/二/三级行业分类表（7 天 TTL，避免重复全表下载）。"""
    if force_refresh:
        market_cache.clear_cache("market_shenwan_l")

    l1 = market_cache.get_or_fetch_df(
        "market_shenwan_l1",
        lambda: call_akshare(ak.sw_index_first_info),
        ttl_seconds=604800.0,
    )
    l2 = market_cache.get_or_fetch_df(
        "market_shenwan_l2",
        lambda: call_akshare(ak.sw_index_second_info),
        ttl_seconds=604800.0,
    )
    l3 = market_cache.get_or_fetch_df(
        "market_shenwan_l3",
        lambda: call_akshare(ak.sw_index_third_info),
        ttl_seconds=604800.0,
    )
    return {"l1": l1, "l2": l2, "l3": l3}


def fetch_shenwan_cons_cached(index_code: str, force_refresh: bool = False) -> pd.DataFrame:
    """拉取并缓存单个申万行业成分股列表（7 天 TTL，兼容上游列数漂移时的优雅降级）。"""
    key = f"market_shenwan_cons_{re.sub(r'[^0-9A-Za-z]', '', str(index_code))}"
    if force_refresh:
        market_cache.clear_cache(key)

    def _safe_fetch() -> pd.DataFrame:
        try:
            df = call_akshare(ak.sw_index_third_cons, symbol=index_code)
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        except (ValueError, KeyError, IndexError):
            # 部分申万三级行业在上游页面返回列数变化时温和返回空表，避免阻断全量分析或误伤熔断器
            return pd.DataFrame()

    return market_cache.get_or_fetch_df(
        key,
        _safe_fetch,
        ttl_seconds=604800.0,
        allow_empty=True,
    )


def fetch_broad_index_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """从东方财富获取大盘/中证指数历史日线（作为新浪指数的自动兜底）。"""
    for em_start in (start_date, "20050101", "20100101", "20150101"):
        try:
            df = call_akshare(
                ak.stock_zh_index_daily_em,
                symbol=symbol,
                start_date=em_start,
                end_date=end_date,
            )
            if df is not None and not df.empty:
                return df
        except Exception:
            continue
    raise ValueError(f"东方财富指数日线为空: {symbol}")


def fetch_sector_board_list(board_type: str = "industry") -> pd.DataFrame:
    """获取东方财富行业/概念板块列表，并按 1 小时缓存。"""
    if board_type == "concept":
        return market_cache.get_or_fetch_df(
            "market_em_concept_boards",
            lambda: call_akshare(ak.stock_board_concept_name_em),
            ttl_seconds=3600.0,
        )
    return market_cache.get_or_fetch_df(
        "market_em_industry_boards",
        lambda: call_akshare(ak.stock_board_industry_name_em),
        ttl_seconds=3600.0,
    )


def fetch_sector_board_daily(
    board_code: str,
    start_date: str,
    end_date: str,
    board_type: str = "industry",
) -> pd.DataFrame:
    """获取东方财富板块日线历史。"""
    if board_type == "concept":
        df = call_akshare(
            ak.stock_board_concept_hist_em,
            symbol=board_code,
            period="日k",
            start_date=start_date,
            end_date=end_date,
        )
    else:
        df = call_akshare(
            ak.stock_board_industry_hist_em,
            symbol=board_code,
            period="日k",
            start_date=start_date,
            end_date=end_date,
        )
    if df is None or df.empty:
        raise ValueError(f"东方财富板块历史为空: {board_code}")
    return df


def fetch_sector_board_constituents(board_code: str) -> pd.DataFrame:
    """获取东方财富行业板块成分股（带 6 小时共享缓存）。"""
    safe_code = re.sub(r"[^0-9A-Za-z]", "", str(board_code))
    return market_cache.get_or_fetch_df(
        f"market_em_board_cons_{safe_code}",
        lambda: call_akshare(ak.stock_board_industry_cons_em, symbol=board_code),
        ttl_seconds=21600.0,
    )


def fetch_board_changes() -> pd.DataFrame:
    """获取当日板块异动数据。"""
    return call_akshare(ak.stock_board_change_em)


def fetch_sector_fund_flow() -> pd.DataFrame:
    """获取板块资金流向排名。"""
    return call_akshare(ak.stock_sector_fund_flow_rank)


def fetch_hk_index_list() -> pd.DataFrame:
    """获取东方财富港股指数列表。"""
    return call_akshare(ak.stock_hk_index_spot_em)


def fetch_hk_index_daily(symbol: str) -> pd.DataFrame:
    """获取东方财富港股指数历史日线。"""
    return call_akshare(ak.stock_hk_index_daily_em, symbol=symbol)


def fetch_main_shareholders_sina_compat(ticker: str, max_periods: int = 8) -> pd.DataFrame:
    """以东财 F10 十大股东接口模拟新浪主股东列名，用于新浪主股东源失效时的无缝备选。"""
    full_code, _, _ = normalize_ticker(ticker)
    df = fetch_shareholders_dc(full_code, max_periods=max_periods)
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "report_date",
                "shareholder_name",
                "shareholding_amount",
                "shareholding_ratio",
                "share_type",
                "announcement_date",
            ]
        )
    out = pd.DataFrame()
    out["ticker"] = full_code
    out["report_date"] = df.get("END_DATE", pd.Series("", index=df.index)).astype(str).str[:10]
    out["shareholder_name"] = df.get("HOLDER_NAME", "")
    out["shareholding_amount"] = pd.to_numeric(df.get("HOLD_NUM"), errors="coerce")
    out["shareholding_ratio"] = pd.to_numeric(df.get("HOLD_NUM_RATIO"), errors="coerce")
    out["share_type"] = df.get("SHARES_TYPE", "")
    out["announcement_date"] = df.get("PUBLISH_DATE", pd.Series("", index=df.index)).astype(str).str[:10]
    return out.reset_index(drop=True)
