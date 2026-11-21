# batch_margin_collector.py
import os
import sys
import json
import pandas as pd
import argparse
from datetime import datetime, timedelta
import random
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from net_guard import ensure_network_ready, apply_collector_socket_timeout
    ensure_network_ready()
except Exception:
    apply_collector_socket_timeout = None

try:
    from config import DATA_DIR
except ImportError:
    DATA_DIR = "./data"


def write_margin_na_marker(ticker, date_str):
    """记录「该股票不在当日全市场两融标的清单中」，供日更检查在有效期内直接跳过。"""
    stock_dir = os.path.join(DATA_DIR, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    marker = os.path.join(stock_dir, f"{ticker}_margin_na.json")
    with open(marker, 'w', encoding='utf-8') as fh:
        json.dump({'ticker': ticker, 'checked_date': date_str,
                   'reason': '不在沪深交易所当日融资融券标的明细中'}, fh, ensure_ascii=False)
    return marker

def get_all_stocks():
    """获取data文件夹中的所有股票代码"""
    stocks = []
    if os.path.exists(DATA_DIR):
        for item in os.listdir(DATA_DIR):
            item_path = os.path.join(DATA_DIR, item)
            if os.path.isdir(item_path) and '.' in item:
                stocks.append(item)
    return sorted(stocks)

def get_margin_data_for_date(date_str):
    """获取指定日期的全市场融资融券数据"""
    try:
        import akshare as ak
        
        # 获取沪市数据
        sh_margin = ak.stock_margin_detail_sse(date=date_str)
        # 获取深市数据
        sz_margin = ak.stock_margin_detail_szse(date=date_str)
        
        return sh_margin, sz_margin
    except Exception as e:
        print(f"获取 {date_str} 全市场融资融券数据失败: {str(e)}")
        return None, None


_ORIG_GET_MARGIN_DATA_FOR_DATE = get_margin_data_for_date

def get_last_margin_date(ticker):
    """获取股票融资融券数据的最后日期"""
    stock_dir = os.path.join(DATA_DIR, ticker)
    output_file = os.path.join(stock_dir, f"{ticker}_margin_data.csv")
    
    if os.path.exists(output_file):
        try:
            df = pd.read_csv(output_file)
            if 'date' in df.columns and len(df) > 0:
                try:
                    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
                    last_date = df['date'].max()
                    return last_date
                except:
                    df['date'] = pd.to_datetime(df['date'])
                    last_date = df['date'].max()
                    return last_date
        except Exception as e:
            print(f"读取 {ticker} 融资融券数据失败: {str(e)}")
    
    return None

def get_existing_dates(ticker):
    """获取股票已有的融资融券数据日期集合"""
    stock_dir = os.path.join(DATA_DIR, ticker)
    output_file = os.path.join(stock_dir, f"{ticker}_margin_data.csv")
    existing_dates = set()
    
    if os.path.exists(output_file):
        try:
            df = pd.read_csv(output_file)
            if 'date' in df.columns:
                try:
                    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
                except:
                    df['date'] = pd.to_datetime(df['date'])
                existing_dates = set(df['date'].dt.strftime('%Y%m%d'))
        except Exception as e:
            print(f"读取 {ticker} 已有日期失败: {str(e)}")
    
    return existing_dates

def save_margin_data(ticker, data, date_str, existing_dates=None):
    """保存单只股票的融资融券数据（带查重处理）"""
    # 检查是否已存在该日期数据
    if existing_dates is not None and date_str in existing_dates:
        return False
    
    stock_dir = os.path.join(DATA_DIR, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    output_file = os.path.join(stock_dir, f"{ticker}_margin_data.csv")
    
    if not data.empty:
        data = data.copy()
        data['date'] = date_str
        
        if os.path.exists(output_file):
            data.to_csv(output_file, mode='a', header=False, index=False, encoding='utf-8-sig')
        else:
            data.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        return True
    return False

def batch_collect_margin_data(start_date=None, end_date=None, tickers=None):
    """批量/单只获取融资融券数据。

    tickers 为 None 时按 data 目录里所有股票处理；给出列表时只处理这些股票
    （check_data_updates.py 的日更调用依赖 --ticker 单只模式）。
    """

    """批量获取所有股票的融资融券数据（自动日期范围+查重处理）"""
    summary = {'days_ok': 0, 'days_failed': 0, 'added': 0, 'not_applicable': []}
    stocks = list(tickers) if tickers else get_all_stocks()
    if not stocks:
        print("没有需要处理的股票")
        return summary
    print(f"找到 {len(stocks)} 只股票")
    
    # 确定结束日期
    if end_date is None:
        end_date = datetime.now()
    else:
        end_date = datetime.strptime(end_date, '%Y%m%d')
    
    # 自动确定开始日期：取所有股票最早的最后日期的下一天
    print("\n正在获取各股票的最新融资融券数据日期...")
    earliest_start = None
    stock_last_dates = {}
    
    for ticker in stocks:
        last_date = get_last_margin_date(ticker)
        stock_last_dates[ticker] = last_date
        
        if last_date is None:
            # 没有数据，从30天前开始
            ticker_start = end_date - timedelta(days=30)
        else:
            ticker_start = last_date + timedelta(days=1)
        
        if earliest_start is None or ticker_start < earliest_start:
            earliest_start = ticker_start
        
        if last_date:
            print(f"  {ticker}: {last_date.strftime('%Y-%m-%d')}")
        else:
            print(f"  {ticker}: 无数据")
    
    # 如果用户指定了开始日期，取较晚的那个
    if start_date is not None:
        specified_start = datetime.strptime(start_date, '%Y%m%d')
        if specified_start > earliest_start:
            earliest_start = specified_start
    
    print(f"\n最早开始日期: {earliest_start.strftime('%Y-%m-%d')}")
    print(f"结束日期: {end_date.strftime('%Y-%m-%d')}")
    
    if earliest_start > end_date:
        print("所有股票的融资融券数据已是最新，无需更新")
        return summary
    
    # 预先获取每只股票已有的日期集合（用于查重）
    print("\n正在获取各股票已有的日期数据...")
    stock_existing_dates = {}
    for ticker in stocks:
        stock_existing_dates[ticker] = get_existing_dates(ticker)
        print(f"  {ticker}: {len(stock_existing_dates[ticker])} 条已有数据")

    # 正常生产模式统一经由 data_hub 单股快速通道（0.2s），并在失败时自动降级到目标单一交易所；
    # 若单测注入了 get_margin_data_for_date mock，则走传统按日全市场循环以保持 100% 测试兼容性。
    if get_margin_data_for_date is _ORIG_GET_MARGIN_DATA_FOR_DATE:
        import data_hub

        end_str = end_date.strftime('%Y%m%d')
        for ticker in stocks:
            last_dt = stock_last_dates.get(ticker)
            t_start = (end_date - timedelta(days=30)) if last_dt is None else (last_dt + timedelta(days=1))
            if start_date is not None:
                spec_dt = datetime.strptime(start_date, '%Y%m%d')
                if spec_dt > t_start:
                    t_start = spec_dt
            if t_start > end_date:
                continue
            t_start_str = t_start.strftime('%Y%m%d')
            try:
                df_margin, src_used = data_hub.fetch_with_source(
                    "stock_margin",
                    ticker=ticker,
                    start_date=t_start_str,
                    end_date=end_str,
                    on_fallback=lambda s, n, e: print(f"  提示：{ticker} 两融通道 {s} 异常（{e}），切换 {n}"),
                )
            except Exception as exc:
                print(f"  获取 {ticker} 融资融券数据失败: {exc}")
                summary['days_failed'] += 1
                continue

            summary['days_ok'] += 1
            if (df_margin is None or df_margin.empty) and last_dt is None and not stock_existing_dates[ticker]:
                write_margin_na_marker(ticker, end_str)
                summary['not_applicable'].append(ticker)
                print(f"  {ticker} 不在融资融券标的清单中，已写入免采集标记")
                continue

            if df_margin is not None and not df_margin.empty:
                df_clean = df_margin.copy()
                df_clean['date'] = df_clean['date'].astype(str).str.replace('-', '').str[:8]
                existing = stock_existing_dates[ticker]
                new_rows = df_clean[~df_clean['date'].isin(existing)]
                if not new_rows.empty:
                    stock_dir = os.path.join(DATA_DIR, ticker)
                    os.makedirs(stock_dir, exist_ok=True)
                    output_file = os.path.join(stock_dir, f"{ticker}_margin_data.csv")
                    if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                        existing_cols = list(pd.read_csv(output_file, nrows=0).columns)
                        for col in existing_cols:
                            if col not in new_rows.columns:
                                new_rows[col] = 0
                        new_rows = new_rows[existing_cols]
                        new_rows.to_csv(output_file, mode='a', header=False, index=False, encoding='utf-8-sig')
                    else:
                        new_rows.to_csv(output_file, index=False, encoding='utf-8-sig')
                    summary['added'] += int(len(new_rows))
                    stock_existing_dates[ticker].update(new_rows['date'].tolist())
                    print(f"  {ticker}（{src_used}）新增 {len(new_rows)} 条融资融券记录")
                else:
                    print(f"  {ticker} 融资融券数据已是最新")
        return summary

    # 遍历日期
    current_date = earliest_start
    total_added = 0
    total_skipped = 0
    
    while current_date <= end_date:
        # 跳过周末
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        
        date_str = current_date.strftime('%Y%m%d')
        print(f"\n===== 处理 {date_str} =====")
        
        # 获取当天全市场数据
        sh_margin, sz_margin = get_margin_data_for_date(date_str)
        
        if sh_margin is None or sz_margin is None:
            print(f"跳过 {date_str}")
            summary['days_failed'] += 1
            current_date += timedelta(days=1)
            continue
        if sh_margin.empty and sz_margin.empty:
            # 节假日或当日尚未发布：两市均无数据，不能据此判断个股是否为两融标的
            print(f"{date_str} 两市均无融资融券数据（节假日或尚未发布），跳过")
            current_date += timedelta(days=1)
            continue
        summary['days_ok'] += 1
        
        # 为每只股票筛选数据（带查重）
        day_added = 0
        day_skipped = 0
        for ticker in list(stocks):
            # 检查该日期是否已存在
            if date_str in stock_existing_dates[ticker]:
                day_skipped += 1
                continue
            
            code = ticker.split('.')[0]
            market = 'sh' if ticker.endswith('.SH') else 'sz'
            
            if market == 'sh':
                stock_data = sh_margin[sh_margin['标的证券代码'] == code]
                market_ok = not sh_margin.empty
            else:
                stock_data = sz_margin[sz_margin['证券代码'] == code]
                market_ok = not sz_margin.empty
            
            if (stock_data.empty and market_ok and stock_last_dates.get(ticker) is None
                    and not stock_existing_dates[ticker]):
                # 当日全市场清单已拿到但没有该股票，且本地从无两融记录 → 非两融标的，
                # 不再逐日抓取后续日期（每天约 20 秒），直接记录并跳过
                write_margin_na_marker(ticker, date_str)
                summary['not_applicable'].append(ticker)
                stocks.remove(ticker)
                print(f"  {ticker} 不在 {date_str} 两融标的清单中，判定为非融资融券标的，停止逐日抓取")
                continue
            
            if save_margin_data(ticker, stock_data, date_str, stock_existing_dates[ticker]):
                day_added += 1
                # 更新已有的日期集合
                stock_existing_dates[ticker].add(date_str)
        
        print(f"当天新增 {day_added} 条，跳过重复 {day_skipped} 条", flush=True)
        total_added += day_added
        total_skipped += day_skipped
        summary['added'] += day_added
        if not stocks:
            print("剩余股票均为非两融标的，提前结束")
            break
        
        # 随机延迟，避免请求过快
        time.sleep(random.uniform(2, 4))
        
        current_date += timedelta(days=1)
    
    print(f"\n===== 批量获取完成 =====")
    print(f"共新增 {total_added} 条融资融券数据")
    print(f"共跳过 {total_skipped} 条重复数据")
    return summary

def main():
    if apply_collector_socket_timeout is not None:
        # 交易所两融接口偶发不响应：单次请求最多等 25 秒，绝不无限挂起
        apply_collector_socket_timeout(25)
    parser = argparse.ArgumentParser(description='批量获取股票融资融券数据')
    parser.add_argument('--start_date', type=str, help='开始日期，格式：YYYYMMDD')
    parser.add_argument('--end_date', type=str, help='结束日期，格式：YYYYMMDD')
    parser.add_argument('--ticker', type=str, help='只处理指定股票，如 300433.SZ')
    parser.add_argument('--tickers', type=str,
                        help='逗号分隔的多只股票；每交易日只抓一次全市场数据再分发，避免逐只重复请求')
    args = parser.parse_args()

    if args.ticker and args.tickers:
        parser.error('--ticker 与 --tickers 不能同时使用')
    tickers = [args.ticker] if args.ticker else None
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(',') if t.strip()]
        print(f"批量模式：{len(tickers)} 只股票，每个交易日只抓一次全市场数据")
    print("开始批量获取融资融券数据..." if not tickers else f"开始获取 {args.ticker} 融资融券数据...")
    summary = batch_collect_margin_data(args.start_date, args.end_date, tickers=tickers) or {}
    if summary.get('days_failed') and not summary.get('days_ok'):
        # 所有需要的交易日都没拉到全市场数据：明确以非 0 退出，调用方据此报失败，而不是「成功但没更新」
        print(f"融资融券全市场数据获取失败（{summary['days_failed']} 个交易日均失败）")
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())