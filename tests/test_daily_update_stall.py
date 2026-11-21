"""完整五维分析第 6 步「日更数据」卡住的回归测试：
非两融标的不再逐日抓全市场、同一采集命令不重复执行、子进程超时会被终止并实时输出。"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from unittest import mock

import pandas as pd

import check_data_updates as cdu

TICKER = '000100.SZ'
EXPECTED = date(2026, 11, 20)


class DailyUpdateStallTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='gp_stall_')
        self.stock_dir = os.path.join(self.tmpdir, TICKER)
        os.makedirs(self.stock_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_marker(self, checked):
        with open(os.path.join(self.stock_dir, f'{TICKER}_margin_na.json'), 'w', encoding='utf-8') as fh:
            json.dump({'checked_date': checked}, fh)

    def test_non_margin_stock_is_skipped_without_fetching(self):
        self._write_marker('20261120')
        with mock.patch.object(cdu, 'run_command') as run, redirect_stdout(io.StringIO()):
            failure = cdu.check_and_update_item(
                TICKER, 'margin_data', f'{TICKER}_margin_data.csv',
                f'python batch_margin_collector.py --ticker {TICKER}', EXPECTED, self.stock_dir)
        self.assertIsNone(failure)
        run.assert_not_called()

    def test_expired_marker_triggers_recheck_with_end_date(self):
        self._write_marker('20261001')
        commands = []
        def fake_run(command, cwd=None):
            commands.append(command)
            return True, ''
        with mock.patch.object(cdu, 'run_command', side_effect=fake_run), redirect_stdout(io.StringIO()):
            failure = cdu.check_and_update_item(
                TICKER, 'margin_data', f'{TICKER}_margin_data.csv',
                f'python batch_margin_collector.py --ticker {TICKER}', EXPECTED, self.stock_dir)
        self.assertEqual(len(commands), 1)
        self.assertIn('--end_date 20261120', commands[0])
        self.assertIsNotNone(failure)  # 过期标记不能放行，必须重新核对

    def test_shared_collector_runs_once_per_group(self):
        commands = []
        def fake_run(command, cwd=None):
            commands.append(command)
            return False, 'returncode=2'
        files = {name: cdu.DAILY_DATA_FILES[name] for name in ('fund_flow', 'valuation')}
        with mock.patch.object(cdu, 'DATA_DIR', self.tmpdir), \
             mock.patch.object(cdu, 'run_command', side_effect=fake_run), \
             redirect_stdout(io.StringIO()):
            failures = cdu._check_group(TICKER, EXPECTED, files)
        self.assertEqual(len(failures), 2)          # 两项各自独立判定失败
        self.assertEqual(len(commands), 1)          # 但共用的采集脚本只执行一次
        self.assertIsNone(cdu._COMMAND_RESULTS)     # 缓存只在本组内有效

    def test_not_applicable_margin_recorded_in_evidence(self):
        self._write_marker('20261120')
        files = {'margin_data': cdu.DAILY_DATA_FILES['margin_data']}
        with mock.patch.object(cdu, 'DATA_DIR', self.tmpdir), redirect_stdout(io.StringIO()):
            failures = cdu._check_group(TICKER, EXPECTED, files)
        self.assertEqual(failures, [])
        with open(os.path.join(self.stock_dir, f'{TICKER}_data_freshness.json'), encoding='utf-8') as fh:
            item = json.load(fh)['items']['margin_data']
        self.assertTrue(item['valid'])
        self.assertTrue(item['not_applicable'])

    def test_decision_layer_accepts_not_applicable_margin(self):
        from Process.two_layer_decision_analyzer import TwoLayerDecisionAnalyzer
        analyzer = TwoLayerDecisionAnalyzer(TICKER)
        analyzer.data_dir = self.stock_dir
        now = datetime.now()
        checked = (now - timedelta(minutes=5)).isoformat()
        for name in ('fund_flow', 'valuation'):
            with open(os.path.join(self.stock_dir, f'{TICKER}_{name}.csv'), 'w', encoding='utf-8') as fh:
                fh.write('date\n2026-11-20\n')
        items = {name: {'valid': True, 'filename': f'{TICKER}_{name}.csv', 'checked_at': checked,
                        'sha256': cdu.source_digest(os.path.join(self.stock_dir, f'{TICKER}_{name}.csv'))}
                 for name in ('fund_flow', 'valuation')}
        items['margin_data'] = {'valid': True, 'not_applicable': True, 'sha256': None,
                                'filename': f'{TICKER}_margin_data.csv', 'checked_at': checked}
        state = {'schema_version': 1, 'ticker': TICKER, 'expected_date': EXPECTED.isoformat(), 'items': items}
        report = {'meta': {'ticker': TICKER, 'generated_at': now.isoformat()}}
        with mock.patch('check_data_updates.source_digest', side_effect=cdu.source_digest):
            err = analyzer._report_evidence_error('sentiment', report, state, EXPECTED)
        self.assertIsNone(err)

    def test_streaming_command_times_out_and_forwards_output(self):
        script = os.path.join(self.tmpdir, 'slow.py')
        with open(script, 'w', encoding='utf-8') as fh:
            fh.write('import time, sys\nprint("PROGRESS_LINE", flush=True)\ntime.sleep(30)\n')
        buf = io.StringIO()
        start = datetime.now()
        with redirect_stdout(buf):
            result = cdu._execute_streaming(f'"{sys.executable}" "{script}"', timeout=2)
        self.assertEqual(result.returncode, 124)
        self.assertLess((datetime.now() - start).total_seconds(), 15)
        self.assertIn('PROGRESS_LINE', buf.getvalue())


class MarginCollectorNonTargetTest(unittest.TestCase):
    def test_non_target_writes_marker_and_stops_after_first_day(self):
        import batch_margin_collector as bmc
        tmp = tempfile.mkdtemp(prefix='gp_bmc_')
        self.addCleanup(shutil.rmtree, tmp, True)
        sh = pd.DataFrame({'标的证券代码': ['600000']})
        sz = pd.DataFrame({'证券代码': ['000001']})
        calls = []
        def fake_fetch(date_str):
            calls.append(date_str)
            return sh, sz
        with mock.patch.object(bmc, 'DATA_DIR', tmp), \
             mock.patch.object(bmc, 'get_margin_data_for_date', side_effect=fake_fetch), \
             mock.patch.object(bmc.time, 'sleep'), \
             redirect_stdout(io.StringIO()):
            summary = bmc.batch_collect_margin_data('20261116', '20261120', tickers=[TICKER])
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary['not_applicable'], [TICKER])
        self.assertTrue(os.path.isfile(os.path.join(tmp, TICKER, f'{TICKER}_margin_na.json')))

    def test_all_days_failed_returns_nonzero(self):
        import batch_margin_collector as bmc
        tmp = tempfile.mkdtemp(prefix='gp_bmc_')
        self.addCleanup(shutil.rmtree, tmp, True)
        argv = ['batch_margin_collector.py', '--ticker', TICKER,
                '--start_date', '20261119', '--end_date', '20261120']
        with mock.patch.object(bmc, 'DATA_DIR', tmp), \
             mock.patch.object(sys, 'argv', argv), \
             mock.patch.object(bmc, 'get_margin_data_for_date', return_value=(None, None)), \
             mock.patch.object(bmc.time, 'sleep'), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(bmc.main(), 2)


if __name__ == '__main__':
    unittest.main()
