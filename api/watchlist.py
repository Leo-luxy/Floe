from flask import Blueprint, request, jsonify
import glob
import json
import os
import re
import sys
import urllib.request

watchlist_bp = Blueprint('watchlist', __name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    import app_paths as _ap
    WATCHLIST_FILE = _ap.get_watchlist_file()
    DATA_DIR = _ap.get_data_dir()
except Exception:
    WATCHLIST_FILE = os.path.join(PROJECT_ROOT, 'watchlist.py')
    DATA_DIR = os.path.join(PROJECT_ROOT, 'data')


def normalize_stock_code(stock_code):
    """标准化股票代码，自动添加市场后缀"""
    stock_code = stock_code.strip().upper()
    if re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', stock_code):
        return stock_code
    digits = re.sub(r'\D', '', stock_code)
    if len(digits) == 6:
        if digits.startswith(('60', '68')):
            return digits + '.SH'
        if digits.startswith(('00', '30')):
            return digits + '.SZ'
        if digits.startswith(('4', '8', '9')):
            return digits + '.BJ'
    return stock_code


def resolve_stock_name(normalized_code, allow_remote=True):
    """尝试从本地已采集元数据补全股票简称，缺失时可选做轻量行情简称查询。"""
    # 1. 本地 company_basic.json
    company_file = os.path.join(DATA_DIR, normalized_code, f'{normalized_code}_company_basic.json')
    if os.path.isfile(company_file):
        try:
            with open(company_file, 'r', encoding='utf-8') as f:
                info = json.load(f).get('basic_info', {})
                name = (info.get('公司简称') or info.get('股票简称') or '').strip()
                if name and name != normalized_code:
                    return name
        except Exception:
            pass

    # 2. 本地回测汇总 CSV 中已有的简称
    try:
        for csv_path in sorted(glob.glob(os.path.join(DATA_DIR, 'backtest_results_*.csv')), reverse=True)[:4]:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    if line.startswith(normalized_code + ','):
                        parts = line.strip().split(',')
                        if len(parts) >= 2 and parts[1] and parts[1] != normalized_code:
                            return parts[1].strip()
    except Exception:
        pass

    # 3. 轻量东方财富简称接口（1.2s 超时，失败静默退回空字符串，不阻塞离线场景）
    if allow_remote and re.fullmatch(r'\d{6}\.(SH|SZ)', normalized_code):
        code6, market = normalized_code.split('.')
        secid = f"{'1' if market == 'SH' else '0'}.{code6}"
        url = f'https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f58'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                payload = json.loads(resp.read().decode('utf-8', errors='ignore'))
                name = str((payload.get('data') or {}).get('f58') or '').strip()
                if name and name != '-':
                    return name
        except Exception:
            pass

    return ''


def load_watchlist():
    """加载关注列表（直接执行 watchlist.py 文件避免跨目录缓存冲突）"""
    if os.path.exists(WATCHLIST_FILE):
        try:
            ns = {}
            with open(WATCHLIST_FILE, 'r', encoding='utf-8') as fh:
                exec(fh.read(), ns)
            if isinstance(ns.get('WATCHLIST'), list):
                return list(ns['WATCHLIST'])
        except Exception as e:
            print(f"加载关注列表失败: {e}")
    return []


def save_watchlist(watchlist_items):
    """保存关注列表到文件，每行一只股票"""
    lines = [
        '# 关注股票列表',
        '# 格式: [(\'股票代码\', \'股票名称\'), ...]',
        '',
        'WATCHLIST = ['
    ]

    for i, item in enumerate(watchlist_items):
        code = str(item[0]).replace("'", "")
        name = str(item[1] if len(item) > 1 and item[1] else '').replace("'", "")
        line = f"    ('{code}', '{name}')"
        if i < len(watchlist_items) - 1:
            line += ','
        lines.append(line)

    lines.append(']')

    content = '\n'.join(lines) + '\n'
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    return True


@watchlist_bp.route('/watchlist/get', methods=['GET'])
def get_watchlist():
    """获取关注列表"""
    watchlist = load_watchlist()
    return jsonify({'success': True, 'data': watchlist})


@watchlist_bp.route('/watchlist/add', methods=['POST'])
def add_to_watchlist():
    """添加股票到关注列表（未提供简称时自动尝试补全）"""
    data = request.get_json(silent=True) or {}
    stock_code = str(data.get('stock_code', '')).strip()
    stock_name = str(data.get('stock_name', '')).strip()

    if not stock_code:
        return jsonify({'success': False, 'message': '股票代码不能为空'})

    normalized_code = normalize_stock_code(stock_code)
    watchlist = load_watchlist()

    for item in watchlist:
        if item[0] == normalized_code:
            return jsonify({'success': False, 'message': '该股票已在关注列表中', 'data': watchlist})

    if not stock_name:
        stock_name = resolve_stock_name(normalized_code)

    watchlist.append((normalized_code, stock_name))
    save_watchlist(watchlist)

    return jsonify({
        'success': True,
        'message': '添加成功',
        'added': {'code': normalized_code, 'name': stock_name},
        'data': watchlist
    })


@watchlist_bp.route('/watchlist/update_name', methods=['POST'])
def update_watchlist_name():
    """更新关注列表中某只股票的名称"""
    data = request.get_json(silent=True) or {}
    stock_code = str(data.get('stock_code', '')).strip()
    stock_name = str(data.get('stock_name', '')).strip()
    if not stock_code:
        return jsonify({'success': False, 'message': '股票代码不能为空'})

    normalized_code = normalize_stock_code(stock_code)
    watchlist = load_watchlist()
    updated = False
    new_watchlist = []
    for item in watchlist:
        if item[0] == normalized_code:
            final_name = stock_name or resolve_stock_name(normalized_code)
            new_watchlist.append((normalized_code, final_name))
            updated = True
        else:
            new_watchlist.append(item)

    if not updated:
        return jsonify({'success': False, 'message': '该股票不在关注列表中'})

    save_watchlist(new_watchlist)
    return jsonify({'success': True, 'message': '名称已更新', 'data': new_watchlist})


@watchlist_bp.route('/watchlist/remove', methods=['POST'])
def remove_from_watchlist():
    """从关注列表中删除股票"""
    data = request.get_json(silent=True) or {}
    stock_code = str(data.get('stock_code', '')).strip()

    if not stock_code:
        return jsonify({'success': False, 'message': '股票代码不能为空'})

    normalized_code = normalize_stock_code(stock_code)
    watchlist = load_watchlist()
    new_watchlist = [item for item in watchlist if item[0] != normalized_code]

    if len(new_watchlist) == len(watchlist):
        return jsonify({'success': False, 'message': '该股票不在关注列表中'})

    save_watchlist(new_watchlist)
    return jsonify({'success': True, 'message': '删除成功', 'data': new_watchlist})
