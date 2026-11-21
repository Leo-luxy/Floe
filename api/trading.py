# api/trading.py
# 买卖记录台账与历史/持仓收益核算 API
import csv
import json
import os
import re
import sys
import urllib.request
from flask import Blueprint, jsonify, request

from .common import get_exchange_suffix

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

trading_bp = Blueprint('trading', __name__)
try:
    import app_paths as _ap
    TRADING_RECORDS_FILE = _ap.get_trading_records_file()
    DATA_DIR = _ap.get_data_dir()
except Exception:
    TRADING_RECORDS_FILE = os.path.join(project_root, 'trading_records.py')
    DATA_DIR = os.path.join(project_root, 'data')


def _load_records_dict():
    """直接读取 TRADING_RECORDS_FILE，不存在时返回空字典。"""
    if not os.path.isfile(TRADING_RECORDS_FILE):
        return {}
    ns = {}
    with open(TRADING_RECORDS_FILE, 'r', encoding='utf-8') as fh:
        exec(fh.read(), ns)
    raw = ns.get('TRADING_RECORDS') or {}
    return {str(k): list(v or []) for k, v in raw.items()}


def _save_records_dict(records_dict):
    """格式化保存 TRADING_RECORDS 到 trading_records.py。"""
    lines = [
        '# trading_records.py',
        '# 交易记录配置',
        '',
        'TRADING_RECORDS = {',
    ]
    for stock, records in records_dict.items():
        if not records:
            continue
        lines.append(f"    '{stock}': [")
        for idx, rec in enumerate(records):
            comma = ',' if idx < len(records) - 1 else ''
            lines.append(
                f"        {{'date': '{rec['date']}', 'type': '{rec['type']}', "
                f"'price': {round(float(rec['price']), 3)}, 'shares': {int(rec['shares'])}}}{comma}"
            )
        lines.append('    ],')
    lines.append('}\n')
    with open(TRADING_RECORDS_FILE, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))


def _resolve_latest_quote(ticker, allow_remote=True):
    """获取股票简称与最新现价（优先实时行情，回退本地最新前复权收盘价）。"""
    name = ''
    price = None
    source = ''

    # 1. 本地简称（watchlist / company_basic）
    try:
        from api.watchlist import load_watchlist
        for item in load_watchlist():
            if item[0] == ticker and len(item) > 1 and item[1]:
                name = str(item[1]).strip()
                break
    except Exception:
        pass

    if not name:
        basic_file = os.path.join(DATA_DIR, ticker, f'{ticker}_company_basic.json')
        if os.path.isfile(basic_file):
            try:
                with open(basic_file, 'r', encoding='utf-8') as fh:
                    info = json.load(fh).get('basic_info', {})
                    name = str(info.get('公司简称') or info.get('股票简称') or '').strip()
            except Exception:
                pass

    # 2. 尝试轻量实时行情（东方财富 push2 fltt=2，停牌或集合竞价前取昨收 f60）
    if allow_remote and re.fullmatch(r'\d{6}\.(SH|SZ)', ticker):
        code6, market = ticker.split('.')
        secid = f"{'1' if market == 'SH' else '0'}.{code6}"
        url = f'https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fltt=2&invt=2&fields=f43,f58,f60'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = (json.loads(resp.read().decode('utf-8', errors='ignore')).get('data') or {})
            if not name and data.get('f58') and data.get('f58') != '-':
                name = str(data['f58']).strip()
            for field, tag in (('f43', '实时现价'), ('f60', '昨收价')):
                val = data.get(field)
                if val is not None and val != '-':
                    fval = float(val)
                    if fval > 0:
                        price = fval
                        source = tag
                        break
        except Exception:
            pass

    # 3. 回退本地 qfq.csv 最后一行收盘价
    if price is None:
        qfq_file = os.path.join(DATA_DIR, ticker, f'{ticker}_qfq.csv')
        if os.path.isfile(qfq_file):
            try:
                last_row = None
                with open(qfq_file, 'r', encoding='utf-8-sig') as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        last_row = row
                if last_row and last_row.get('close'):
                    cval = float(last_row['close'])
                    if cval > 0:
                        price = cval
                        dt = str(last_row.get('date') or '')[:10]
                        source = f'本地收盘({dt})' if dt else '本地收盘'
            except Exception:
                pass

    return name, price, source


