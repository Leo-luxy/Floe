# -*- coding: utf-8 -*-
"""
补充重要缺失数据采集器（分红送转 + 机构盈利预测）
统一经由 data_hub 调度：全市场慢表自动复用 6 小时本地共享缓存，避免逐只重复下载。
"""

import argparse
import os
import sys
import traceback

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from net_guard import apply_collector_socket_timeout, ensure_network_ready

    ensure_network_ready()
except Exception:
    apply_collector_socket_timeout = None

try:
    from config import DATA_DIR, STOCK_TICKERS
except ImportError:
    DATA_DIR = "./data"
    STOCK_TICKERS = []

import data_hub


def get_stock_ex_dividend_data(ticker):
    """获取历史分红除权信息，保存到 {ticker}_ex_dividend.csv。"""
    print(f"正在获取 {ticker} 历史分红数据...")
    stock_dir = os.path.join(DATA_DIR, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    output_file = os.path.join(stock_dir, f"{ticker}_ex_dividend.csv")
    try:
        df = data_hub.fetch("stock_ex_dividend", ticker=ticker)
        if df is not None and not df.empty:
            df.to_csv(output_file, index=False, encoding="utf-8-sig")
            print(f"分红数据已保存到: {output_file} ({len(df)} 条)")
            return df
        print(f"未找到 {ticker} 的分红数据")
        return None
    except Exception as exc:
        print(f"获取 {ticker} 分红数据失败: {exc}")
        traceback.print_exc()
        return None


def get_stock_b龙虎榜_data(ticker):
    """获取龙虎榜数据（保留接口兼容）。"""
    print(f"跳过 {ticker} 龙虎榜独立抓取（如需扩展请在 data_hub 注册能力）")
    return None


def get_stock_insider_trading_data(ticker):
    """获取高管增减持数据（保留接口兼容）。"""
    print(f"跳过 {ticker} 高管增减持独立抓取（如需扩展请在 data_hub 注册能力）")
    return None


def get_stock_业绩预告_data(ticker):
    """获取机构盈利预测（东方财富全市场共享缓存 + 同花顺单股接口）。"""
    print(f"正在获取 {ticker} 盈利预测数据...")
    stock_dir = os.path.join(DATA_DIR, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    result_df = None

    try:
        em_df = data_hub.fetch("stock_profit_forecast_em", ticker=ticker)
        if em_df is not None and not em_df.empty:
            out_em = os.path.join(stock_dir, f"{ticker}_performance_forecast.csv")
            em_df.to_csv(out_em, index=False, encoding="utf-8-sig")
            print(f"东财盈利预测已保存到: {out_em} ({len(em_df)} 条)")
            result_df = em_df
    except Exception as exc:
        print(f"获取 {ticker} 东财盈利预测失败: {exc}")

    try:
        ths_df = data_hub.fetch("stock_profit_forecast_ths", ticker=ticker)
        if ths_df is not None and not ths_df.empty:
            out_ths = os.path.join(stock_dir, f"{ticker}_performance_forecast_ths.csv")
            ths_df.to_csv(out_ths, index=False, encoding="utf-8-sig")
            print(f"同花顺盈利预测已保存到: {out_ths} ({len(ths_df)} 条)")
            if result_df is None:
                result_df = ths_df
    except Exception as exc:
        print(f"获取 {ticker} 同花顺盈利预测失败: {exc}")

    return result_df


def get_stock_important_missing_data(ticker):
    """获取指定股票的全部补充缺失数据。"""
    print(f"\n===== 开始采集 {ticker} 补充基础数据 =====")
    return {
        "ex_dividend": get_stock_ex_dividend_data(ticker),
        "profit_forecast": get_stock_业绩预告_data(ticker),
    }


def main():
    if apply_collector_socket_timeout is not None:
        apply_collector_socket_timeout(25)
    parser = argparse.ArgumentParser(description="采集分红与盈利预测等补充基础数据")
    parser.add_argument("--ticker", type=str, help="指定股票代码，例如：300433.SZ")
    args = parser.parse_args()

    tickers = [args.ticker] if args.ticker else [
        (t[0] if isinstance(t, (list, tuple)) else t) for t in STOCK_TICKERS
    ]
    if not tickers and os.path.isdir(DATA_DIR):
        tickers = sorted(
            d for d in os.listdir(DATA_DIR)
            if os.path.isdir(os.path.join(DATA_DIR, d)) and "." in d
        )

    for t in tickers:
        get_stock_important_missing_data(t)
    print("\n补充数据采集完成！")


if __name__ == "__main__":
    main()
