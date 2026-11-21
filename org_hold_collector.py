# -*- coding: utf-8 -*-
"""
机构持股明细采集器
统一经由 data_hub 动态探测最新可用报告期，不再写死历史年份或硬编码相对目录。
"""

import argparse
import csv
import os
import sys

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
    """安全合并写入 CSV 文件并按 id_field 去重。"""
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
        key = (str(row.get("REPORT_DATE", "")), str(row.get(id_field, "")))
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)

    all_fieldnames = list(fieldnames)
    for row in merged:
        for key in row.keys():
            if key not in all_fieldnames:
                all_fieldnames.append(key)

    with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_fieldnames)
        writer.writeheader()
        writer.writerows(merged)


def fetch_org_hold_detail(
    secucode,
    report_date=None,
    org_type="01",
    page_size=200,
    save_path="org_hold_detail.csv",
):
    """经由 data_hub 获取指定股票最新可用报告期（或指定报告期）的机构持股明细。"""
    _ = page_size
    df = data_hub.fetch("stock_org_holdings", ticker=secucode, report_date=report_date)
    if df is None or df.empty:
        print(f"未获取到 {secucode} 的机构持股数据")
        return []

    if org_type and "ORG_TYPE" in df.columns:
        filtered = df[df["ORG_TYPE"].astype(str) == str(org_type)]
        if not filtered.empty:
            df = filtered

    records = df.to_dict(orient="records")
    default_fields = [
        "ORG_TYPE",
        "SECUCODE",
        "REPORT_DATE",
        "HOLDER_CODE",
        "HOLDER_NAME",
        "TOTAL_SHARES",
        "HOLD_VALUE",
        "TOTALSHARES_RATIO",
        "FREESHARES_RATIO",
        "FREE_MARKET_CAP",
        "FREE_SHARES",
        "SECURITY_CODE",
        "FUND_CODE",
        "FUND_DERIVECODE",
        "NETVALUE_RATIO",
    ]
    fieldnames = default_fields + [c for c in df.columns if c not in default_fields]

    if save_path:
        save_to_csv(save_path, records, fieldnames, "HOLDER_CODE")
        print(f"机构持股明细已保存: {save_path} ({len(records)} 条)")
    return records


def main():
    if apply_collector_socket_timeout is not None:
        apply_collector_socket_timeout(25)
    parser = argparse.ArgumentParser(description="采集股票机构持股明细数据")
    parser.add_argument("--ticker", type=str, help="指定股票代码，例如：002594.SZ")
    parser.add_argument(
        "--report-date",
        type=str,
        default=None,
        help="报告日期（YYYY-MM-DD）；默认自动探测最新可用报告期",
    )
    parser.add_argument("--org-type", type=str, default="01", help="机构类型，默认：01")
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
        save_path = os.path.join(stock_dir, f"{ticker}_institutional_holdings.csv")
        fetch_org_hold_detail(
            ticker,
            report_date=args.report_date,
            org_type=args.org_type,
            page_size=args.page_size,
            save_path=save_path,
        )


if __name__ == "__main__":
    main()