def compute_stock_fifo_pnl(ticker, records, latest_price=None, stock_name='', price_source=''):
    """按 FIFO（先进先出）逐手核算单只股票的历史已实现收益与当前持仓浮动收益。"""
    indexed = []
    for idx, rec in enumerate(records or []):
        try:
            t_type = str(rec.get('type') or '').strip().lower()
            t_date = str(rec.get('date') or '').strip()
            t_price = round(float(rec.get('price') or 0), 3)
            t_shares = int(rec.get('shares') or 0)
            if t_type in ('buy', 'sell') and t_price > 0 and t_shares > 0:
                indexed.append((t_date, idx, t_type, t_price, t_shares))
        except (TypeError, ValueError):
            continue

    indexed.sort(key=lambda item: (item[0], item[1]))

    open_queue = []  # [{'buy_date', 'buy_price', 'shares'}]
    closed_lots = []
    total_buy_cost = 0.0

    for t_date, _idx, t_type, t_price, t_shares in indexed:
        if t_type == 'buy':
            total_buy_cost += t_price * t_shares
            open_queue.append({
                'buy_date': t_date,
                'buy_price': t_price,
                'shares': t_shares,
            })
        elif t_type == 'sell':
            rem = t_shares
            while rem > 0 and open_queue:
                head = open_queue[0]
                matched = min(rem, head['shares'])
                cost = matched * head['buy_price']
                proceeds = matched * t_price
                pnl = proceeds - cost
                ret_pct = ((t_price - head['buy_price']) / head['buy_price'] * 100.0) if head['buy_price'] > 0 else 0.0
                closed_lots.append({
                    'status': 'closed',
                    'buy_date': head['buy_date'],
                    'buy_price': round(head['buy_price'], 3),
                    'sell_date': t_date,
                    'sell_price': round(t_price, 3),
                    'shares': matched,
                    'cost': round(cost, 2),
                    'value': round(proceeds, 2),
                    'pnl': round(pnl, 2),
                    'return_pct': round(ret_pct, 2),
                })
                head['shares'] -= matched
                rem -= matched
                if head['shares'] <= 0:
                    open_queue.pop(0)
            if rem > 0:
                closed_lots.append({
                    'status': 'unmatched_sell',
                    'buy_date': '缺少前序买入',
                    'buy_price': 0.0,
                    'sell_date': t_date,
                    'sell_price': round(t_price, 3),
                    'shares': rem,
                    'cost': 0.0,
                    'value': round(rem * t_price, 2),
                    'pnl': 0.0,
                    'return_pct': 0.0,
                })

    holding_shares = sum(lot['shares'] for lot in open_queue)
    holding_cost_sum = sum(lot['shares'] * lot['buy_price'] for lot in open_queue)
    avg_hold_cost = (holding_cost_sum / holding_shares) if holding_shares > 0 else 0.0

    # 若仍在持仓但外部无现价，用最近一笔成交价兜底避免断算
    effective_price = latest_price
    effective_source = price_source
    if holding_shares > 0 and (effective_price is None or effective_price <= 0):
        effective_price = indexed[-1][3] if indexed else avg_hold_cost
        effective_source = '最近成交价兜底'

    open_lots = []
    for lot in open_queue:
        if lot['shares'] <= 0:
            continue
        cur_p = float(effective_price or lot['buy_price'])
        cost = lot['shares'] * lot['buy_price']
        val = lot['shares'] * cur_p
        pnl = val - cost
        ret_pct = ((cur_p - lot['buy_price']) / lot['buy_price'] * 100.0) if lot['buy_price'] > 0 else 0.0
        open_lots.append({
            'status': 'open',
            'buy_date': lot['buy_date'],
            'buy_price': round(lot['buy_price'], 3),
            'sell_date': '持仓中',
            'sell_price': round(cur_p, 3),
            'shares': lot['shares'],
            'cost': round(cost, 2),
            'value': round(val, 2),
            'pnl': round(pnl, 2),
            'return_pct': round(ret_pct, 2),
        })

    realized_pnl = sum(l['pnl'] for l in closed_lots if l['status'] == 'closed')
    unrealized_pnl = sum(l['pnl'] for l in open_lots)
    total_pnl = realized_pnl + unrealized_pnl
    market_value = sum(l['value'] for l in open_lots)
    total_return_pct = (total_pnl / total_buy_cost * 100.0) if total_buy_cost > 0 else 0.0

    all_lots = []
    for idx, lot in enumerate(closed_lots + open_lots, start=1):
        entry = dict(lot)
        entry['lot_no'] = idx
        all_lots.append(entry)

    return {
        'ticker': ticker,
        'code6': ticker.split('.')[0],
        'name': stock_name or '',
        'holding_shares': holding_shares,
        'avg_hold_cost': round(avg_hold_cost, 3),
        'latest_price': round(float(effective_price), 3) if effective_price else None,
        'price_source': effective_source if holding_shares > 0 else '已清仓',
        'market_value': round(market_value, 2),
        'total_buy_cost': round(total_buy_cost, 2),
        'realized_pnl': round(realized_pnl, 2),
        'unrealized_pnl': round(unrealized_pnl, 2),
        'total_pnl': round(total_pnl, 2),
        'total_return_pct': round(total_return_pct, 2),
        'lot_count': len(all_lots),
        'lots': all_lots,
    }


