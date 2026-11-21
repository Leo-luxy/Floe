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

        captured_tunnel = {}

        class _FakeOpener:
            def open(self, req_obj, timeout=None):
                captured_tunnel['host'] = req_obj.host
                captured_tunnel['tunnel'] = getattr(req_obj, '_tunnel_host', None)
                return _ProxyResp()

        net_guard.reconfigure_network_mode('direct')
        self.assertEqual(os.environ.get('no_proxy'), '*')

        req = urllib.request.Request('https://api.github.com/repos/Leo-luxy/Floe/releases/latest')
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError(TimeoutError('timed out'))), \
             mock.patch.object(net_guard, '_raw_system_proxy_dict', return_value={'https': 'http://127.0.0.1:10808'}), \
             mock.patch.object(net_guard, '_reachable', return_value=True), \
             mock.patch('urllib.request.build_opener', return_value=_FakeOpener()):
            with net_guard.urlopen_with_optional_proxy(req, timeout=3.0) as resp:
                payload = json.loads(resp.read().decode('utf-8'))

        self.assertEqual(payload['tag_name'], 'v2.0.1')
        self.assertEqual(captured_tunnel.get('host'), '127.0.0.1:10808')
        self.assertEqual(captured_tunnel.get('tunnel'), 'api.github.com')
        # 全局必须继续保持国内直连保护，不污染 A 股数据源采集
        self.assertEqual(os.environ.get('no_proxy'), '*')


if __name__ == '__main__':
    unittest.main()
