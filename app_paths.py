# app_paths.py
# 跨平台路径隔离与打包冻结态（PyInstaller）子进程调度兼容层
#
# 设计原则：
# 1. 源码开发模式（默认在仓库内直接 python web_ui.py，未冻结且未设 FLOE_PACKAGED=1）：
#    BUNDLE_DIR == USER_DATA_DIR == 仓库根目录，100% 兼容原有脚本与全部回归单测。
# 2. 桌面软件/命令行打包发布模式（sys.frozen 为真，或设置了 FLOE_PACKAGED=1 / FLOE_USER_DATA_DIR）：
#    - BUNDLE_DIR 指向只读代码与模板资源包目录；
#    - USER_DATA_DIR 指向操作系统标准用户应用数据目录：
#        * macOS:   ~/Library/Application Support/Floe
#        * Windows: %APPDATA%\Floe
#        * Linux:   ~/.local/share/floe
#    软件升级替换安装包时，用户的自选股、交易台账、API 密钥与行情缓存永久保留不丢失。

import os
import shlex
import sys


def is_frozen() -> bool:
    """判断当前是否运行在 PyInstaller 等冻结二进制环境中。"""
    return bool(getattr(sys, 'frozen', False))


def is_packaged_mode() -> bool:
    """判断是否启用用户数据目录与代码目录分离模式。"""
    if is_frozen():
        return True
    if os.environ.get('FLOE_USER_DATA_DIR', '').strip():
        return True
    return str(os.environ.get('FLOE_PACKAGED', '')).strip().lower() in ('1', 'true', 'yes', 'on')


def get_bundle_dir() -> str:
    """获取只读程序代码与静态模板所在根目录。"""
    if is_frozen():
        return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))


def _default_os_user_data_dir(app_name: str = 'Floe') -> str:
    """返回符合各操作系统规范的应用数据存储目录。"""
    if sys.platform == 'darwin':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', app_name)
    if os.name == 'nt':
        appdata = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
        return os.path.join(appdata, app_name)
    xdg_data = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(xdg_data, app_name.lower())


def get_user_data_dir() -> str:
    """获取用户可变数据根目录（配置、自选股、交易台账、行情与选股结果）。"""
    override = os.environ.get('FLOE_USER_DATA_DIR', '').strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if is_packaged_mode():
        return _default_os_user_data_dir('Floe')
    return get_bundle_dir()


def ensure_user_data_layout(user_dir: str = None) -> str:
    """确保用户数据目录下的子目录与基础配置文件存在（幂等安全）。"""
    base = user_dir or get_user_data_dir()
    for sub in ('data', 'stocks_filter', 'backup', 'log'):
        os.makedirs(os.path.join(base, sub), exist_ok=True)

    wl_path = os.path.join(base, 'watchlist.py')
    if not os.path.exists(wl_path):
        with open(wl_path, 'w', encoding='utf-8') as fh:
            fh.write('# 关注的股票列表\nWATCHLIST = [\n]\n')

    tr_path = os.path.join(base, 'trading_records.py')
    if not os.path.exists(tr_path):
        with open(tr_path, 'w', encoding='utf-8') as fh:
            fh.write('# trading_records.py\n# 交易记录配置\n\nTRADING_RECORDS = {\n}\n')

    return base


def activate_runtime_paths() -> str:
    """在打包模式下初始化用户目录并挂载至 sys.path 首位；源码首次克隆若缺 config.py 自动用模板初始化。"""
    import shutil
    bundle_dir = get_bundle_dir()
    cfg_py = os.path.join(bundle_dir, 'config.py')
    cfg_ex = os.path.join(bundle_dir, 'config.example.py')
    if not is_frozen() and not os.path.exists(cfg_py) and os.path.isfile(cfg_ex):
        try:
            shutil.copyfile(cfg_ex, cfg_py)
        except OSError:
            pass
    user_dir = get_user_data_dir()
    if is_packaged_mode():
        ensure_user_data_layout(user_dir)
        os.environ['FLOE_USER_DATA_DIR'] = user_dir
        if bundle_dir not in sys.path:
            sys.path.insert(0, bundle_dir)
        if sys.path[0] != user_dir:
            if user_dir in sys.path:
                sys.path.remove(user_dir)
            sys.path.insert(0, user_dir)
    else:
        if bundle_dir not in sys.path:
            sys.path.insert(0, bundle_dir)
    return user_dir