@trading_bp.route('/trading_records/<stock_code>')
def get_trading_records(stock_code):
    """获取单只股票的交易记录"""
    clean = str(stock_code or '').strip().upper()
    full_stock_code = clean if re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', clean) else clean + get_exchange_suffix(clean)
    try:
        records_dict = _load_records_dict()
        records = records_dict.get(full_stock_code, [])
        return jsonify({
            'success': True,
            'records': records,
            'stock_code': full_stock_code,
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'获取交易记录失败：{str(e)}',
        })


@trading_bp.route('/trading_portfolio_summary')
def get_trading_portfolio_summary():
    """汇总全部已记账股票的总收益、分股收益及逐手（FIFO）盈亏明细。"""
    allow_remote = request.args.get('offline') != '1'
    try:
        records_dict = _load_records_dict()
        stocks_summary = []
        for ticker, recs in records_dict.items():
            if not recs:
                continue
            has_net_pos = sum((1 if r.get('type') == 'buy' else -1) * int(r.get('shares') or 0) for r in recs) > 0
            name, latest_price, source = _resolve_latest_quote(
                ticker, allow_remote=(allow_remote and has_net_pos)
            )
            item = compute_stock_fifo_pnl(
                ticker=ticker,
                records=recs,
                latest_price=latest_price,
                stock_name=name,
                price_source=source,
            )
            stocks_summary.append(item)

        # 持仓中排前面，再按总盈亏金额降序排列
        stocks_summary.sort(key=lambda s: (0 if s['holding_shares'] > 0 else 1, -s['total_pnl']))

        grand_realized = round(sum(s['realized_pnl'] for s in stocks_summary), 2)
        grand_unrealized = round(sum(s['unrealized_pnl'] for s in stocks_summary), 2)
        grand_total_pnl = round(grand_realized + grand_unrealized, 2)
        grand_buy_cost = round(sum(s['total_buy_cost'] for s in stocks_summary), 2)
        grand_market_val = round(sum(s['market_value'] for s in stocks_summary), 2)
        grand_ret_pct = round((grand_total_pnl / grand_buy_cost * 100.0), 2) if grand_buy_cost > 0 else 0.0
        holding_count = sum(1 for s in stocks_summary if s['holding_shares'] > 0)

        return jsonify({
            'success': True,
            'portfolio': {
                'total_pnl': grand_total_pnl,
                'realized_pnl': grand_realized,
                'unrealized_pnl': grand_unrealized,
                'holding_market_value': grand_market_val,
                'total_buy_cost': grand_buy_cost,
                'total_return_pct': grand_ret_pct,
                'holding_stock_count': holding_count,
                'total_stock_count': len(stocks_summary),
            },
            'stocks': stocks_summary,
        })
    except Exception as exc:
        return jsonify({'success': False, 'message': f'计算历史收益失败：{exc}'})


@trading_bp.route('/add_trading_record', methods=['POST'])
def add_trading_record():
    """添加交易记录"""
    data = request.get_json(silent=True) or {}
    stock_code = str(data.get('stock_code', '')).strip()
    date = str(data.get('date', '')).strip()
    trade_type = str(data.get('type', '')).strip()
    try:
        price = round(float(data.get('price', 0)), 3)
        shares = int(data.get('shares', 0))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '价格与股数格式不正确'})

    if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
        return jsonify({'success': False, 'message': '请输入6位数字的股票代码'})

    if not date or trade_type not in ('buy', 'sell') or price <= 0 or shares <= 0:
        return jsonify({'success': False, 'message': '请填写完整的交易信息'})

    full_stock_code = stock_code + get_exchange_suffix(stock_code)
    try:
        records_dict = _load_records_dict()
        records_dict.setdefault(full_stock_code, []).append({
            'date': date,
            'type': trade_type,
            'price': price,
            'shares': shares,
        })
        _save_records_dict(records_dict)
        return jsonify({
            'success': True,
            'message': '交易记录添加成功',
            'stock_code': full_stock_code,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'添加交易记录失败：{str(e)}'})


@trading_bp.route('/delete_trading_record', methods=['POST'])
def delete_trading_record():
    """按索引删除某只股票的一条交易记录"""
    data = request.get_json(silent=True) or {}
    raw_code = str(data.get('stock_code', '')).strip().upper()
    index = data.get('index')
    if not raw_code or not isinstance(index, int):
        return jsonify({'success': False, 'message': '参数不完整'})

    full_code = raw_code if re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', raw_code) else raw_code + get_exchange_suffix(raw_code)
    try:
        records_dict = _load_records_dict()
        recs = records_dict.get(full_code, [])
        if index < 0 or index >= len(recs):
            return jsonify({'success': False, 'message': '未找到指定的交易记录'})
        recs.pop(index)
        if not recs:
            records_dict.pop(full_code, None)
        _save_records_dict(records_dict)
        return jsonify({'success': True, 'message': '已删除该条成交记录'})
    except Exception as exc:
        return jsonify({'success': False, 'message': f'删除失败：{exc}'})
