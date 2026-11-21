#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Floe 跨平台统一启动器（macOS / Windows / Linux）

支持四种运行模式：
1. 默认桌面窗口模式：floe（或双击 Floe.app / Floe.exe / Floe.AppImage）
   → 后台启动本地量化引擎服务 + 打开原生独立桌面窗口 + 挂载顶部菜单栏/系统托盘小企鹅图标
2. 浏览器/服务器模式：floe --web [--port 3130]
   → 启动本地服务并自动打开系统默认浏览器
3. 命令行自检与版本查询：floe --version | floe --doctor
4. 冻结态内部脚本执行器：floe --run-script <script.py> [args...]
   → 供 PyInstaller 打包环境下安全调度选股、回测、采集与 AI 分析子进程，绝不重复弹窗
"""

import os
import runpy
import socket
import subprocess
import sys
import threading
import time
import webbrowser

# 保持对原生菜单栏 / 系统托盘对象的强引用，防止被垃圾回收后图标消失
_STATUS_BAR_REFS = {}


def _ensure_valid_stdio():
    """Windows GUI 模式 (console=False) 下 sys.stdout/stderr 可能为 None，兜底重定向至日志文件防止 print 崩溃。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        import app_paths
        log_dir = os.path.join(app_paths.get_user_data_dir(), 'log')
        os.makedirs(log_dir, exist_ok=True)
        log_fp = open(os.path.join(log_dir, 'floe_gui.log'), 'a', encoding='utf-8', buffering=1)
        if sys.stdout is None:
            sys.stdout = log_fp
        if sys.stderr is None:
            sys.stderr = log_fp
    except Exception:
        devnull = open(os.devnull, 'w', encoding='utf-8')
        if sys.stdout is None:
            sys.stdout = devnull
        if sys.stderr is None:
            sys.stderr = devnull


def _dispatch_internal_script():
    """拦截 --run-script 子命令：在当前进程内直接执行指定业务脚本并以其退出码返回。"""
    if len(sys.argv) >= 3 and sys.argv[1] == '--run-script':
        import app_paths
        user_dir = app_paths.activate_runtime_paths()
        _ensure_valid_stdio()
        if app_paths.is_packaged_mode():
            try:
                os.chdir(user_dir)
            except OSError:
                pass
        target_script = app_paths.resolve_script_path(sys.argv[2])
        if not os.path.isfile(target_script):
            sys.stderr.write(f'[Floe] Script not found: {target_script}\n')
            sys.exit(2)
        script_dir = os.path.dirname(os.path.abspath(target_script))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        sys.argv = [target_script] + sys.argv[3:]
        runpy.run_path(target_script, run_name='__main__')
        sys.exit(0)


# 必须在导入重型 GUI / Flask 模块前优先拦截子脚本调用
_dispatch_internal_script()


def _wait_server_ready(host: str, port: int, timeout: float = 12.0) -> bool:
    """轮询等待本地 HTTP 服务端口进入监听就绪状态。"""
    probe_host = '127.0.0.1' if host in ('0.0.0.0', '') else host
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((probe_host, port)) == 0:
                return True
        time.sleep(0.08)
    return False


