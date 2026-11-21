# -*- coding: utf-8 -*-
"""
历史前十大股东采集器
统一经由 data_hub 一次拉取最近多期十大股东记录并按 config.DATA_DIR 落盘。
"""

import argparse
import csv
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from net_guard import apply_collector_socket_timeout, ensure_network_ready

    ensure_network_ready()
except Exception:
    apply_collector_socket_timeout = None

try:
    from config import DATA_DIR
except ImportError:
    DATA_DIR = "./data"

import data_hub


def get_latest_quarter_end():
    """返回当前日期之前最近的季度末日期（YYYY-MM-DD）。"""
    now = datetime.now()
    y = now.year
    for dt_str in (f"{y}-12-31", f"{y}-09-30", f"{y}-06-30", f"{y}-03-31", f"{y - 1}-12-31"):
        if dt_str <= now.strftime("%Y-%m-%d"):
            return dt_str
    return f"{y - 1}-12-31"


def get_next_quarter(date_str):
    """计算指定季末日期的下一个季末日期。"""
    dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
    m = dt.month
    y = dt.year
    if m == 3:
        return f"{y}-06-30"
    if m == 6:
        return f"{y}-09-30"
    if m == 9:
        return f"{y}-12-31"
    return f"{y + 1}-03-31"


def get_last_end_date(save_path):
    """从已有历史股东文件读取最新报告期 END_DATE。"""
    if not os.path.exists(save_path) or os.path.getsize(save_path) == 0:
        return None
    try:
        df = pd.read_csv(save_path)
        if not df.empty and "END_DATE" in df.columns:
            return str(df["END_DATE"].astype(str).max())[:10]
    except Exception:
        pass
    return None


def save_to_csv(file_path, data, fieldnames, id_field):
    """增量去重保存股东列表 CSV。"""
    if not data:
        return
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    existing_data = []
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                existing_data = list(csv.DictReader(f))
        except Exception:
            existing_data = []

    seen = set()
    merged = []
    for row in existing_data + list(data):
        key = (str(row.get("END_DATE", ""))[:10], str(row.get(id_field, "")))
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)

    all_fieldnames = list(fieldnames)
    for row in merged:
        for k in row.keys():
            if k not in all_fieldnames:
                all_fieldnames.append(k)

    with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_fieldnames)
        writer.writeheader()
        writer.writerows(merged)


def fetch_shareholders_data(secucode, end_date=None, start_date=None, page_size=200, save_path=None):
    """经由 data_hub 拉取历史十大股东并按起止日期过滤保存。"""
    _ = page_size
    df = data_hub.fetch("stock_shareholders", ticker=secucode)
    if df is None or df.empty:
        print(f"未获取到 {secucode} 的历史十大股东数据")
        return None if save_path is None else []

    if "END_DATE" in df.columns:
        df = df.copy()
        end_dates = df["END_DATE"].astype(str).str[:10]
        if start_date:
            df = df[end_dates >= str(start_date)[:10]]
            end_dates = df["END_DATE"].astype(str).str[:10]
        if end_date:
            df = df[end_dates <= str(end_date)[:10]]

    if df.empty:
        print(f"{secucode} 在指定区间内无新增股东记录")
        return pd.DataFrame() if save_path is None else []

    if save_path:
        records = df.to_dict(orient="records")
        save_to_csv(save_path, records, list(df.columns), "HOLDER_NAME")
        print(f"前十大股东数据已保存到: {save_path} ({len(records)} 条)")
        return records
    return df


def main():
    if apply_collector_socket_timeout is not None:
        apply_collector_socket_timeout(25)
    parser = argparse.ArgumentParser(description="采集股票历史前十大股东数据")
    parser.add_argument("--ticker", type=str, help="指定股票代码，例如：002384.SZ")
    parser.add_argument("--end-date", type=str, help="截止日期，例如：2025-09-30")
    parser.add_argument("--start-date", type=str, help="开始日期，例如：2024-01-01")
    parser.add_argument("--page-size", type=int, default=200, help="每页大小，默认：200")
    args = parser.parse_args()

    if args.ticker:
        tickers = [args.ticker]
    elif os.path.isdir(DATA_DIR):
        tickers = sorted(
            d for d in os.listdir(DATA_DIR)
            if os.path.isdir(os.path.join(DATA_DIR, d)) and "." in d
        )
    else:
        tickers = []

    for ticker in tickers:
        stock_dir = os.path.join(DATA_DIR, ticker)
        os.makedirs(stock_dir, exist_ok=True)
        save_path = os.path.join(stock_dir, f"{ticker}_historical_shareholders.csv")
        last_date = get_last_end_date(save_path)
        eff_start = args.start_date
        if not eff_start and last_date:
            next_q = get_next_quarter(last_date)
            if next_q <= (args.end_date or get_latest_quarter_end()):
                eff_start = next_q
            else:
                print(f"{ticker} 前十大股东已是最新报告期（{last_date}），跳过请求")
                continue
        fetch_shareholders_data(
            ticker,
            end_date=args.end_date,
            start_date=eff_start,
            page_size=args.page_size,
            save_path=save_path,
        )


if __name__ == "__main__":
    main()
