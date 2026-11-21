# -*- coding: utf-8 -*-
"""
股东户数变化采集器
统一经由 data_hub 拉取东财 F10 股东户数，按需补充 detail 表，消除重复请求与长延时。
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
    """增量合并写入 CSV 并按日期键去重。"""
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
    """股东户数通常至少隔 7 天以上才可能披露新期，若已是近期则减少无谓拉取。"""
    if not last_date_str:
        return True
    try:
        dt = pd.to_datetime(last_date_str, errors="coerce")
        if pd.isna(dt):
            return True
        return (datetime.now() - dt.to_pydatetime().replace(tzinfo=None)).days >= 7
    except Exception:
        return True


def get_last_date_from_file(file_path):
    """读取股东户数 CSV 最新截止日期。"""
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return None
    try:
        df = pd.read_csv(file_path)
        for col in ("END_DATE", "股东户数统计截止日"):
            if col in df.columns and not df.empty:
                return str(df[col].astype(str).max())[:10]
    except Exception:
        pass
    return None


def fetch_shareholder_num(secucode, page_size=200, save_path=None):
    """经由 data_hub 拉取东财 F10 股东户数历史。"""
    _ = page_size
    df = data_hub.fetch("stock_shareholder_num", ticker=secucode)
    if df is None or df.empty:
        print(f"未获取到 {secucode} 的股东户数数据")
        return []

    records = df.to_dict(orient="records")
    if save_path:
        save_to_csv(save_path, records, list(df.columns), "END_DATE")
        print(f"股东户数数据已保存到: {save_path} ({len(records)} 条)")
    return records


def fetch_shareholder_num_akshare(code, save_path=None):
    """经由 data_hub 拉取股东户数详情补充表。"""
    df = data_hub.fetch("stock_shareholder_num_detail", ticker=code)
    if df is None or df.empty:
        return []
    records = df.to_dict(orient="records")
    if save_path:
        save_to_csv(save_path, records, list(df.columns), "股东户数统计截止日")
        print(f"股东户数补充详情已保存到: {save_path} ({len(records)} 条)")
    return records


def main():
    if apply_collector_socket_timeout is not None:
        apply_collector_socket_timeout(25)
    parser = argparse.ArgumentParser(description="采集股票股东户数历史数据")
    parser.add_argument("--ticker", type=str, help="指定股票代码，例如：300433.SZ")
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
        save_path_eastmoney = os.path.join(stock_dir, f"{ticker}_shareholder_num.csv")
        last_em = get_last_date_from_file(save_path_eastmoney)
        if should_fetch_data(last_em):
            fetch_shareholder_num(ticker, page_size=args.page_size, save_path=save_path_eastmoney)
        else:
            print(f"{ticker} 股东户数主表距上次更新不足 7 天（{last_em}），跳过重复抓取")

        # 补充详情表仅在不存在或已有期次滞后主表时才请求，避免每次双倍访问东财
        save_path_info = os.path.join(stock_dir, f"{ticker}_shareholder_num_info.csv")
        last_info = get_last_date_from_file(save_path_info)
        if not os.path.exists(save_path_info) or should_fetch_data(last_info):
            try:
                fetch_shareholder_num_akshare(ticker.split(".")[0], save_path=save_path_info)
            except Exception as exc:
                print(f"补充 {ticker} 股东户数详情失败（可忽略）: {exc}")


if __name__ == "__main__":
    main()
