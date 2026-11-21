"""用Node执行真实轮询函数，确保降级不会显示绿色完成或残留旧持仓。"""
import json
import pathlib
import re
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), '需要Node验证前端轮询分支')
class FrontendStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (pathlib.Path(__file__).resolve().parents[1] / 'templates' / 'index.html').read_text()

    def run_branch(self, function_name, end_name, status):
        start = self.source.index('function ' + function_name + '(')
        end = self.source.index('function ' + end_name + '(', start)
        function = self.source[start:end]
        harness = """
const vm = require('node:vm');
const assert = require('node:assert/strict');
const target = {innerHTML: '', children: [], replaceChildren(child) {this.children=[child]; this.innerHTML=child.textContent;}};
const elements = new Map();
const context = {
 document: {getElementById: (id) => {if(!elements.has(id)) elements.set(id,target); return elements.get(id);},
            createElement: () => ({className:'',textContent:''})},
 fetch: () => Promise.resolve({json: () => Promise.resolve(STATUS)}),
 setTimeout: () => {},
 localStorage: {getItem: () => null, setItem: () => {}},
 loadSelectionResult: () => {target.loads = (target.loads || 0) + 1;}, loadBacktestReport: () => {}, loadBacktestStockList: () => {},
};
vm.createContext(context); vm.runInContext(SOURCE, context);
context[NAME]('test');
setImmediate(() => { console.log(JSON.stringify(target)); });
"""
        harness = harness.replace('STATUS', json.dumps(status)).replace('SOURCE', json.dumps(function)).replace('NAME', json.dumps(function_name))
        result = subprocess.run([shutil.which('node'), '-e', harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_selection_degraded_has_warning_not_success(self):
        result = self.run_branch('pollSelectionTaskStatus', 'loadSelectionResult',
                                 {'status':'degraded','degraded':True,'warnings':['部分失败']})
        self.assertEqual(result['children'][0]['className'], 'alert alert-warning')
        self.assertIn('名单只含已完成校验的股票', result['innerHTML'])
        self.assertNotIn('alert-success', result['innerHTML'])
        self.assertNotIn('任务不存在', result['innerHTML'])

    def test_selection_pending_keeps_polling(self):
        result = self.run_branch('pollSelectionTaskStatus', 'loadSelectionResult',
                                 {'status':'pending','progress':42,'progress_label':'（5/73 只）'})
        html = result['innerHTML']
        self.assertIn('progress', html)
        self.assertNotIn('任务不存在', html)
        # 必须有真实可见的进度条（带宽度、颜色、百分比与步骤标签）
        self.assertIn('progress-bar', html)
        self.assertIn('width: 42%', html)
        self.assertIn('background-color', html)
        self.assertIn('42%', html)
        self.assertIn('5/73', html)

    def test_backtest_completed_degraded_is_yellow(self):
        # 只执行函数本身，后续加载由harness模拟。
        start = self.source.index('function pollBacktestStatus(')
        next_function = re.search(r'function (\w+)\(', self.source[start + 10:])
        result = self.run_branch('pollBacktestStatus', next_function.group(1),
                                 {'status':'completed','degraded':True,'warnings':['数据缺失']})
        self.assertEqual(result['children'][0]['className'], 'alert alert-warning')
        self.assertNotIn('alert-success', result['innerHTML'])

    def test_backtest_failure_is_summary_with_collapsed_safe_log(self):
        result = self.run_branch('pollBacktestStatus', 'loadBacktestReport', {
            'status': 'failed', 'error_summary': '回测未完成，请检查数据',
            'messages': ['<img src=x onerror=alert(1)>', '源数据未达到期望交易日']})
        html = result['innerHTML']
        self.assertIn('回测未完成，请检查数据', html)
        self.assertIn('<details', html)
        self.assertNotIn('<details open', html)
        self.assertIn('max-height: 320px', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)

    def test_chart_requests_bind_strategy_and_clear_stale_image(self):
        start = self.source.index('function loadBacktestStockList(')
        end = self.source.index('// ==================== 板块分析相关函数', start)
        functions = self.source[start:end]
        self.assertIn("get_stock_list?mode=", functions)
        self.assertIn("'?mode=' + encodeURIComponent(lastBacktestMode)", functions)
        self.assertIn("image.removeAttribute('src')", functions)

    def test_selection_date_columns_are_not_numeric_formatted(self):
        self.assertIn("col.includes('截止日')", self.source)
        self.assertIn("text.slice(0, 4) + '-' + text.slice(4, 6)", self.source)

    def test_selection_start_keeps_latest_saved_table(self):
        start = self.source.index('function runStockSelection(')
        end = self.source.index('function pollSelectionTaskStatus(', start)
        function = self.source[start:end]
        self.assertNotIn("getElementById('selection-result').style.display = 'none'", function)
        self.assertNotIn("getElementById('selection-result-content').textContent = ''", function)
        self.assertIn('loadSelectionResult()', function)
        start = self.source.index('function showStockSelection(')
        opened = self.source[start:self.source.index('function runStockSelection(', start)]
        self.assertIn('loadSelectionResult()', opened)
        failed = self.run_branch('pollSelectionTaskStatus', 'loadSelectionResult', {'status': 'failed'})
        self.assertEqual(failed['loads'], 1)

    def test_selection_renders_and_batch_watches_only_new_entries(self):
        script_start = self.source.rindex('<script>') + len('<script>')
        script_end = self.source.rindex('</script>')
        script_body = self.source[script_start:script_end]
        harness = """
const vm = require('node:vm');
const nodes = new Map();
function el(id) {
  if (!nodes.has(id)) nodes.set(id, {id, innerHTML: '', textContent: '', value: '', style: {}, className: '', appendChild: () => {}});
  return nodes.get(id);
}
const posted = [];
const context = {
  document: {
    documentElement: {getAttribute: () => 'light', setAttribute: () => {}},
    getElementById: el,
    querySelectorAll: () => [],
    addEventListener: () => {},
    createElement: () => ({className: '', innerHTML: '', style: {}, remove: () => {}})
  },
  window: {},
  localStorage: {getItem: () => null, setItem: () => {}},
  fetch: (url, opts) => {
    if (opts && opts.body) posted.push(JSON.parse(opts.body));
    return Promise.resolve({json: () => Promise.resolve({success: true, data: [['600000.SH', '浦发银行'], ['300433.SZ', '蓝思科技']]})});
  },
  setTimeout: () => {},
  console
};
vm.createContext(context);
vm.runInContext(SOURCE, context);
vm.runInContext(`
  wbWatchlistMap.set('600000.SH', '浦发银行');
  wbCachedSelectionPayload = {
    success: true,
    data_asof: '20261120',
    data: [
      {'股票代码': '000921.SZ', '入场日期': '2026-11-19', '入场价格': '26.13', '当前日期': '2026-11-20', '当前价格': '26.47', '收益': '1.30', '离场类型': 'final_close', '数据截止日': '20261120', '处理时间': '2026-11-21 13:01:25'},
      {'股票代码': '300433.SZ', '入场日期': '2026-11-20', '入场价格': '21.50', '当前日期': '2026-11-20', '当前价格': '21.50', '收益': '0.00', '离场类型': 'final_close', '数据截止日': '20261120', '处理时间': '2026-11-21 13:01:26'},
      {'股票代码': '600000.SH', '入场日期': '2026-11-20', '入场价格': '10.10', '当前日期': '2026-11-20', '当前价格': '10.10', '收益': '0.00', '离场类型': 'final_close', '数据截止日': '20261120', '处理时间': '2026-11-21 13:01:27'}
    ]
  };
  renderSelectionResult(wbCachedSelectionPayload);
`, context);
context.addAllSelectionToWatchlist().then(() => {
  console.log(JSON.stringify({
    html: el('selection-result-content').innerHTML,
    kpiCount: el('sel-kpi-count').textContent,
    kpiUnwatched: el('sel-kpi-unwatched').textContent,
    kpiFiltered: el('sel-kpi-filtered').textContent,
    posted
  }));
});
""".replace('SOURCE', json.dumps(script_body))
        res = subprocess.run([shutil.which('node'), '-e', harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout)
        self.assertIn('300433.SZ', out['html'])
        self.assertIn('600000.SH', out['html'])
        self.assertNotIn('000921.SZ', out['html'])
        self.assertEqual(out['kpiCount'], '2 只')
        self.assertEqual(out['kpiFiltered'], '1 只')
        self.assertEqual([item['stock_code'] for item in out['posted']], ['300433.SZ'])


class WorkbenchAndWatchlistApiTest(unittest.TestCase):
    """验证新版工作台静态样式路由、默认首屏结构以及关注池一键入池/改名接口。"""

    def setUp(self):
        import tempfile
        from unittest import mock
        import web_ui
        import api.watchlist as wl

        self.tmpdir = tempfile.TemporaryDirectory()
        self.wl = wl
        self.fake_wl_file = str(pathlib.Path(self.tmpdir.name) / 'watchlist.py')
        self.fake_data_dir = str(pathlib.Path(self.tmpdir.name) / 'data')
        ticker_dir = pathlib.Path(self.fake_data_dir) / '300433.SZ'
        ticker_dir.mkdir(parents=True, exist_ok=True)
        (ticker_dir / '300433.SZ_company_basic.json').write_text(
            json.dumps({'basic_info': {'公司简称': '蓝思科技'}}, ensure_ascii=False),
            encoding='utf-8'
        )
        pathlib.Path(self.fake_wl_file).write_text('WATCHLIST = []\n', encoding='utf-8')

        self.patchers = [
            mock.patch.object(wl, 'WATCHLIST_FILE', self.fake_wl_file),
            mock.patch.object(wl, 'DATA_DIR', self.fake_data_dir),
            mock.patch.object(wl, 'load_watchlist', side_effect=self._load_fake_wl),
        ]
        for p in self.patchers:
            p.start()
        self.client = web_ui.app.test_client()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.tmpdir.cleanup()

    def _load_fake_wl(self):
        ns = {}
        exec(pathlib.Path(self.fake_wl_file).read_text(encoding='utf-8'), ns)
        return list(ns.get('WATCHLIST', []))

    def test_workbench_index_and_css_served(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('no-store', resp.headers.get('Cache-Control', ''))
        body = resp.get_data(as_text=True)
        self.assertIn('class="app-sidebar"', body)
        self.assertIn('01 · 市场选股', body)
        self.assertIn('toggleWorkbenchTheme', body)
        self.assertIn('quickAddStockToWatchlist', body)

        css_resp = self.client.get('/static/css/workbench.css')
        self.assertEqual(css_resp.status_code, 200)
        css_text = css_resp.get_data(as_text=True)
        self.assertIn('[data-theme="dark"]', css_text)
        self.assertIn('--up-color', css_text)
        css_resp.close()

    def test_watchlist_auto_name_and_update(self):
        add_resp = self.client.post('/api/watchlist/add', json={'stock_code': '300433', 'stock_name': ''})
        payload = add_resp.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['added'], {'code': '300433.SZ', 'name': '蓝思科技'})

        upd_resp = self.client.post('/api/watchlist/update_name',
                                    json={'stock_code': '300433.SZ', 'stock_name': '蓝思科技A'})
        self.assertTrue(upd_resp.get_json()['success'])
        self.assertEqual(self._load_fake_wl(), [('300433.SZ', '蓝思科技A')])

        rm_resp = self.client.post('/api/watchlist/remove', json={'stock_code': '300433'})
        self.assertTrue(rm_resp.get_json()['success'])
        self.assertEqual(self._load_fake_wl(), [])

    def test_watchlist_column_removed_and_simple_default(self):
        body = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('历史回测累计 / 胜率', body)
        self.assertIn("localStorage.getItem('wbBacktestStrategyMode') || 'simple'", body)
        self.assertIn('id="use-simplified" value="simplified" checked', body)
        self.assertIn('https://platform.deepseek.com/api_keys', body)
        self.assertIn('https://tushare.pro/user/token', body)


class TradingPnlAndSettingsApiTest(unittest.TestCase):
    """验证 FIFO 逐手收益核算、本机选股入场回测追踪及设置页配置检测。"""

    def test_fifo_pnl_closed_and_open_lots(self):
        from api.trading import compute_stock_fifo_pnl
        records = [
            {'date': '2026-05-01', 'type': 'buy', 'price': 10.125, 'shares': 1000},
            {'date': '2026-05-05', 'type': 'buy', 'price': 12.0, 'shares': 500},
            {'date': '2026-05-10', 'type': 'sell', 'price': 13.125, 'shares': 1200},
        ]
        # FIFO: 先卖 1000股@10.125 -> 卖出13.125 盈利 +3000；再卖 200股@12.0 -> 卖出13.125 盈利 +225；已实现 = +3225
        # 剩余持仓: 300股@12.0，现价 15.0 -> 浮盈 +900；累计总收益 = +4125
        res = compute_stock_fifo_pnl('600000.SH', records, latest_price=15.0, stock_name='浦发银行', price_source='实时现价')
        self.assertEqual(res['holding_shares'], 300)
        self.assertAlmostEqual(res['avg_hold_cost'], 12.0)
        self.assertAlmostEqual(res['realized_pnl'], 3225.0)
        self.assertAlmostEqual(res['unrealized_pnl'], 900.0)
        self.assertAlmostEqual(res['total_pnl'], 4125.0)
        self.assertEqual(res['lots'][0]['buy_price'], 10.125)
        self.assertEqual(res['lots'][0]['sell_price'], 13.125)
        self.assertEqual(len(res['lots']), 3)
        self.assertEqual([l['status'] for l in res['lots']], ['closed', 'closed', 'open'])

    def test_settings_status_and_save(self):
        import tempfile
        from unittest import mock
        import web_ui
        import user_settings as us
        import tushare_client as tc

        with tempfile.TemporaryDirectory() as tmp:
            fake_settings = str(pathlib.Path(tmp) / 'user_settings.json')
            import config as cfg
            with mock.patch.object(us, 'SETTINGS_FILE', fake_settings), \
                 mock.patch.object(us, 'probe_ollama', return_value=(False, [], 'offline')), \
                 mock.patch.dict(cfg.AI_CONFIG, {'api_key': '', 'provider': 'ollama'}, clear=False), \
                 mock.patch.object(tc, 'PRIMARY_TOKEN', 'YOUR_TUSHARE_TOKEN'), \
                 mock.patch.object(tc, 'BACKUP_TOKENS', []), \
                 mock.patch.dict('os.environ', {}, clear=False):
                import os
                os.environ.pop('GP_TUSHARE_TOKENS', None)
                client = web_ui.app.test_client()

                st = client.get('/api/settings/status').get_json()
                self.assertFalse(st['ai_ready'])
                self.assertFalse(st['tushare_ready'])
                self.assertTrue(st['needs_setup'])
                self.assertEqual(st['ai']['provider'], 'api')

                # 未选择模型时禁止保存
                r_no_mod = client.post('/api/settings/save_ai', json={
                    'provider': 'api',
                    'api_base': 'https://api.deepseek.com',
                    'selected_model': '',
                    'api_key': 'sk-testdeepseek123456',
                }).get_json()
                self.assertFalse(r_no_mod['success'])

                # 第一步：验证 API 链接并拉取模型列表
                with mock.patch.object(us, 'fetch_openai_compatible_models',
                                       return_value=['deepseek-chat', 'deepseek-reasoner']):
                    r_fetch = client.post('/api/settings/fetch_models', json={
                        'provider': 'api',
                        'api_base': 'https://api.deepseek.com',
                        'api_key': 'sk-testdeepseek123456',
                    }).get_json()
                self.assertTrue(r_fetch['success'])
                self.assertEqual(r_fetch['models'], ['deepseek-chat', 'deepseek-reasoner'])

                # 第二步：根据返回的模型列表选定并保存
                r_ai = client.post('/api/settings/save_ai', json={
                    'provider': 'api',
                    'api_base': 'https://api.deepseek.com',
                    'selected_model': 'deepseek-reasoner',
                    'verified_models': r_fetch['models'],
                    'api_key': 'sk-testdeepseek123456',
                }).get_json()
                self.assertTrue(r_ai['success'])

                r_ts = client.post('/api/settings/save_tushare', json={
                    'primary_token': 'ts_real_token_1234567890',
                }).get_json()
                self.assertTrue(r_ts['success'])

                st2 = client.get('/api/settings/status').get_json()
                self.assertTrue(st2['ai_ready'])
                self.assertTrue(st2['tushare_ready'])
                self.assertFalse(st2['needs_setup'])
                self.assertEqual(st2['ai']['api_key_masked'], 'sk-t****3456')
                self.assertEqual(st2['ai']['api_model'], 'deepseek-reasoner')
                self.assertEqual(st2['ai']['api_models'], ['deepseek-chat', 'deepseek-reasoner'])

    def test_selected_cohort_performance_starts_from_first_selected_date(self):
        import hashlib
        import tempfile
        from unittest import mock
        import pandas as pd
        import numpy as np
        import web_ui
        import selection_result_store as store
        import api.backtest as bt
        import api.stock_selection as sel_api

        with tempfile.TemporaryDirectory() as tmp:
            sel_dir = pathlib.Path(tmp) / 'stocks_filter'
            data_dir = pathlib.Path(tmp) / 'data'
            sel_dir.mkdir()
            (data_dir / '300433.SZ').mkdir(parents=True)

            # 构造 160 根加速上涨行情 K 线（指数斜率保证 MACD_hist > 0，末段放量保证量比达标）
            dates = pd.bdate_range(end='2026-11-20', periods=160)
            prices = 10.0 * np.exp(np.linspace(0.0, 0.9, 160))
            qfq_df = pd.DataFrame({
                'date': dates.strftime('%Y-%m-%d'),
                'open': prices * 0.995,
                'high': prices * 1.01,
                'low': prices * 0.99,
                'close': prices,
                'volume': np.concatenate([np.full(150, 1000.0), np.full(10, 3500.0)]),
            })
            qfq_df.to_csv(data_dir / '300433.SZ' / '300433.SZ_qfq.csv', index=False)

            first_asof = dates[-5].strftime('%Y%m%d')
            first_iso = dates[-5].strftime('%Y-%m-%d')
            out_csv = str(sel_dir / 'final_holdings.csv')

            # 放入 1 只当日可入场 (300433.SZ) + 1 只旧入场副产物 (000921.SZ)
            df_hold = pd.DataFrame([
                ['300433.SZ', first_iso, '20.0', first_iso, '20.0', '0.0', 'final_close', first_asof, '2026-11-14 18:00:00'],
                ['000921.SZ', '2026-10-01', '15.0', first_iso, '18.0', '20.0', 'final_close', first_asof, '2026-11-14 18:00:00'],
            ], columns=['股票代码', '入场日期', '入场价格', '当前日期', '当前价格', '收益', '离场类型', '数据截止日', '处理时间'])
            with open(out_csv, 'w', encoding='utf-8-sig', newline='') as fh:
                df_hold.to_csv(fh, index=False)
            with open(out_csv, 'rb') as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            store.archive_daily(out_csv, {
                'completed': True, 'valid': True, 'void': False, 'state': 'completed',
                'degraded': False, 'data_asof': first_asof, 'holdings': 2, 'processed': 2,
                'csv_sha256': digest,
            })

            with mock.patch.object(sel_api, 'SELECTION_DIR', str(sel_dir)), \
                 mock.patch.object(bt, 'DATA_DIR', str(data_dir)):
                client = web_ui.app.test_client()
                resp = client.get('/api/backtest/get_selected_performance?mode=simple').get_json()
                self.assertTrue(resp['success'])
                # 旧入场副产物 000921.SZ 绝不纳入统计，仅含当日可入场的 300433.SZ
                self.assertEqual([r['ticker'] for r in resp['data']], ['300433.SZ'])
                self.assertEqual(resp['data'][0]['first_selected_date'], first_iso)
                self.assertTrue(resp['data'][0]['has_data'])
                self.assertGreaterEqual(resp['data'][0]['total_trades'], 1)


if __name__ == '__main__':
    unittest.main()
