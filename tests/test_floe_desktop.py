import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FloeDesktopAndSettingsTest(unittest.TestCase):
    """验证 Floe 桌面软件化核心机制：路径解耦、冻结态子进程路由、双语联动、检查更新、权限体检与安全备份。"""

    def test_app_paths_packaged_isolation_and_frozen_cmd_rewrite(self):
        import app_paths

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {'FLOE_USER_DATA_DIR': tmp}, clear=False):
                self.assertTrue(app_paths.is_packaged_mode())
                base = app_paths.ensure_user_data_layout()
                self.assertEqual(base, os.path.abspath(tmp))
                self.assertTrue(os.path.isdir(os.path.join(tmp, 'data')))
                self.assertTrue(os.path.isdir(os.path.join(tmp, 'stocks_filter')))
                self.assertTrue(os.path.isfile(os.path.join(tmp, 'watchlist.py')))
                self.assertTrue(os.path.isfile(os.path.join(tmp, 'trading_records.py')))

                # 模拟冻结二进制环境下的命令重写
                with mock.patch.object(sys, 'frozen', True, create=True):
                    cmd = app_paths.rewrite_shell_python_cmd('python check_data_updates.py --mode price')
                    self.assertIn('--run-script', cmd)
                    self.assertIn('check_data_updates.py', cmd)

                    argv = app_paths.python_script_argv('stocks_filter/step1_daily.py', '--trade-date', '20261120')
                    self.assertEqual(argv[1], '--run-script')
                    self.assertTrue(argv[2].endswith('step1_daily.py'))
                    self.assertEqual(argv[3:], ['--trade-date', '20261120'])

    def test_floe_launcher_cli_and_run_script_dispatcher(self):
        import version
        launcher = str(PROJECT_ROOT / 'floe_app.py')
        ver_proc = subprocess.run([sys.executable, launcher, '--version'], capture_output=True, text=True)
        self.assertEqual(ver_proc.returncode, 0)
        self.assertIn(f'Floe v{version.APP_VERSION}', ver_proc.stdout)

        with tempfile.TemporaryDirectory() as tmp:
            mini_script = pathlib.Path(tmp) / 'hello_sub.py'
            mini_script.write_text('import sys\nprint("SUB_OK:" + ",".join(sys.argv[1:]))\n', encoding='utf-8')
            sub_proc = subprocess.run(
                [sys.executable, launcher, '--run-script', str(mini_script), '--alpha', '123'],
                capture_output=True,
                text=True,
            )
            self.assertEqual(sub_proc.returncode, 0)
            self.assertIn('SUB_OK:--alpha,123', sub_proc.stdout)

    def test_offline_vendor_assets_and_floe_branding_served(self):
        import web_ui
        client = web_ui.app.test_client()

        html = client.get('/').get_data(as_text=True)
        self.assertNotIn('cdn.jsdelivr.net', html)
        self.assertNotIn('topbar-quick-code', html)
        self.assertIn('/static/vendor/bootstrap.min.css', html)
        self.assertIn('/static/js/i18n.js', html)
        self.assertIn('/static/icons/floe_icon_bull.png', html)
        self.assertIn('/static/icons/floe_icon_bear.png', html)
        self.assertIn('适合中国宝宝体质的 A 股选股软件', html)
        self.assertIn('关于我们', html)
        self.assertIn('https://github.com/Leo-luxy/Floe', html)
        self.assertIn('luleo856@gmail.com', html)

        for asset_url in (
            '/static/vendor/bootstrap.min.css',
            '/static/vendor/bootstrap.bundle.min.js',
            '/static/vendor/marked.min.js',
            '/static/js/i18n.js',
            '/static/icons/floe_icon.png',
            '/static/icons/floe_icon_bull.png',
            '/static/icons/floe_icon_bear.png',
        ):
            resp = client.get(asset_url)
            self.assertEqual(resp.status_code, 200, asset_url)
            resp.close()

    def test_language_preference_injects_english_directive_into_llm(self):
        import web_ui
        import user_settings as us

        with tempfile.TemporaryDirectory() as tmp:
            fake_settings = str(pathlib.Path(tmp) / 'user_settings.json')
            with mock.patch.object(us, 'SETTINGS_FILE', fake_settings):
                client = web_ui.app.test_client()
                res = client.post('/api/settings/save_preferences', json={'language': 'en-US', 'icon_variant': 'bear'}).get_json()
                self.assertTrue(res['success'])
                self.assertEqual(res['preferences']['icon_variant'], 'bear')
                self.assertEqual(us.get_ui_language(), 'en-US')

                msgs = [{'role': 'user', 'content': '请结合技术指标给出详细买卖分析与仓位计划。' * 3}]
                prepared = us._prepare_messages_for_language(msgs)
                self.assertEqual(prepared[0]['role'], 'system')
                self.assertIn('English', prepared[0]['content'])

                # 切回中文后不再注入英文系统指令
                client.post('/api/settings/save_preferences', json={'language': 'zh-CN'})
                self.assertEqual(us.get_ui_language(), 'zh-CN')
                self.assertEqual(len(us._prepare_messages_for_language(msgs)), 1)

    def test_check_update_and_diagnostics_and_backup_security(self):
        import web_ui
        import user_settings as us
        import app_paths

        fake_release = {
            'tag_name': 'v2.1.0',
            'name': 'Floe Version 2.1.0',
            'published_at': '2026-12-01T10:00:00Z',
            'html_url': 'https://github.com/Leo-luxy/Floe/releases/tag/v2.1.0',
            'body': '### New features\n- Faster backtest',
            'assets': [
                {
                    'name': 'Floe-v2.1.0-macos-arm64.dmg',
                    'browser_download_url': 'https://github.com/Leo-luxy/Floe/releases/download/v2.1.0/Floe-v2.1.0-macos-arm64.dmg',
                    'size': 85 * 1024 * 1024,
                },
                {
                    'name': 'Floe-v2.1.0-windows-x64.zip',
                    'browser_download_url': 'https://github.com/Leo-luxy/Floe/releases/download/v2.1.0/Floe-v2.1.0-windows-x64.zip',
                    'size': 90 * 1024 * 1024,
                },
            ],
        }

        class _FakeResp:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps(fake_release).encode('utf-8')

        with tempfile.TemporaryDirectory() as tmp:
            fake_settings = os.path.join(tmp, 'user_settings.json')
            with mock.patch.dict(os.environ, {'FLOE_USER_DATA_DIR': tmp, 'FLOE_INSTALL_CHANNEL': 'homebrew'}, clear=False), \
                 mock.patch.object(us, 'SETTINGS_FILE', fake_settings):
                app_paths.ensure_user_data_layout(tmp)
                us.save_user_settings({'ui': {'language': 'zh-CN'}})

                client = web_ui.app.test_client()

                with mock.patch('urllib.request.urlopen', return_value=_FakeResp()):
                    upd = client.get('/api/settings/check_update').get_json()
                self.assertTrue(upd['success'])
                self.assertTrue(upd['has_update'])
                self.assertEqual(upd['latest_version'], '2.1.0')
                self.assertEqual(upd['upgrade_command'], 'brew upgrade --cask floe')

                with mock.patch('urllib.request.urlopen', return_value=_FakeResp()):
                    diag = client.get('/api/settings/diagnostics').get_json()
                self.assertTrue(diag['success'])
                self.assertTrue(any(c['id'] == 'storage' and c['ok'] for c in diag['checks']))

                # 导出合法备份并重新导入恢复
                exp_resp = client.get('/api/settings/export_backup')
                self.assertEqual(exp_resp.status_code, 200)
                zip_bytes = exp_resp.get_data()
                exp_resp.close()

                imp_ok = client.post(
                    '/api/settings/import_backup',
                    data={'file': (io.BytesIO(zip_bytes), 'Floe_backup.zip')},
                    content_type='multipart/form-data',
                ).get_json()
                self.assertTrue(imp_ok['success'])

                # 安全拦截测试：构造含有恶意函数调用的篡改 watchlist.py 备份包，必须拒绝执行与导入
                evil_buf = io.BytesIO()
                with zipfile.ZipFile(evil_buf, 'w') as zf:
                    zf.writestr('watchlist.py', '__import__("os").system("echo pwned")\nWATCHLIST = []\n')
                evil_buf.seek(0)
                imp_evil = client.post(
                    '/api/settings/import_backup',
                    data={'file': (evil_buf, 'evil.zip')},
                    content_type='multipart/form-data',
                ).get_json()
                self.assertFalse(imp_evil['success'])

    def test_windows_appdata_permission_denied_falls_back_to_portable_dir(self):
        """复现 Windows 受控文件夹访问 / 安全管家拦截 AppData 与 Temp ([WinError 5] 拒绝访问) 时的自动便携回退。"""
        import app_paths
        import user_settings as us

        orig_tempdir = tempfile.tempdir
        orig_sys_path = list(sys.path)
        orig_sf = us.SETTINGS_FILE
        orig_init_sf = us._INITIAL_SETTINGS_FILE
        try:
            with tempfile.TemporaryDirectory() as sandbox:
                # 模拟中文路径下的 D 盘绿色解压目录与受拦截的 C:\Users\user\AppData
                fake_c_appdata = os.path.join(sandbox, 'C_Users_user_AppData_Roaming')
                fake_c_local = os.path.join(sandbox, 'C_Users_user_AppData_Local')
                fake_c_temp = os.path.join(fake_c_local, 'Temp')
                portable_app_dir = os.path.join(sandbox, '量化工具', '桌面版', 'Floe', 'Floe')
                os.makedirs(portable_app_dir, exist_ok=True)
                fake_exe = os.path.join(portable_app_dir, 'Floe.exe')

                # 预建 Roaming\Floe 空目录，验证即使目录本身已存在但内部拒写也能被探针识破并回退
                os.makedirs(os.path.join(fake_c_appdata, 'Floe'), exist_ok=True)

                real_makedirs = os.makedirs
                real_open = open

                def _guarded_makedirs(path, *args, **kwargs):
                    abs_p = os.path.abspath(str(path))
                    if abs_p.startswith(os.path.abspath(fake_c_appdata)) or abs_p.startswith(os.path.abspath(fake_c_local)):
                        raise PermissionError(13, '[WinError 5] 拒绝访问。', abs_p)
                    return real_makedirs(path, *args, **kwargs)

                def _guarded_open(file, mode='r', *args, **kwargs):
                    abs_f = os.path.abspath(str(file))
                    if ('w' in mode or 'a' in mode or '+' in mode) and (
                        abs_f.startswith(os.path.abspath(fake_c_appdata))
                        or abs_f.startswith(os.path.abspath(fake_c_local))
                    ):
                        raise PermissionError(13, '[WinError 5] 拒绝访问。', abs_f)
                    return real_open(file, mode, *args, **kwargs)

                env_overrides = {
                    'FLOE_PACKAGED': '1',
                    'FLOE_USER_DATA_DIR': '',
                    'APPDATA': fake_c_appdata,
                    'LOCALAPPDATA': fake_c_local,
                    'TEMP': fake_c_temp,
                    'TMP': fake_c_temp,
                    'TMPDIR': fake_c_temp,
                    'WEBVIEW2_USER_DATA_FOLDER': '',
                    'MPLCONFIGDIR': '',
                }

                app_paths.reset_path_cache()
                with mock.patch.dict(os.environ, env_overrides, clear=False), \
                     mock.patch.object(os, 'name', 'nt'), \
                     mock.patch.object(sys, 'platform', 'win32'), \
                     mock.patch.object(sys, 'frozen', True, create=True), \
                     mock.patch.object(sys, 'executable', fake_exe), \
                     mock.patch('os.makedirs', side_effect=_guarded_makedirs), \
                     mock.patch('builtins.open', side_effect=_guarded_open):

                    resolved = app_paths.activate_runtime_paths()
                    expected_portable = os.path.join(portable_app_dir, 'Floe_Data')
                    self.assertEqual(os.path.abspath(resolved), os.path.abspath(expected_portable))
                    self.assertTrue(app_paths.is_using_fallback_data_dir())

                    # 验证子目录、基础配置及运行时缓存目录全部落在可写的便携目录内
                    for sub in ('data', 'stocks_filter', 'backup', 'log', 'tmp'):
                        self.assertTrue(os.path.isdir(os.path.join(expected_portable, sub)), sub)
                    self.assertTrue(os.path.isfile(os.path.join(expected_portable, 'watchlist.py')))
                    self.assertTrue(os.path.isfile(os.path.join(expected_portable, 'trading_records.py')))
                    self.assertEqual(os.environ['TEMP'], os.path.join(expected_portable, 'tmp'))
                    self.assertTrue(os.environ['WEBVIEW2_USER_DATA_FOLDER'].startswith(expected_portable))
                    self.assertTrue(os.environ['MPLCONFIGDIR'].startswith(expected_portable))

                    # 模拟用户在便携目录保存了设置；后续即使 AppData 恢复可写，也必须继续沿用便携目录不丢配置
                    with real_open(os.path.join(expected_portable, 'user_settings.json'), 'w', encoding='utf-8') as fh:
                        fh.write('{"ui": {"language": "zh-CN"}}')

                app_paths.reset_path_cache()
                with mock.patch.dict(os.environ, env_overrides, clear=False), \
                     mock.patch.object(os, 'name', 'nt'), \
                     mock.patch.object(sys, 'platform', 'win32'), \
                     mock.patch.object(sys, 'frozen', True, create=True), \
                     mock.patch.object(sys, 'executable', fake_exe):
                    second_run = app_paths.get_user_data_dir()
                    self.assertEqual(os.path.abspath(second_run), os.path.abspath(expected_portable))
        finally:
            tempfile.tempdir = orig_tempdir
            sys.path[:] = orig_sys_path
            us.SETTINGS_FILE = orig_sf
            us._INITIAL_SETTINGS_FILE = orig_init_sf
            app_paths.reset_path_cache()

    def test_packaged_ssl_ca_bundle_and_github_proxy_fallback(self):
        """复现 GitHub Actions 打包二进制丢失 runner 硬编码证书路径导致的 SSL 报错，及直连下境外检查更新局部代理回退。"""
        import ssl
        import urllib.error
        import urllib.request
        import app_paths
        import net_guard

        dead_runner_cert = '/Users/runner/hostedtoolcache/Python/3.10.15/arm64/etc/openssl/cert.pem'
        with mock.patch.dict(os.environ, {
            'SSL_CERT_FILE': dead_runner_cert,
            'REQUESTS_CA_BUNDLE': dead_runner_cert,
            'CURL_CA_BUNDLE': '',
        }, clear=False):
            ca_file = app_paths.ensure_ssl_certificates()
            self.assertTrue(ca_file and os.path.isfile(ca_file), f'Expected valid CA bundle, got: {ca_file}')
            self.assertEqual(os.environ['SSL_CERT_FILE'], ca_file)
            self.assertEqual(os.environ['REQUESTS_CA_BUNDLE'], ca_file)

            ctx = ssl._create_default_https_context()
            self.assertGreater(len(ctx.get_ca_certs()), 0)

            sub_env = app_paths.subprocess_env()
            self.assertEqual(sub_env.get('SSL_CERT_FILE'), ca_file)
            self.assertEqual(sub_env.get('REQUESTS_CA_BUNDLE'), ca_file)

        # 验证默认国内直连模式下，访问 GitHub Release 超时且本机代理存活时可无污染局部重试成功
        class _ProxyResp:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"tag_name": "v2.0.1"}'

        captured_proxy = {}

        class _FakeOpener:
            def open(self, req_obj, timeout=None):
                captured_proxy['url'] = req_obj.full_url
                return _ProxyResp()

        def _fake_build_opener(*handlers):
            for h in handlers:
                if hasattr(h, 'proxies'):
                    captured_proxy['proxies'] = dict(h.proxies)
            return _FakeOpener()

        net_guard.reconfigure_network_mode('direct')
        self.assertEqual(os.environ.get('no_proxy'), '*')

        # 刻意传入 Windows 注册表常见的错误 https://127.0.0.1:10808 格式，验证自动纠正为 http:// 隧道
        req = urllib.request.Request('https://api.github.com/repos/Leo-luxy/Floe/releases/latest')
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError(TimeoutError('timed out'))), \
             mock.patch.object(net_guard, '_raw_system_proxy_dict', return_value={'https': 'https://127.0.0.1:10808'}), \
             mock.patch.object(net_guard, '_reachable', return_value=True), \
             mock.patch('urllib.request.build_opener', side_effect=_fake_build_opener):
            with net_guard.urlopen_with_optional_proxy(req, timeout=3.0) as resp:
                payload = json.loads(resp.read().decode('utf-8'))

        self.assertEqual(payload['tag_name'], 'v2.0.1')
        self.assertEqual(captured_proxy.get('url'), 'https://api.github.com/repos/Leo-luxy/Floe/releases/latest')
        self.assertEqual(captured_proxy.get('proxies'), {
            'http': 'http://127.0.0.1:10808',
            'https': 'http://127.0.0.1:10808',
        })
        # 全局必须继续保持国内直连保护，不污染 A 股数据源采集
        self.assertEqual(os.environ.get('no_proxy'), '*')

    def test_domestic_cdn_update_fallback_and_multi_feed_diagnostics(self):
        """验证纯国内无梯子网络下检查更新自动回退国内 CDN 版本源，以及行情网关单点 RemoteDisconnected 自动多源切换。"""
        import http.client
        import urllib.error
        import web_ui
        import net_guard

        client = web_ui.app.test_client()

        fake_ver_py = (
            'APP_VERSION = "2.2.0"\n'
            'RELEASE_CHANGELOG_ZH = "### Floe v2.2.0 更新\\n- 纯国内免代理检查更新"\n'
            'RELEASE_CHANGELOG_EN = "### Floe v2.2.0\\n- Domestic CDN update check"\n'
        ).encode('utf-8')

        class _CdnResp:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return fake_ver_py

        class _CdnOpener:
            def open(self, req_obj, timeout=None):
                return _CdnResp()

        with mock.patch.object(net_guard, 'urlopen_with_optional_proxy', side_effect=urllib.error.URLError('network unreachable')), \
             mock.patch('urllib.request.build_opener', return_value=_CdnOpener()):
            upd = client.get('/api/settings/check_update').get_json()

        self.assertTrue(upd['success'])
        self.assertTrue(upd['has_update'])
        self.assertEqual(upd['latest_version'], '2.2.0')
        self.assertIsNotNone(upd['recommended_asset'])

        # 模拟第 1 个行情网关抛 RemoteDisconnected，第 2 个网关正常返回 200
        call_idx = {'n': 0}

        class _OkFeedResp:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        def _flaky_urlopen(req_obj, timeout=None):
            call_idx['n'] += 1
            if call_idx['n'] == 1:
                raise http.client.RemoteDisconnected('Remote end closed connection without response')
            return _OkFeedResp()

        with mock.patch('urllib.request.urlopen', side_effect=_flaky_urlopen):
            diag = client.get('/api/settings/diagnostics').get_json()

        self.assertTrue(diag['success'])
        market_chk = next(c for c in diag['checks'] if c['id'] == 'market_network')
        self.assertTrue(market_chk['ok'], market_chk)
        self.assertGreaterEqual(call_idx['n'], 2)

    def test_frozen_selection_subprocesses_never_spawn_second_gui_window(self):
        """回归测试：冻结态选股预检 collect_market 必须走 --run-script，且子进程守卫阻止嵌套弹出第二个应用窗口。"""
        import stocks_filter.batch_backtest_filter as bbf

        captured_calls = []

        def _fake_run(cmd, *args, **kwargs):
            captured_calls.append((cmd, kwargs.get('env') or {}))
            return subprocess.CompletedProcess(cmd, 0, stdout='ok', stderr='')

        fake_frozen_exe = '/Applications/Floe.app/Contents/MacOS/floe'
        with mock.patch.object(sys, 'frozen', True, create=True), \
             mock.patch.object(sys, 'executable', fake_frozen_exe), \
             mock.patch.object(bbf.subprocess, 'run', side_effect=_fake_run):
            bbf.collect_market('002939.SZ')

        self.assertEqual(len(captured_calls), 1)
        issued_cmd, issued_env = captured_calls[0]
        self.assertIn('--run-script', issued_cmd)
        self.assertIn('data_collector.py', issued_cmd)
        self.assertEqual(issued_env.get('FLOE_SUBPROCESS'), '1')

        # 防线验证 1：当 FLOE_SUBPROCESS=1 的子进程意外未带脚本参数调用 floe_app.py 时，必须立即返回码 2 拒绝启动新窗口
        launcher = str(PROJECT_ROOT / 'floe_app.py')
        nested_env = os.environ.copy()
        nested_env['FLOE_SUBPROCESS'] = '1'
        nested_proc = subprocess.run(
            [sys.executable, launcher, '--dev'],
            capture_output=True,
            text=True,
            env=nested_env,
            timeout=10,
        )
        self.assertEqual(nested_proc.returncode, 2)
        self.assertIn('Refusing to launch nested GUI/server', nested_proc.stderr)

        # 防线验证 2：模拟冻结态下漏传 --run-script、直接传 bare .py 脚本时，_dispatch_internal_script 仍自动接管不弹窗
        with tempfile.TemporaryDirectory() as tmp:
            bare_script = pathlib.Path(tmp) / 'bare_job.py'
            bare_script.write_text('import sys\nprint("BARE_OK:" + ",".join(sys.argv[1:]))\n', encoding='utf-8')
            shim = (
                'import sys\n'
                'sys.frozen = True\n'
                f'sys.argv = ["floe", {str(bare_script)!r}, "--ticker", "002939.SZ"]\n'
                'import floe_app\n'
            )
            shim_proc = subprocess.run(
                [sys.executable, '-c', shim],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(shim_proc.returncode, 0, shim_proc.stderr)
            self.assertIn('BARE_OK:--ticker,002939.SZ', shim_proc.stdout)

    def test_step2_daily_basic_fallback_and_selection_log_preservation(self):
        """验证 Tushare 免费账号无 daily_basic 2000 积分权限时的同日全集备用补齐、跨日拦截，以及选股失败日志不丢失。"""
        import pandas as pd
        import api.stock_selection as sel_api
        import stocks_filter.step2_daily_basic as step2

        self.assertTrue(step2.is_permission_error(Exception('抱歉，您没有访问该接口的权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108')))

        df_daily = pd.DataFrame([
            {'ts_code': '000001.SZ', 'trade_date': '20261120', 'vol': 120000.0},
            {'ts_code': '600519.SH', 'trade_date': '20261120', 'vol': 35000.0},
        ])

        def _build_gtimg_line(sym, ts_stamp, turnover, pe_ttm, circ_yi, total_yi, pb, vol_ratio):
            fields = [''] * 55
            fields[30] = ts_stamp
            fields[38] = str(turnover)
            fields[39] = str(pe_ttm)
            fields[44] = str(circ_yi)
            fields[45] = str(total_yi)
            fields[46] = str(pb)
            fields[49] = str(vol_ratio)
            return f'v_{sym}="' + '~'.join(fields) + '";'

        fake_body_ok = (
            _build_gtimg_line('sz000001', '20261120161500', '3.25', '6.1', '2100.0', '2200.5', '0.65', '1.18')
            + _build_gtimg_line('sh600519', '20261120161500', '2.40', '22.5', '18000.0', '18500.0', '7.20', '1.05')
        )

        class _FakeHTTPResp:
            def __init__(self, text):
                self.text = text
                self.encoding = 'gbk'
            def raise_for_status(self):
                return None

        class _FakeSession:
            def __init__(self, text):
                self.text = text
            def get(self, url, timeout=12):
                return _FakeHTTPResp(self.text)

        # 1. 同交易日且 100% 覆盖全部代码：应成功返回并精确换算总市值（亿元 -> 万元）
        fb_ok, err_ok = step2.fetch_gtimg_daily_basic_same_date(
            '20261120', df_daily, session_factory=lambda: _FakeSession(fake_body_ok)
        )
        self.assertIsNotNone(fb_ok, err_ok)
        self.assertEqual(len(fb_ok), 2)
        row_sz = fb_ok[fb_ok['ts_code'] == '000001.SZ'].iloc[0]
        self.assertAlmostEqual(float(row_sz['turnover_rate']), 3.25)
        self.assertAlmostEqual(float(row_sz['total_mv']), 2200.5 * 10000.0)

        # 2. 请求历史回退日 20261119，但实时网关已是 20261120：必须严格拒绝跨日混用
        fb_mismatch, err_mismatch = step2.fetch_gtimg_daily_basic_same_date(
            '20261119', df_daily, session_factory=lambda: _FakeSession(fake_body_ok)
        )
        self.assertIsNone(fb_mismatch)
        self.assertIn('禁止跨日混用', err_mismatch)

        # 3. 选股子进程失败时，详细报错行不得被 messages.copy() 覆盖清空，且状态文件须更新为 failed
        with tempfile.TemporaryDirectory() as tmp_sel:
            with mock.patch.object(sel_api, 'SELECTION_DIR', tmp_sel):
                def _fake_step_runner(tid, cmd, cwd, desc):
                    sel_api.selection_tasks[tid]['messages'].append('子进程真实报错详情：Tushare token 无效')
                    return 2

                with mock.patch.object(sel_api, 'run_command_with_output', side_effect=_fake_step_runner):
                    sel_api.run_selection('test_log_keep', True, False)

                task_info = sel_api.selection_tasks['test_log_keep']
                self.assertEqual(task_info['status'], 'failed')
                joined_msgs = '\n'.join(task_info['messages'])
                self.assertIn('子进程真实报错详情：Tushare token 无效', joined_msgs)

                with open(os.path.join(tmp_sel, 'final_holdings_status.json'), encoding='utf-8') as fh:
                    st_disk = json.load(fh)
                self.assertEqual(st_disk.get('state'), 'failed')

    def test_cross_client_readonly_bundle_and_quote_fallbacks(self):
        """跨客户端审计回归测试：新设备缺失申万目录不崩溃、两层决策读写隔离数据目录、东财断连时关注池与台账自动兜底腾讯行情。"""
        import config
        import api.settings as set_api
        import api.trading as tr_api
        import api.watchlist as wl_api
        from Process.multi_strategy_analyzer import MultiStrategyAnalyzer
        from Process.two_layer_decision_analyzer import TwoLayerDecisionAnalyzer
        from shenwan_config.shenwan_industry_thresholds import ShenwanIndustryThresholds

        with tempfile.TemporaryDirectory() as isolated_data:
            # 1. 新安装设备尚无 shenwan_industry 目录：不得抛出 FileNotFoundError
            missing_sw_dir = os.path.join(isolated_data, 'shenwan_industry_not_created_yet')
            sw = ShenwanIndustryThresholds(data_dir=missing_sw_dir)
            self.assertEqual(sw.industry_averages, {})

            # 2. 两层决策与多策略分析器必须跟随 config.DATA_DIR（用户隔离目录），绝不写入只读应用包
            with mock.patch.object(config, 'DATA_DIR', isolated_data):
                tla = TwoLayerDecisionAnalyzer('300433.SZ')
                msa = MultiStrategyAnalyzer('300433.SZ')
                self.assertEqual(os.path.abspath(tla.data_dir), os.path.abspath(os.path.join(isolated_data, '300433.SZ')))
                self.assertEqual(os.path.abspath(msa.data_dir), os.path.abspath(os.path.join(isolated_data, '300433.SZ')))

            # 3. 东方财富 push2 被断连时，关注池简称查询与交易台账现价查询自动回退腾讯行情
            class _FakeGtResp:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
                def read(self):
                    return 'v_sz002939="51~长城证券~002939~8.65~8.50~8.52~";'.encode('gbk')

            def _mock_urlopen(req, timeout=None):
                url = req.full_url if hasattr(req, 'full_url') else str(req)
                if 'eastmoney.com' in url:
                    raise ConnectionResetError('RemoteDisconnected')
                if 'qt.gtimg.cn' in url:
                    return _FakeGtResp()
                raise RuntimeError(f'Unexpected URL: {url}')

            with mock.patch.object(wl_api, 'DATA_DIR', isolated_data), \
                 mock.patch.object(tr_api, 'DATA_DIR', isolated_data), \
                 mock.patch.object(wl_api, 'load_watchlist', return_value=[]), \
                 mock.patch('urllib.request.urlopen', side_effect=_mock_urlopen):
                resolved_name = wl_api.resolve_stock_name('002939.SZ', allow_remote=True)
                self.assertEqual(resolved_name, '长城证券')

                q_name, q_price, q_src = tr_api._resolve_latest_quote('002939.SZ', allow_remote=True)
                self.assertEqual(q_name, '长城证券')
                self.assertAlmostEqual(float(q_price), 8.65)
                self.assertEqual(q_src, '实时现价')

            # 4. Linux 客户端在检查更新合成列表中优先匹配 .AppImage
            with mock.patch.object(sys, 'platform', 'linux'), \
                 mock.patch('platform.machine', return_value='x86_64'):
                picked = set_api._match_platform_asset([
                    {'name': 'Floe-v2.0.2-linux-x64.tar.gz', 'browser_download_url': 'https://example.com/a.tar.gz', 'size': 0},
                    {'name': 'Floe-v2.0.2-linux-x86_64.AppImage', 'browser_download_url': 'https://example.com/a.AppImage', 'size': 0},
                ])
                self.assertEqual(picked['name'], 'Floe-v2.0.2-linux-x86_64.AppImage')

    def test_mini_racer_dependency_pin_and_no_v8_qfq_fallback(self):
        """回归测试：requirements.txt 严禁出现覆盖损坏 Windows V8 引擎的旧包 py_mini_racer，且 V8 受限时自动回退纯 JSON 前复权。"""
        import pandas as pd
        import data_collector as dc

        req_lines = [
            ln.split('#', 1)[0].strip()
            for ln in (PROJECT_ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines()
        ]
        req_lines = [ln for ln in req_lines if ln]
        self.assertNotIn('py_mini_racer', req_lines)
        self.assertNotIn('py-mini-racer', req_lines)
        self.assertTrue(any(ln.startswith('mini-racer') for ln in req_lines))

        fake_em_raw = pd.DataFrame([
            {
                '日期': '2026-11-20',
                '开盘': 4.50,
                '收盘': 4.68,
                '最高': 4.72,
                '最低': 4.48,
                '成交量': 500000,       # 50万手 -> 5000万股
                '成交额': 230000000.0,
                '换手率': 2.50,         # 2.50% -> 0.025
            }
        ])

        with mock.patch.object(dc, 'stock_zh_a_daily', side_effect=ImportError('LibNotFoundError: mini_racer.dll')), \
             mock.patch('akshare.stock_zh_a_hist', return_value=fake_em_raw):
            out = dc._fetch_qfq_history('sz000100', '20261101', '20261120')

        self.assertEqual(len(out), 1)
        self.assertEqual(list(out.columns), [
            'date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'outstanding_share', 'turnover'
        ])
        self.assertAlmostEqual(float(out.iloc[0]['close']), 4.68)
        self.assertAlmostEqual(float(out.iloc[0]['volume']), 500000 * 100.0)
        self.assertAlmostEqual(float(out.iloc[0]['turnover']), 0.025)

    def test_cloud_llm_long_timeout_not_truncated_and_https_proxy_tunnel_preserved(self):
        """回归测试：云端 DeepSeek 180s 长超时在本机代理存在时不得被截断为 3s；直连不可达时 HTTPS 隧道保持 https 协议。"""
        import urllib.request
        import net_guard
        import user_settings as us

        net_guard.reconfigure_network_mode('direct')
        seen_timeouts = []

        class _OkLlmResp:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        def _capture_urlopen(req_obj, timeout=None):
            seen_timeouts.append(timeout)
            return _OkLlmResp()

        req = urllib.request.Request('https://api.deepseek.com/chat/completions', data=b'{}', method='POST')
        with mock.patch.object(net_guard, '_raw_system_proxy_dict', return_value={'https': 'http://127.0.0.1:7897'}), \
             mock.patch.object(net_guard, '_reachable', return_value=True), \
             mock.patch('urllib.request.urlopen', side_effect=_capture_urlopen):
            with net_guard.urlopen_with_optional_proxy(req, timeout=180) as resp:
                self.assertIn(b'choices', resp.read())
        self.assertEqual(seen_timeouts, [180])

        # 当直连 TCP 不可达时，走显式代理构建器，且 HTTPS 请求保持 set_proxy(hostport, 'https')
        seen_proxy_calls = []

        class _MockReq:
            def __init__(self):
                self.type = 'https'
                self.host = 'api.deepseek.com'
                self.full_url = 'https://api.deepseek.com/chat/completions'
                self._tunnel_host = None
                self.timeout = 180

            def add_header(self, k, v):
                pass

            def set_proxy(self, hostport, p_type):
                seen_proxy_calls.append((hostport, p_type))
                self._tunnel_host = self.host
                self.host = hostport

        captured_handlers = []

        class _OkOpener:
            def open(self, r_obj, timeout=None):
                seen_timeouts.append(('proxy', timeout))
                return _OkLlmResp()

        def _fake_opener(*handlers):
            captured_handlers.extend(handlers)
            return _OkOpener()

        with mock.patch.object(net_guard, '_raw_system_proxy_dict', return_value={'https': 'http://127.0.0.1:7897'}), \
             mock.patch.object(net_guard, '_reachable', side_effect=lambda h, p, timeout=0.6: h == '127.0.0.1'), \
             mock.patch('urllib.request.build_opener', side_effect=_fake_opener):
            with net_guard.urlopen_with_optional_proxy(req, timeout=180) as resp:
                self.assertIn(b'choices', resp.read())
            proxy_handler = next(h for h in captured_handlers if hasattr(h, 'proxy_open'))
            proxy_handler.proxy_open(_MockReq(), 'http://127.0.0.1:7897', 'https')

        self.assertIn(('proxy', 180), seen_timeouts)
        self.assertEqual(seen_proxy_calls, [('127.0.0.1:7897', 'https')])

        # 验证云端 API 文案提示不再误导为检查 Ollama 服务
        api_cfg = {'provider': 'api', 'api_base': 'https://api.deepseek.com', 'api_key': 'sk-test-123456', 'api_model': 'deepseek-chat'}
        desc = us.describe_ai_backend(api_cfg)
        err_hint = us.format_ai_error_hint(api_cfg, TimeoutError('read timed out'))
        self.assertIn('云端 API', desc)
        self.assertIn('deepseek-chat', desc)
        self.assertNotIn('Ollama', err_hint)
        self.assertIn('云端 API', err_hint)
        self.assertIn('read timed out', err_hint)

    def test_cloud_llm_omits_max_tokens_for_large_reports_and_retries_reasoning_truncation(self):
        """回归测试：研报分析不硬塞 max_tokens=8192，空正文自动自愈重试并支持非标 400 回退。"""
        import urllib.error
        import user_settings as us

        def _make_resp(payload_obj):
            raw = json.dumps(payload_obj).encode('utf-8')

            class _Resp:
                status = 200
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
                def read(self):
                    return raw
            return _Resp()

        sent_payloads = []
        responses = [
            # 1) 首次返回思考链截断空正文
            _make_resp({
                'model': 'deepseek-flash',
                'choices': [{
                    'finish_reason': 'length',
                    'message': {'role': 'assistant', 'content': '', 'reasoning_content': 'long thinking...'},
                }],
            }),
            # 2) 自愈重试后返回正常正文
            _make_resp({
                'model': 'deepseek-flash',
                'choices': [{
                    'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': '完整报告正文'},
                }],
            }),
        ]

        def _fake_cloud_urlopen(req, timeout=None):
            sent_payloads.append(json.loads(req.data.decode('utf-8')))
            return responses.pop(0)

        with mock.patch.object(us, 'get_ui_language', return_value='zh-CN'), \
             mock.patch.object(us, '_urlopen_cloud_api', side_effect=_fake_cloud_urlopen):
            res = us.call_openai_compatible_chat(
                api_base='https://api.deepseek.com',
                api_key='sk-test-123456',
                model='deepseek-flash',
                messages=[{'role': 'user', 'content': '分析融资融券数据'}],
                options={'temperature': 0.3, 'num_predict': 8192},
            )

        self.assertEqual(res['message']['content'], '完整报告正文')
        self.assertEqual(len(sent_payloads), 2)
        self.assertNotIn('max_tokens', sent_payloads[0])
        self.assertNotIn('max_tokens', sent_payloads[1])
        self.assertEqual(len(sent_payloads[1]['messages']), 2)
        self.assertIn('精简中间计算', sent_payloads[1]['messages'][-1]['content'])

        # 场景 B：两次均为空正文（思考耗尽上限），必须抛 RuntimeError 而非静默写空文件
        exhausted_resps = [
            _make_resp({
                'model': 'deepseek-flash',
                'choices': [{'finish_reason': 'length', 'message': {'content': '', 'reasoning_content': 'step 1'}}],
            }),
            _make_resp({
                'model': 'deepseek-flash',
                'choices': [{'finish_reason': 'length', 'message': {'content': '', 'reasoning_content': 'step 2'}}],
            }),
        ]
        with mock.patch.object(us, 'get_ui_language', return_value='zh-CN'), \
             mock.patch.object(us, '_urlopen_cloud_api', side_effect=lambda req, timeout=None: exhausted_resps.pop(0)):
            with self.assertRaises(RuntimeError) as ctx:
                us.call_openai_compatible_chat(
                    api_base='https://api.deepseek.com',
                    api_key='sk-test-123456',
                    model='deepseek-flash',
                    messages=[{'role': 'user', 'content': '分析资金流'}],
                    options={'temperature': 0.3, 'num_predict': 8192},
                )
        self.assertIn('思考过程耗尽', str(ctx.exception))

        # 场景 C：非标网关要求必传 max_tokens 返回 HTTP 400，应自动回退 max_tokens=8192 重试
        fallback_payloads = []

        def _fake_strict_gateway(req, timeout=None):
            body = json.loads(req.data.decode('utf-8'))
            fallback_payloads.append(body)
            if 'max_tokens' not in body:
                raise urllib.error.HTTPError(
                    req.full_url, 400, 'Bad Request', {},
                    io.BytesIO(b'{"error":{"message":"max_tokens is required"}}'),
                )
            return _make_resp({
                'model': 'custom-model',
                'choices': [{'finish_reason': 'stop', 'message': {'content': '网关回退成功'}}],
            })

        with mock.patch.object(us, 'get_ui_language', return_value='zh-CN'), \
             mock.patch.object(us, '_urlopen_cloud_api', side_effect=_fake_strict_gateway):
            res_fb = us.call_openai_compatible_chat(
                api_base='https://example.invalid',
                api_key='sk-test-123456',
                model='custom-model',
                messages=[{'role': 'user', 'content': '测试'}],
                options={'temperature': 0.3, 'num_predict': 8192},
            )
        self.assertEqual(res_fb['message']['content'], '网关回退成功')
        self.assertEqual(len(fallback_payloads), 2)
        self.assertNotIn('max_tokens', fallback_payloads[0])
        self.assertEqual(fallback_payloads[1].get('max_tokens'), 8192)

    def test_valuation_analyzer_loads_company_basic_and_two_layer_gets_price_when_flat(self):
        """回归测试：估值分析支持读取 _company_basic.json；两层决策空仓时仍填充当前价格（含 qfq 回退）。"""
        import analyze_valuation_data as avd
        from Process.two_layer_decision_analyzer import TwoLayerDecisionAnalyzer

        with tempfile.TemporaryDirectory() as tmp:
            ticker = '600519.SH'
            stock_dir = os.path.join(tmp, ticker)
            os.makedirs(stock_dir, exist_ok=True)
            with open(os.path.join(stock_dir, f'{ticker}_company_basic.json'), 'w', encoding='utf-8') as f:
                json.dump({'basic_info': {'公司简称': '贵州茅台'}}, f, ensure_ascii=False)
            val_path = os.path.join(stock_dir, f'{ticker}_valuation.csv')
            with open(val_path, 'w', encoding='utf-8') as f:
                f.write('数据日期,当日收盘价,PE(TTM)\n2026-11-20,1520.5,24.1\n')
            with open(os.path.join(stock_dir, f'{ticker}_qfq.csv'), 'w', encoding='utf-8') as f:
                f.write('date,close\n2026-11-20,1519.8\n')

            with mock.patch.object(avd, 'DATA_DIR', tmp):
                info = avd.load_company_info(ticker)
            self.assertIsNotNone(info)
            self.assertEqual(info.get('basic_info', {}).get('公司简称'), '贵州茅台')

            analyzer = TwoLayerDecisionAnalyzer(ticker)
            analyzer.data_dir = stock_dir
            pos_val = analyzer.get_position_info({})
            self.assertAlmostEqual(float(pos_val['current_price']), 1520.5)

            # 删除 _valuation.csv 后，验证空仓时回退读取 _qfq.csv 的 close
            os.unlink(val_path)
            pos_qfq = analyzer.get_position_info({})
            self.assertAlmostEqual(float(pos_qfq['current_price']), 1519.8)

    def test_windows_cp936_utf8_stdio_reconfigure_and_gbk_subprocess_decode(self):
        """回归测试：模拟 Windows cp936/gbk 控制台与 GBK 子进程字节流，验证零乱码且永不抛 UnicodeEncodeError。"""
        import app_paths
        import floe_app
        import api.stock_selection as sel_api
        import stocks_filter.batch_backtest_filter as bbf

        # 1. 模拟 Windows 中文控制台默认 cp936/gbk 管道流
        raw_out_buf = io.BytesIO()
        raw_err_buf = io.BytesIO()
        gbk_stdout = io.TextIOWrapper(raw_out_buf, encoding='gbk', errors='strict')
        gbk_stderr = io.TextIOWrapper(raw_err_buf, encoding='gbk', errors='strict')

        with mock.patch.object(sys, 'stdout', gbk_stdout), \
             mock.patch.object(sys, 'stderr', gbk_stderr):
            # 在未重配置前，写入 \ufffd / ⚠️ / → 在 gbk(strict) 下必然失败；
            # 调用 ensure_utf8_stdio / _ensure_valid_stdio 后必须自动转为 utf-8 + errors='replace'
            app_paths.ensure_utf8_stdio()
            floe_app._ensure_valid_stdio()

            self.assertEqual(sys.stdout.encoding.lower(), 'utf-8')
            self.assertEqual(sys.stderr.encoding.lower(), 'utf-8')
            sys.stdout.write('测试特殊字符：⚠️ → ✅ \ufffd\n')
            sys.stdout.flush()
            written = raw_out_buf.getvalue().decode('utf-8')
            self.assertIn('测试特殊字符：⚠️ → ✅', written)

        # 2. 模拟子进程意外吐出 GBK 编码中文字节流：decode_subprocess_bytes 与批筛/选股捕获均应无损还原
        gbk_msg = '交易日：20261120\n成功: 预检更新 000100.SZ 行情\n'.encode('gbk')
        decoded = app_paths.decode_subprocess_bytes(gbk_msg)
        self.assertNotIn('\ufffd', decoded)
        self.assertIn('交易日：20261120', decoded)

        with mock.patch.object(
            bbf.subprocess,
            'run',
            return_value=subprocess.CompletedProcess(['cmd'], 0, stdout=gbk_msg, stderr=b''),
        ):
            cap_buf = io.StringIO()
            with mock.patch.object(sys, 'stdout', cap_buf):
                rc = bbf.run_command_status(['fake_exe', '--run-script', 'data_collector.py'], '预检测试')
            self.assertEqual(rc, 0)
            out_log = cap_buf.getvalue()
            self.assertIn('交易日：20261120', out_log)
            self.assertNotIn('\ufffd', out_log)

        class _FakeProc:
            def __init__(self, payload):
                self.stdout = io.BytesIO(payload)
            def poll(self):
                return 0
            def wait(self):
                return 0

        sel_api.selection_tasks['gbk_decode_test'] = {'status': 'running', 'progress': 0, 'messages': []}
        with mock.patch.object(sel_api.subprocess, 'Popen', return_value=_FakeProc(gbk_msg)):
            rc2 = sel_api.run_command_with_output('gbk_decode_test', ['fake'], str(PROJECT_ROOT), '测试步骤')
        self.assertEqual(rc2, 0)
        joined = '\n'.join(sel_api.selection_tasks['gbk_decode_test']['messages'])
        self.assertIn('交易日：20261120', joined)
        self.assertNotIn('\ufffd', joined)


if __name__ == '__main__':
    unittest.main()
