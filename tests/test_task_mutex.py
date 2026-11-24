# tests/test_task_mutex.py
# -*- coding: utf-8 -*-
"""单任务运行互斥、活跃任务进度查询与前端按钮/弹窗联动测试。"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class BackendTaskMutexTest(unittest.TestCase):
    """验证后端全局单任务槽拦截并发请求、实时反馈进度并在终态自动释放。"""

    def setUp(self):
        import web_ui
        import api.common as common
        import api.stock_selection as sel_api
        import api.backtest as bt_api
        import api.sector as sec_api

        self.common = common
        self.sel_api = sel_api
        self.bt_api = bt_api
        self.sec_api = sec_api

        self.saved_task_status = dict(common.task_status)
        self.saved_sel_tasks = dict(sel_api.selection_tasks)
        self.saved_bt_status = dict(bt_api.backtest_task_status)
        self.saved_sec_status = dict(sec_api.sector_task_status)

        common.release_active_task()
        common.task_status.clear()
        sel_api.selection_tasks.clear()
        bt_api.backtest_task_status.clear()
        sec_api.sector_task_status.clear()

        self.client = web_ui.app.test_client()

    def tearDown(self):
        self.common.release_active_task()
        self.common.task_status.clear()
        self.common.task_status.update(self.saved_task_status)
        self.sel_api.selection_tasks.clear()
        self.sel_api.selection_tasks.update(self.saved_sel_tasks)
        self.bt_api.backtest_task_status.clear()
        self.bt_api.backtest_task_status.update(self.saved_bt_status)
        self.sec_api.sector_task_status.clear()
        self.sec_api.sector_task_status.update(self.saved_sec_status)

    def test_active_task_blocks_other_tasks_and_auto_releases(self):
        # 启动市场选股（拦截后台线程防止实际跑选股）
        with mock.patch.object(self.sel_api.threading, 'Thread') as mock_thread:
            mock_thread.return_value = mock.MagicMock()
            resp1 = self.client.post(
                '/api/stock_selection/run',
                json={'preliminary': True, 'detailed': True},
            ).get_json()
        self.assertTrue(resp1['success'])
        sel_tid = resp1['task_id']

        # 模拟进度推进到 42%
        self.sel_api.selection_tasks[sel_tid].update({
            'status': 'running',
            'progress': 42,
            'progress_label': '统一日期回测 （21/50 只）',
            'messages': ['[21/50] 正在处理 300433.SZ'],
        })

        # 查询 /api/active_task 应返回完整进度信息
        active_resp = self.client.get('/api/active_task').get_json()
        self.assertTrue(active_resp['success'])
        self.assertTrue(active_resp['has_active_task'])
        self.assertEqual(active_resp['active_task']['task_name'], '市场选股')
        self.assertEqual(active_resp['active_task']['progress'], 42)
        self.assertIn('21/50', active_resp['active_task']['progress_label'])

        # 尝试并发启动其他各类任务，均须被拦截并返回冲突详情
        with mock.patch.object(self.common.analysis_queue, 'put') as mock_aq, \
             mock.patch.object(self.common.quick_queue, 'put') as mock_qq, \
             mock.patch.object(self.bt_api.backtest_task_queue, 'put') as mock_bq, \
             mock.patch.object(self.sec_api.sector_task_queue, 'put') as mock_sq:
            conflict_calls = [
                self.client.post('/api/quick_analyze', json={'stock_code': '300433', 'task_type': 'daily', 'strategy_mode': 'short'}),
                self.client.post('/api/analyze', json={'stock_code': '300433'}),
                self.client.post('/api/backtest/run_backtest', json={'skip_data_update': True, 'use_simplified': True}),
                self.client.post('/api/sector_analyze', json={'sector_code': 'sh000001', 'sector_type': 'broad_index'}),
                self.client.post('/api/sector_collect', json={'collect_type': 'broad_index'}),
                self.client.post('/api/detailed_function', json={'function_type': 'fetch_data', 'data_type': 'daily', 'stock_code': '300433'}),
                self.client.post('/api/execute_single_function', json={'category': 'fetch', 'program': 'data_collector.py', 'stock_code': '300433'}),
            ]
            for http_resp in conflict_calls:
                payload = http_resp.get_json()
                self.assertFalse(payload['success'], payload)
                self.assertTrue(payload.get('task_conflict'), payload)
                self.assertEqual(payload['active_task']['task_name'], '市场选股')
                self.assertEqual(payload['active_task']['progress'], 42)

            # 只读 query_data 不阻塞
            q_resp = self.client.post(
                '/api/detailed_function',
                json={'function_type': 'query_data', 'data_type': 'daily', 'stock_code': '300433'},
            ).get_json()
            self.assertFalse(q_resp.get('task_conflict'))

            mock_aq.assert_not_called()
            mock_qq.assert_not_called()
            mock_bq.assert_not_called()
            mock_sq.assert_not_called()

        # 市场选股完成后应自动释放槽位，允许启动新任务
        self.sel_api.selection_tasks[sel_tid]['status'] = 'completed'
        self.sel_api.selection_tasks[sel_tid]['progress'] = 100
        active_after = self.client.get('/api/active_task').get_json()
        self.assertFalse(active_after['has_active_task'])
        self.assertIsNone(active_after['active_task'])

        with mock.patch.object(self.bt_api.backtest_task_queue, 'put') as mock_bq2:
            bt_resp = self.client.post(
                '/api/backtest/run_backtest',
                json={'skip_data_update': True, 'use_simplified': True},
            ).get_json()
        self.assertTrue(bt_resp['success'])
        mock_bq2.assert_called_once()

    def test_sync_detailed_route_locks_while_running_and_releases_on_finish(self):
        import api.detailed as det_api
        import web_ui

        entered = threading.Event()
        release = threading.Event()

        def _blocking_cmd(cmd):
            entered.set()
            release.wait(timeout=3.0)
            return subprocess.CompletedProcess(cmd, 0, stdout='ok', stderr='')

        result_holder = {}

        def _run_req():
            c = web_ui.app.test_client()
            result_holder['resp'] = c.post(
                '/api/execute_single_function',
                json={'category': 'fetch', 'program': 'data_collector.py', 'stock_code': '300433'},
            ).get_json()

        with mock.patch.object(det_api, '_run_py_cmd', side_effect=_blocking_cmd):
            t = threading.Thread(target=_run_req)
            t.start()
            self.assertTrue(entered.wait(timeout=2.0))

            # 运行期间，其他任务会被拦截并看到“脚本运行”
            conflict = self.client.post(
                '/api/quick_analyze',
                json={'stock_code': '000001', 'task_type': 'daily', 'strategy_mode': 'short'},
            ).get_json()
            self.assertFalse(conflict['success'])
            self.assertTrue(conflict['task_conflict'])
            self.assertEqual(conflict['active_task']['task_name'], '脚本运行')

            release.set()
            t.join(timeout=3.0)

        self.assertTrue(result_holder['resp']['success'])
        # 完成后已自动释放
        self.assertFalse(self.client.get('/api/active_task').get_json()['has_active_task'])


@unittest.skipUnless(shutil.which('node'), '需要 Node 验证前端任务互斥与按钮文本状态')
class FrontendTaskMutexTests(unittest.TestCase):
    """验证前端按钮运行态文本“正在进行……”、其他按钮弹出进度弹窗及完成后恢复。"""

    def test_running_button_text_and_conflict_modal_flow(self):
        html = (PROJECT_ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
        for marker in (
            'id="taskConflictModal"',
            'id="btn-start-selection"',
            'id="btn-start-backtest"',
            'id="btn-start-quick-ai"',
            'id="btn-start-full-ai"',
            'id="btn-start-sector-ai"',
            'id="btn-start-sector-collect"',
            'id="btn-start-detailed-ops"',
            'id="btn-start-single-script"',
        ):
            self.assertIn(marker, html)

        script_start = html.rindex('<script>') + len('<script>')
        script_end = html.rindex('</script>')
        script_body = html[script_start:script_end]

        harness = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
function el(id) {
  if (!nodes.has(id)) {
    const classes = new Set();
    nodes.set(id, {
      id,
      innerHTML: '',
      textContent: '',
      value: '',
      checked: true,
      disabled: false,
      style: {},
      classList: {
        add(c) { classes.add(c); },
        remove(c) { classes.delete(c); },
        toggle(c, force) {
          if (force === undefined) {
            if (classes.has(c)) classes.delete(c); else classes.add(c);
          } else if (force) classes.add(c); else classes.delete(c);
        },
        contains(c) { return classes.has(c); }
      },
      setAttribute() {},
      addEventListener() {},
      appendChild() {},
      removeAttribute() {},
      replaceChildren(ch) { this.innerHTML = ch ? (ch.textContent || '') : ''; }
    });
  }
  return nodes.get(id);
}

el('btn-start-selection').textContent = '▶ 开始市场选股';
el('btn-start-backtest').textContent = '▶ 开始策略回测';
el('btn-start-quick-ai').textContent = '▶ 开始快速研判';
el('selection-preliminary').checked = true;
el('selection-detailed').checked = true;

let modalShowCount = 0;
const fetchCalls = [];
let statusPayload = {
  status: 'running',
  progress: 42,
  progress_label: '统一日期回测 （21/50 只）',
  messages: ['[21/50] 正在处理 300433.SZ']
};

const context = {
  document: {
    documentElement: { getAttribute: () => 'light', setAttribute: () => {} },
    getElementById: el,
    querySelector: (sel) => ({ value: 'short', checked: true }),
    querySelectorAll: () => [],
    addEventListener: () => {},
    createElement: () => ({ className: '', innerHTML: '', textContent: '', style: {}, remove: () => {} })
  },
  window: {},
  bootstrap: {
    Modal: {
      getOrCreateInstance(target) {
        return {
          show() { modalShowCount += 1; target.classList.add('show'); },
          hide() { target.classList.remove('show'); }
        };
      },
      getInstance(target) {
        return { hide() { target.classList.remove('show'); } };
      }
    }
  },
  localStorage: { getItem: () => null, setItem: () => {} },
  fetch: (url, opts) => {
    fetchCalls.push(url);
    if (url === '/api/stock_selection/run') {
      return Promise.resolve({ json: () => Promise.resolve({ success: true, task_id: 'sel_1' }) });
    }
    if (url.startsWith('/api/stock_selection/task_status/')) {
      return Promise.resolve({ json: () => Promise.resolve(statusPayload) });
    }
    if (url === '/api/active_task') {
      return Promise.resolve({
        json: () => Promise.resolve({
          success: true,
          has_active_task: true,
          active_task: {
            task_id: 'sel_1',
            task_key: 'selection',
            page_key: 'selection',
            task_name: '市场选股',
            task_detail: '全市场初筛 + 批量回测',
            status: 'running',
            progress: 42,
            progress_label: '统一日期回测 （21/50 只）',
            latest_message: '[21/50] 正在处理 300433.SZ'
          }
        })
      });
    }
    return Promise.resolve({ json: () => Promise.resolve({ success: true, data: [] }) });
  },
  setTimeout: () => {},
  setInterval: () => 1,
  clearInterval: () => {},
  console
};
vm.createContext(context);
vm.runInContext(SOURCE, context);

(async () => {
  // 1. 启动市场选股
  context.runStockSelection();
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));

  assert.equal(el('btn-start-selection').disabled, true);
  assert.ok(el('btn-start-selection').innerHTML.includes('正在进行市场选股'));
  assert.equal(el('btn-start-backtest').disabled, false);
  assert.equal(el('btn-start-quick-ai').disabled, false);

  // 2. 点击其他“开始任务”按钮（如策略回测、快速研判）：不发新请求，弹出运行中进度弹窗
  const beforeCount = fetchCalls.length;
  context.runBacktest();
  context.startQuickAnalysis();
  await new Promise(r => setImmediate(r));

  assert.ok(modalShowCount >= 2);
  assert.ok(!fetchCalls.includes('/api/backtest/run_backtest'));
  assert.ok(!fetchCalls.includes('/api/quick_analyze'));
  assert.equal(el('conflict-modal-task-name').textContent, '市场选股');
  assert.equal(el('conflict-modal-progress-pct').textContent, '42%');
  assert.ok(el('conflict-modal-step-text').textContent.includes('21/50'));

  // 3. 选股任务完成，按钮恢复默认文案与可点击状态
  statusPayload = { status: 'completed', progress: 100, messages: ['完成'] };
  context.pollSelectionTaskStatus('sel_1');
  await new Promise(r => setImmediate(r));
  assert.equal(el('btn-start-selection').disabled, false);
  assert.equal(el('btn-start-selection').textContent, '▶ 开始市场选股');
  console.log('FRONTEND_MUTEX_OK');
})().catch(err => {
  console.error(err);
  process.exit(1);
});
""".replace('SOURCE', json.dumps(script_body))

        res = subprocess.run(
            [shutil.which('node'), '-e', harness],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        self.assertIn('FRONTEND_MUTEX_OK', res.stdout)

    def test_update_cask_sha_preserves_arch_declaration(self):
        import importlib.util
        import tempfile

        script_path = PROJECT_ROOT / 'packaging' / 'scripts' / 'update_cask_sha.py'
        spec = importlib.util.spec_from_file_location('update_cask_sha', str(script_path))
        cask_upd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cask_upd)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = pathlib.Path(tmp)
            cask_file = tmp_root / 'packaging' / 'homebrew' / 'Casks' / 'floe.rb'
            cask_file.parent.mkdir(parents=True, exist_ok=True)
            cask_file.write_text(
                (PROJECT_ROOT / 'packaging' / 'homebrew' / 'Casks' / 'floe.rb').read_text(encoding='utf-8'),
                encoding='utf-8',
            )
            sums_file = tmp_root / 'SHA256SUMS.txt'
            arm_hash = 'a' * 64
            x64_hash = 'b' * 64
            sums_file.write_text(
                f'{arm_hash}  Floe-v2.1.0-macos-arm64.dmg\n'
                f'{x64_hash}  Floe-v2.1.0-macos-x64.dmg\n',
                encoding='utf-8',
            )
            with mock.patch.object(cask_upd, 'PROJECT_ROOT', str(tmp_root)):
                cask_upd.update_cask(str(sums_file))

            updated = cask_file.read_text(encoding='utf-8')
            self.assertIn('arch arm: "arm64", intel: "x64"', updated)
            self.assertIn(f'sha256 arm:   "{arm_hash}"', updated)
            self.assertIn(f'intel: "{x64_hash}"', updated)


if __name__ == '__main__':
    unittest.main()