def get_data_dir() -> str:
    return os.path.join(get_user_data_dir(), 'data')


def get_selection_dir() -> str:
    return os.path.join(get_user_data_dir(), 'stocks_filter')


def get_settings_file() -> str:
    return os.path.join(get_user_data_dir(), 'user_settings.json')


def get_watchlist_file() -> str:
    return os.path.join(get_user_data_dir(), 'watchlist.py')


def get_trading_records_file() -> str:
    return os.path.join(get_user_data_dir(), 'trading_records.py')


def get_task_cache_file() -> str:
    return os.path.join(get_user_data_dir(), '.task_status_cache.json')


def resolve_script_path(rel_or_abs_script: str) -> str:
    """将项目内脚本相对路径解析为代码包内的真实绝对路径。"""
    if os.path.isabs(rel_or_abs_script) and os.path.exists(rel_or_abs_script):
        return rel_or_abs_script
    candidate = os.path.join(get_bundle_dir(), rel_or_abs_script)
    if os.path.exists(candidate):
        return candidate
    # 例如传入 stocks_filter/step1_daily.py 但被拼接在了 user_data_dir 下时自动纠偏回 bundle_dir
    user_dir = get_user_data_dir()
    if rel_or_abs_script.startswith(user_dir):
        rel = os.path.relpath(rel_or_abs_script, user_dir)
        alt = os.path.join(get_bundle_dir(), rel)
        if os.path.exists(alt):
            return alt
    return candidate


def _quote_arg(arg: str) -> str:
    if os.name == 'nt':
        text = str(arg)
        if not text or any(ch in text for ch in ' \t"'):
            return '"' + text.replace('"', '\\"') + '"'
        return text
    return shlex.quote(str(arg))


def python_exec_cmd_prefix() -> str:
    """返回 shell 命令中用于启动项目内 Python 脚本的前缀（冻结态自动带 --run-script）。"""
    exe_q = _quote_arg(sys.executable or 'python')
    if is_frozen():
        return f'{exe_q} --run-script'
    return exe_q


def python_script_argv(script_path: str, *extra_args) -> list:
    """构造 subprocess 列表调用参数（兼容源码态与 PyInstaller 冻结态）。"""
    real_script = resolve_script_path(script_path)
    if is_frozen():
        return [sys.executable, '--run-script', real_script, *[str(a) for a in extra_args]]
    return [sys.executable, real_script, *[str(a) for a in extra_args]]


def rewrite_shell_python_cmd(command: str) -> str:
    """将形如 'python xxx.py --ticker ...' 的 shell 命令重写为当前运行态安全命令。"""
    text = str(command or '').strip()
    if not text.startswith('python '):
        return text
    rest = text[len('python '):].strip()
    if not rest:
        return text
    parts = rest.split(None, 1)
    script_token = parts[0].strip('"\'')
    tail = (' ' + parts[1]) if len(parts) > 1 else ''
    real_script = resolve_script_path(script_token)
    exe_q = _quote_arg(sys.executable)
    scr_q = _quote_arg(real_script)
    if is_frozen():
        return f'{exe_q} --run-script {scr_q}{tail}'
    return f'{exe_q} {scr_q}{tail}'


def subprocess_env() -> dict:
    """生成传递给子进程的环境变量字典，确保子进程继承用户数据目录与 UTF-8 编码。"""
    env = os.environ.copy()
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    if is_packaged_mode():
        env['FLOE_USER_DATA_DIR'] = get_user_data_dir()
        bundle_dir = get_bundle_dir()
        user_dir = get_user_data_dir()
        existing_pp = env.get('PYTHONPATH', '')
        parts = [user_dir, bundle_dir] + ([existing_pp] if existing_pp else [])
        env['PYTHONPATH'] = os.pathsep.join(parts)
    return env
