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
        launcher = str(PROJECT_ROOT / 'floe_app.py')
        ver_proc = subprocess.run([sys.executable, launcher, '--version'], capture_output=True, text=True)
        self.assertEqual(ver_proc.returncode, 0)
        self.assertIn('Floe v2.0.0', ver_proc.stdout)

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


if __name__ == '__main__':
    unittest.main()