class FloeDesktopBridge:
    """暴露给 pywebview 前端 window.pywebview.api 的安全原生系统能力桥接。"""

    def open_external(self, url: str) -> bool:
        text = str(url or '').strip()
        if text.startswith(('http://', 'https://')):
            webbrowser.open(text)
            return True
        return False

    def open_data_dir(self) -> str:
        import app_paths
        target = app_paths.ensure_user_data_layout()
        if sys.platform == 'darwin':
            subprocess.Popen(['open', target])
        elif os.name == 'nt':
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(['xdg-open', target])
        return target

    def notify(self, title: str, message: str) -> bool:
        """发送操作系统级原生通知（macOS Notification Center / Linux notify-send）。"""
        clean_title = str(title or 'Floe').replace('"', "'")[:80]
        clean_msg = str(message or '').replace('"', "'")[:200]
        try:
            if sys.platform == 'darwin':
                apple_script = f'display notification "{clean_msg}" with title "{clean_title}"'
                subprocess.Popen(['osascript', '-e', apple_script],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if sys.platform.startswith('linux'):
                subprocess.Popen(['notify-send', clean_title, clean_msg],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
        except Exception:
            pass
        return False

    def set_app_icon(self, variant: str) -> bool:
        """在桌面运行时实时切换 macOS Dock 图标（bull: 红涨瞭望款 / bear: 绿跌闭眼款）。"""
        clean_var = 'bear' if str(variant or '').strip().lower() == 'bear' else 'bull'
        if sys.platform != 'darwin':
            return True
        try:
            import AppKit
            from PyObjCTools import AppHelper
            import app_paths

            bundle_dir = app_paths.get_bundle_dir()
            icns_file = os.path.join(bundle_dir, 'packaging', 'icons', f'floe_{clean_var}.icns')
            png_fallback = os.path.join(bundle_dir, 'static', 'icons', f'floe_icon_{clean_var}.png')
            chosen = icns_file if os.path.isfile(icns_file) else png_fallback
            if not os.path.isfile(chosen):
                return False

            def _apply_dock_icon():
                ns_img = AppKit.NSImage.alloc().initWithContentsOfFile_(chosen)
                if ns_img is not None:
                    AppKit.NSApplication.sharedApplication().setApplicationIconImage_(ns_img)

            AppHelper.callAfter(_apply_dock_icon)
            return True
        except Exception:
            return False


def _install_macos_menubar(window_obj, server_url: str, bridge: FloeDesktopBridge):
    """在 macOS 顶部系统菜单栏挂载黑白极简小企鹅 Template 图标与原生快捷菜单。"""
    if sys.platform != 'darwin':
        return
    try:
        import AppKit
        import Foundation
        from PyObjCTools import AppHelper
        import app_paths
        import user_settings as us
        import version

        bundle_dir = app_paths.get_bundle_dir()
        icon_2x = os.path.join(bundle_dir, 'packaging', 'icons', 'menubar_template@2x.png')
        icon_fallback = os.path.join(bundle_dir, 'static', 'icons', 'menubar_template.png')
        chosen_icon = icon_2x if os.path.isfile(icon_2x) else icon_fallback
        if not os.path.isfile(chosen_icon):
            return

        class _FloeMenuDelegate(Foundation.NSObject):
            def showMainWindow_(self, _sender):
                try:
                    app = AppKit.NSApplication.sharedApplication()
                    app.activateIgnoringOtherApps_(True)
                    for ns_win in app.windows():
                        if ns_win.isMiniaturized():
                            ns_win.deminiaturize_(None)
                        ns_win.makeKeyAndOrderFront_(None)
                    if window_obj is not None:
                        window_obj.show()
                        window_obj.restore()
                except Exception:
                    pass

            def openBrowser_(self, _sender):
                webbrowser.open(server_url)

            def openDataFolder_(self, _sender):
                bridge.open_data_dir()

            def quitFloe_(self, _sender):
                try:
                    if window_obj is not None:
                        window_obj.destroy()
                except Exception:
                    pass
                AppKit.NSApplication.sharedApplication().terminate_(None)

        def _mount_on_main_thread():
            is_en = (us.get_ui_language() == 'en-US')
            status_bar = AppKit.NSStatusBar.systemStatusBar()
            status_item = status_bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)

            ns_img = AppKit.NSImage.alloc().initWithContentsOfFile_(chosen_icon)
            if ns_img is not None:
                ns_img.setSize_(Foundation.NSMakeSize(18.0, 18.0))
                ns_img.setTemplate_(True)
                btn = status_item.button()
                if btn is not None:
                    btn.setImage_(ns_img)
                    btn.setToolTip_(f'{version.APP_NAME} v{version.APP_VERSION}')

            delegate = _FloeMenuDelegate.alloc().init()
            menu = AppKit.NSMenu.alloc().init()

            header_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f'{version.APP_NAME} v{version.APP_VERSION}', None, ''
            )
            header_item.setEnabled_(False)
            menu.addItem_(header_item)
            menu.addItem_(AppKit.NSMenuItem.separatorItem())

            show_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                'Show Floe Workbench' if is_en else '显示 Floe 主工作台',
                'showMainWindow:',
                '',
            )
            show_item.setTarget_(delegate)
            menu.addItem_(show_item)

            web_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                'Open in Web Browser' if is_en else '在浏览器中打开',
                'openBrowser:',
                '',
            )
            web_item.setTarget_(delegate)
            menu.addItem_(web_item)

            dir_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                'Open Data Directory' if is_en else '打开本地数据目录',
                'openDataFolder:',
                '',
            )
            dir_item.setTarget_(delegate)
            menu.addItem_(dir_item)

            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                'Quit Floe' if is_en else '退出 Floe',
                'quitFloe:',
                'q',
            )
            quit_item.setTarget_(delegate)
            menu.addItem_(quit_item)

            status_item.setMenu_(menu)
            _STATUS_BAR_REFS['item'] = status_item
            _STATUS_BAR_REFS['delegate'] = delegate
            _STATUS_BAR_REFS['menu'] = menu

        AppHelper.callAfter(_mount_on_main_thread)
    except Exception as exc:
        print(f'[Floe] Menu bar icon setup skipped: {exc}')


