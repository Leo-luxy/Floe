# -*- coding: utf-8 -*-
"""
北向资金（陆股通）持股历史采集器
统一经由 data_hub 拉取，使用 config.DATA_DIR 管理落盘路径并按季度增量更新。
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


def save_to_csv(file_path, data, fieldnames, id_field):
    """去重增量写入 CSV 文件。"""
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
        key = str(row.get(id_field, ""))
        if key and key in seen:
            continue
        if key:
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


def should_fetch_data(last_date_str):
    """根据最后一次报告期判断本季度是否需要重新抓取（距今超过 80 天则刷新）。"""
    if not last_date_str:
        return True
    try:
        dt = pd.to_datetime(last_date_str, errors="coerce")
        if pd.isna(dt):
            return True
        return (datetime.now() - dt.to_pydatetime().replace(tzinfo=None)).days >= 80
    except Exception:
        return True


def get_last_date_from_file(file_path):
    """读取现有北向持股文件中的最新 TRADE_DATE。"""
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return None
    try:
        df = pd.read_csv(file_path)
        if not df.empty and "TRADE_DATE" in df.columns:
            return str(df["TRADE_DATE"].astype(str).max())
    except Exception:
        pass
    return None


def fetch_north_holdings(secucode, interval_type="001", page_size=200, save_path=None):
    """经由 data_hub 获取北向持股历史，返回记录列表或在指定 save_path 后落盘。"""
    _ = (interval_type, page_size)
    df = data_hub.fetch("stock_north_holdings", ticker=secucode)
    if df is None or df.empty:
        print(f"未获取到 {secucode} 的北向资金持股数据")
        return []

    records = df.to_dict(orient="records")
    if save_path:
        fieldnames = ["ticker"] + [c for c in df.columns if c != "ticker"]
        save_to_csv(save_path, records, fieldnames, "TRADE_DATE")
        print(f"北向持股数据已保存到: {save_path} ({len(records)} 条)")
    return records


def main():
    if apply_collector_socket_timeout is not None:
        apply_collector_socket_timeout(25)
    parser = argparse.ArgumentParser(description="采集股票北向资金持股数据")
    parser.add_argument("--ticker", type=str, help="指定股票代码，例如：300433.SZ")
    parser.add_argument("--interval-type", type=str, default="001", help="数据周期，001为季度，默认：001")
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
        save_path = os.path.join(stock_dir, f"{ticker}_north_holdings.csv")
        last_date = get_last_date_from_file(save_path)
        if not should_fetch_data(last_date):
            print(f"{ticker} 北向持股数据距上次报告期不足一季（{last_date}），跳过重复抓取")
            continue
        fetch_north_holdings(
            ticker,
            interval_type=args.interval_type,
            page_size=args.page_size,
            save_path=save_path,
        )


if __name__ == "__main__":
    main()