def _install_cross_platform_tray(window_obj, server_url: str, bridge: FloeDesktopBridge):
    """在 Windows / Linux 上挂载系统托盘黑白小企鹅图标（若已安装 pystray）。"""
    if sys.platform == 'darwin':
        return
    try:
        import pystray
        from PIL import Image
        import app_paths
        import user_settings as us

        tray_png = os.path.join(app_paths.get_bundle_dir(), 'packaging', 'icons', 'tray_icon_white.png')
        if not os.path.isfile(tray_png):
            return
        img = Image.open(tray_png)
        is_en = (us.get_ui_language() == 'en-US')

        def _on_show(icon, item):
            try:
                if window_obj is not None:
                    window_obj.show()
                    window_obj.restore()
            except Exception:
                pass

        def _on_web(icon, item):
            webbrowser.open(server_url)

        def _on_dir(icon, item):
            bridge.open_data_dir()

        def _on_quit(icon, item):
            icon.stop()
            try:
                if window_obj is not None:
                    window_obj.destroy()
            except Exception:
                pass
            os._exit(0)

        tray = pystray.Icon(
            'floe',
            img,
            'Floe',
            menu=pystray.Menu(
                pystray.MenuItem('Show Floe Workbench' if is_en else '显示 Floe 主工作台', _on_show, default=True),
                pystray.MenuItem('Open in Browser' if is_en else '在浏览器中打开', _on_web),
                pystray.MenuItem('Open Data Directory' if is_en else '打开本地数据目录', _on_dir),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('Quit Floe' if is_en else '退出 Floe', _on_quit),
            ),
        )
        threading.Thread(target=tray.run, daemon=True, name='FloeSystemTray').start()
        _STATUS_BAR_REFS['tray'] = tray
    except Exception:
        pass


def _run_doctor() -> int:
    import app_paths
    app_paths.activate_runtime_paths()
    import net_guard
    import tushare_client
    import user_settings as us
    import version

    print(f'{version.APP_NAME} v{version.APP_VERSION} Environment Doctor')
    print('-' * 56)
    print(f'Platform       : {sys.platform} ({os.name})')
    print(f'Python         : {sys.version.split()[0]} ({sys.executable})')
    print(f'Packaged Mode  : {app_paths.is_packaged_mode()} (frozen={app_paths.is_frozen()}, fallback={app_paths.is_using_fallback_data_dir()})')
    print(f'Bundle Root    : {app_paths.get_bundle_dir()}')
    print(f'User Data Dir  : {app_paths.get_user_data_dir()}')
    net = net_guard.status()
    print(f'Network Guard  : {net.get("detail")}')
    try:
        tokens = tushare_client.resolve_tokens()
        print(f'Tushare Tokens : Ready ({len(tokens)} configured)')
    except Exception:
        print('Tushare Tokens : Not configured yet (set in Settings UI)')
    saved_ai = (us.load_user_settings().get('ai') or {})
    print(f'AI Provider    : {saved_ai.get("provider", "not set")}')
    print('-' * 56)
    return 0


def main():
    args = sys.argv[1:]
    if '--version' in args or '-v' in args:
        _ensure_valid_stdio()
        import version
        print(f'{version.APP_NAME} v{version.APP_VERSION}')
        return 0

    # 独立软件启动默认开启用户数据目录隔离（传 --dev 时保持开发仓库内读写）
    if '--dev' not in args and 'FLOE_PACKAGED' not in os.environ:
        os.environ['FLOE_PACKAGED'] = '1'

    for idx, arg in enumerate(args):
        if arg == '--port' and idx + 1 < len(args):
            os.environ['GP_ANA_WEB_PORT'] = args[idx + 1]

    # 先完成可写用户目录解析与便携回退，再挂载 GUI 日志与工作目录，防止 AppData 受阻崩溃
    import app_paths
    user_dir = app_paths.activate_runtime_paths()
    _ensure_valid_stdio()

    if '--doctor' in args:
        return _run_doctor()

    if app_paths.is_packaged_mode():
        try:
            os.chdir(user_dir)
        except OSError:
            pass

    import user_settings as us
    import version
    import web_ui

    host, preferred_port, debug = web_ui.get_run_config()
    port = web_ui.pick_available_port(host, preferred_port)
    if port != preferred_port:
        print(f'⚠️  默认端口 {preferred_port} 已被占用，已自动切换至空闲端口：{port}')

    url = f'http://127.0.0.1:{port}'
    force_web = ('--web' in args or '--no-gui' in args or os.environ.get('FLOE_WEB_ONLY') == '1')

    # 若非强制浏览器模式，尝试加载原生桌面窗口引擎 pywebview
    webview_mod = None
    if not force_web:
        try:
            import webview as _wv
            webview_mod = _wv
        except Exception as exc:
            print(f'提示：未检测到桌面窗口组件 ({exc})，自动切换为浏览器模式启动。')

    if webview_mod is None:
        print(f'🐧 {version.APP_NAME} v{version.APP_VERSION} 已启动：{url}')
        if '--no-browser' not in args:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        web_ui.app.run(host=host, port=port, debug=debug, use_reloader=False)
        return 0

    # 桌面原生窗口模式：后台守护线程运行 Flask，主线程驱动原生 WebView 与菜单栏小企鹅图标
    server_thread = threading.Thread(
        target=lambda: web_ui.app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True),
        daemon=True,
        name='FloeFlaskServer',
    )
    server_thread.start()
    _wait_server_ready('127.0.0.1', port, timeout=12.0)

    win_title = (version.APP_DISPLAY_EN if us.get_ui_language() == 'en-US' else version.APP_DISPLAY_ZH)
    bridge = FloeDesktopBridge()
    win = webview_mod.create_window(
        title=win_title,
        url=url,
        js_api=bridge,
        width=1420,
        height=900,
        min_size=(1024, 680),
        text_select=True,
    )

    def _on_gui_ready():
        saved_ui = (us.load_user_settings().get('ui') or {})
        init_icon = 'bear' if saved_ui.get('icon_variant') == 'bear' else 'bull'
        bridge.set_app_icon(init_icon)
        _install_macos_menubar(win, url, bridge)
        _install_cross_platform_tray(win, url, bridge)

    icon_png = os.path.join(app_paths.get_bundle_dir(), 'static', 'icons', 'floe_icon.png')
    start_kwargs = {'func': _on_gui_ready}
    if sys.platform.startswith('linux') and os.path.isfile(icon_png):
        start_kwargs['icon'] = icon_png
    if app_paths.is_packaged_mode():
        try:
            import inspect
            wv_params = inspect.signature(webview_mod.start).parameters
            if 'storage_path' in wv_params and 'private_mode' in wv_params:
                wv_storage = os.path.join(user_dir, '.cache', 'webview_storage')
                os.makedirs(wv_storage, exist_ok=True)
                start_kwargs['storage_path'] = wv_storage
                start_kwargs['private_mode'] = False
        except Exception:
            pass
    webview_mod.start(**start_kwargs)
    return 0


if __name__ == '__main__':
    sys.exit(main())
