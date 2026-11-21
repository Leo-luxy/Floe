# app_paths.py
# 跨平台路径隔离与打包冻结态（PyInstaller）子进程调度兼容层
#
# 设计原则：
# 1. 源码开发模式（默认在仓库内直接 python web_ui.py，未冻结且未设 FLOE_PACKAGED=1）：
#    BUNDLE_DIR == USER_DATA_DIR == 仓库根目录，100% 兼容原有脚本与全部回归单测。
# 2. 桌面软件/命令行打包发布模式（sys.frozen 为真，或设置了 FLOE_PACKAGED=1 / FLOE_USER_DATA_DIR）：
#    - BUNDLE_DIR 指向只读代码与模板资源包目录；
#    - USER_DATA_DIR 优先指向操作系统标准用户应用数据目录：
#        * macOS:   ~/Library/Application Support/Floe
#        * Windows: %APPDATA%\Floe
#        * Linux:   ~/.local/share/floe
#    - 权限自适应便携回退（Windows 受控文件夹访问 / 杀毒管家拦截 AppData 写权限时）：
#      若默认系统目录抛出 PermissionError ([WinError 5] 拒绝访问) 或只读不可写，自动顺延尝试
#      %LOCALAPPDATA%\Floe 及可执行程序同级目录 Floe_Data（便携绿色模式），并同步收拢不可写的
#      TEMP / MPLCONFIGDIR / WEBVIEW2_USER_DATA_FOLDER，确保零配置免管理员稳定启动。

import os
import shlex
import sys
import tempfile
import uuid

_PACKAGED_DIR_CACHE = {
    'key': None,
    'path': None,
    'fallback': False,
}


def reset_path_cache() -> None:
    """清空已解析的用户数据目录缓存（供单元测试动态切换环境时调用）。"""
    _PACKAGED_DIR_CACHE['key'] = None
    _PACKAGED_DIR_CACHE['path'] = None
    _PACKAGED_DIR_CACHE['fallback'] = False


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


def _get_executable_host_dir() -> str:
    """获取可执行程序所在的宿主目录（用于绿色便携包在同级目录创建 Floe_Data）。"""
    appimage = os.environ.get('APPIMAGE', '').strip()
    if appimage:
        return os.path.dirname(os.path.abspath(appimage))
    if is_frozen() and sys.executable:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        # macOS .app 包内二进制位于 Floe.app/Contents/MacOS，内部不应作为便携数据目录
        if sys.platform == 'darwin' and '.app/Contents/' in exe_dir.replace('\\', '/'):
            return ''
        return exe_dir
    return get_bundle_dir()


def _default_os_user_data_dir(app_name: str = 'Floe') -> str:
    """返回符合各操作系统规范的首选应用数据存储目录。"""
    if sys.platform == 'darwin':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', app_name)
    if os.name == 'nt':
        appdata = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
        return os.path.join(appdata, app_name)
    xdg_data = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(xdg_data, app_name.lower())


def _candidate_user_data_dirs(app_name: str = 'Floe') -> list:
    """生成按优先级排列的用户数据目录候选列表（首选标准目录，受阻时回退便携/本地目录）。"""
    primary = _default_os_user_data_dir(app_name)
    exe_host = _get_executable_host_dir()
    home_dir = os.path.expanduser('~')
    raw = []

    if os.name == 'nt':
        local_appdata = os.environ.get('LOCALAPPDATA') or os.path.join(home_dir, 'AppData', 'Local')
        local_dir = os.path.join(local_appdata, app_name)
        portable_dir = os.path.join(exe_host, f'{app_name}_Data') if exe_host else ''

        # 便携连续性保护：若同级目录存在 .portable 标记，或此前已因回退在 Floe_Data 保存过配置
        # （而标准目录无配置），后续启动继续优先使用 Floe_Data，防止用户配置“消失”
        prefer_portable = False
        if portable_dir and exe_host:
            if os.path.exists(os.path.join(exe_host, '.portable')) or os.path.exists(os.path.join(portable_dir, '.portable')):
                prefer_portable = True
            elif (os.path.isfile(os.path.join(portable_dir, 'user_settings.json'))
                  and not os.path.isfile(os.path.join(primary, 'user_settings.json'))):
                prefer_portable = True

        if prefer_portable and portable_dir:
            raw.append(portable_dir)
        raw.extend([primary, local_dir])
        if portable_dir:
            raw.append(portable_dir)
        raw.append(os.path.join(os.path.abspath(os.getcwd()), f'{app_name}_Data'))
        raw.append(os.path.join(home_dir, f'{app_name}_Data'))
    elif sys.platform == 'darwin':
        raw.extend([
            primary,
            os.path.join(home_dir, 'Library', 'Caches', f'{app_name}_Data'),
            os.path.join(home_dir, f'{app_name}_Data'),
        ])
        if exe_host:
            raw.append(os.path.join(exe_host, f'{app_name}_Data'))
    else:
        portable_lin = os.path.join(exe_host, f'{app_name.lower()}_data') if exe_host else ''
        if portable_lin and os.path.isfile(os.path.join(portable_lin, 'user_settings.json')) and not os.path.isfile(os.path.join(primary, 'user_settings.json')):
            raw.append(portable_lin)
        raw.append(primary)
        if portable_lin:
            raw.append(portable_lin)
        raw.extend([
            os.path.join(home_dir, '.cache', f'{app_name.lower()}_data'),
            os.path.join(home_dir, f'{app_name.lower()}_data'),
        ])

    # 去重并保持顺序
    deduped = []
    seen = set()
    for item in raw:
        if not item:
            continue
        norm = os.path.abspath(item)
        key = norm.lower() if os.name == 'nt' else norm
        if key not in seen:
            seen.add(key)
            deduped.append(norm)
    return deduped


def _probe_dir_writable(dir_path: str) -> bool:
    """实测目标目录是否可创建且具备真实文件写入与删除权限（拦截只读目录与受控文件夹拒绝访问）。"""
    if not dir_path:
        return False
    probe_file = os.path.join(dir_path, f'.floe_probe_{os.getpid()}_{uuid.uuid4().hex[:8]}')
    try:
        os.makedirs(dir_path, exist_ok=True)
        with open(probe_file, 'w', encoding='utf-8') as fh:
            fh.write('ok')
        os.remove(probe_file)
        return True
    except OSError:
        try:
            if os.path.exists(probe_file):
                os.remove(probe_file)
        except OSError:
            pass
        return False


def _init_user_data_structure(base: str) -> str:
    """在指定目录内创建完整子目录与默认配置文件（失败时直接抛出 OSError 供上层捕获回退）。"""
    for sub in ('data', 'stocks_filter', 'backup', 'log'):
        os.makedirs(os.path.join(base, sub), exist_ok=True)

    probe_file = os.path.join(base, f'.floe_probe_{os.getpid()}_{uuid.uuid4().hex[:8]}')
    with open(probe_file, 'w', encoding='utf-8') as fh:
        fh.write('ok')
    os.remove(probe_file)

    wl_path = os.path.join(base, 'watchlist.py')
    if not os.path.exists(wl_path):
        with open(wl_path, 'w', encoding='utf-8') as fh:
            fh.write('# 关注的股票列表\nWATCHLIST = [\n]\n')

    tr_path = os.path.join(base, 'trading_records.py')
    if not os.path.exists(tr_path):
        with open(tr_path, 'w', encoding='utf-8') as fh:
            fh.write('# trading_records.py\n# 交易记录配置\n\nTRADING_RECORDS = {\n}\n')

    return base


def _resolve_packaged_user_data_dir(app_name: str = 'Floe') -> str:
    """解析并验证可写的打包态用户数据目录；若标准目录被安全软件拦截则自动降级至便携目录。"""
    cache_key = (
        sys.platform,
        os.name,
        is_frozen(),
        os.path.abspath(sys.executable or ''),
        os.environ.get('APPDATA', ''),
        os.environ.get('LOCALAPPDATA', ''),
        os.environ.get('XDG_DATA_HOME', ''),
        os.environ.get('APPIMAGE', ''),
    )
    cached_path = _PACKAGED_DIR_CACHE.get('path')
    if _PACKAGED_DIR_CACHE.get('key') == cache_key and cached_path and os.path.isdir(cached_path):
        return cached_path

    primary_norm = os.path.abspath(_default_os_user_data_dir(app_name))
    candidates = _candidate_user_data_dirs(app_name)
    for cand in candidates:
        try:
            _init_user_data_structure(cand)
            is_fb = (cand.lower() != primary_norm.lower()) if os.name == 'nt' else (cand != primary_norm)
            _PACKAGED_DIR_CACHE['key'] = cache_key
            _PACKAGED_DIR_CACHE['path'] = cand
            _PACKAGED_DIR_CACHE['fallback'] = is_fb
            return cand
        except OSError:
            continue

    # 极端兜底：所有常规目录均受限时，尝试系统临时目录
    last_resort = os.path.abspath(os.path.join(tempfile.gettempdir(), f'{app_name}_Data'))
    try:
        _init_user_data_structure(last_resort)
        _PACKAGED_DIR_CACHE['key'] = cache_key
        _PACKAGED_DIR_CACHE['path'] = last_resort
        _PACKAGED_DIR_CACHE['fallback'] = True
        return last_resort
    except OSError:
        return primary_norm


def is_using_fallback_data_dir() -> bool:
    """判断当前是否因默认系统目录无写权限而自动切换到了便携回退目录。"""
    if not is_packaged_mode():
        return False
    current = os.path.abspath(get_user_data_dir())
    primary = os.path.abspath(_default_os_user_data_dir('Floe'))
    if os.name == 'nt':
        return current.lower() != primary.lower()
    return current != primary


def get_user_data_dir() -> str:
    """获取用户可变数据根目录（配置、自选股、交易台账、行情与选股结果）。"""
    override = os.environ.get('FLOE_USER_DATA_DIR', '').strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if is_packaged_mode():
        return _resolve_packaged_user_data_dir('Floe')
    return get_bundle_dir()


def ensure_user_data_layout(user_dir: str = None) -> str:
    """确保用户数据目录下的子目录与基础配置文件存在（幂等安全，支持受阻自动回退）。"""
    explicit_arg = bool(user_dir)
    base = os.path.abspath(os.path.expanduser(user_dir)) if explicit_arg else get_user_data_dir()
    try:
        return _init_user_data_structure(base)
    except OSError:
        # 若显式传入路径在非打包测试中报错，保持原样抛出；打包运行时自动寻找可写回退目录避免崩溃
        if explicit_arg and not is_packaged_mode():
            raise
        reset_path_cache()
        for cand in _candidate_user_data_dirs('Floe'):
            try:
                _init_user_data_structure(cand)
                os.environ['FLOE_USER_DATA_DIR'] = cand
                return cand
            except OSError:
                continue
        raise


def _ensure_writable_runtime_caches(user_dir: str) -> None:
    """在打包模式下自检系统临时目录、Matplotlib 缓存与 Windows WebView2 目录，受阻时收拢至 user_dir。"""
    # 1. 若系统 TEMP / TMP 被安全软件拦截（如 C:\Users\xxx\AppData\Local\Temp 报 WinError 5），
    #    重定向至 <user_dir>/tmp，防止 Python 退回程序目录生成 tmpXXXXXX 散落文件夹或子库崩溃
    env_tmp = (os.environ.get('TMPDIR') or os.environ.get('TEMP') or os.environ.get('TMP') or '').strip()
    if not env_tmp or not _probe_dir_writable(env_tmp):
        safe_tmp = os.path.join(user_dir, 'tmp')
        try:
            os.makedirs(safe_tmp, exist_ok=True)
            os.environ['TEMP'] = safe_tmp
            os.environ['TMP'] = safe_tmp
            os.environ['TMPDIR'] = safe_tmp
            tempfile.tempdir = safe_tmp
        except OSError:
            pass

    # 2. 若启用了便携回退或默认 ~/.matplotlib 不可写，将 Matplotlib 字体缓存收拢至 user_dir
    if not os.environ.get('MPLCONFIGDIR', '').strip():
        default_mpl = os.path.join(os.path.expanduser('~'), '.matplotlib')
        if is_using_fallback_data_dir() or not _probe_dir_writable(default_mpl):
            mpl_cache = os.path.join(user_dir, '.cache', 'matplotlib')
            try:
                os.makedirs(mpl_cache, exist_ok=True)
                os.environ['MPLCONFIGDIR'] = mpl_cache
            except OSError:
                pass

    # 3. Windows Edge WebView2 默认写 %APPDATA%，收拢至已确认可写的 user_dir 避免白屏或 0x80070005 拒绝访问
    if os.name == 'nt' and not os.environ.get('WEBVIEW2_USER_DATA_FOLDER', '').strip():
        wv2_dir = os.path.join(user_dir, '.cache', 'webview2')
        try:
            os.makedirs(wv2_dir, exist_ok=True)
            os.environ['WEBVIEW2_USER_DATA_FOLDER'] = wv2_dir
        except OSError:
            pass


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

    if is_packaged_mode():
        user_dir = ensure_user_data_layout()
        os.environ['FLOE_USER_DATA_DIR'] = user_dir
        _ensure_writable_runtime_caches(user_dir)
        if bundle_dir not in sys.path:
            sys.path.insert(0, bundle_dir)
        if sys.path[0] != user_dir:
            if user_dir in sys.path:
                sys.path.remove(user_dir)
            sys.path.insert(0, user_dir)
        # 若 user_settings 已提前导入且未被单测打桩覆盖，同步刷新其默认配置文件路径
        us_mod = sys.modules.get('user_settings')
        if us_mod is not None and getattr(us_mod, 'SETTINGS_FILE', None) == getattr(us_mod, '_INITIAL_SETTINGS_FILE', None):
            new_sf = get_settings_file()
            us_mod.SETTINGS_FILE = new_sf
            us_mod._INITIAL_SETTINGS_FILE = new_sf
    else:
        user_dir = get_bundle_dir()
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
        if not text or any(ch in text for ch in ' \t"&()[]{}^=;!+,`~'):
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
    env.setdefault('PYTHONUTF8', '1')
    if is_packaged_mode():
        user_dir = get_user_data_dir()
        bundle_dir = get_bundle_dir()
        env['FLOE_USER_DATA_DIR'] = user_dir
        existing_pp = env.get('PYTHONPATH', '')
        parts = [user_dir, bundle_dir] + ([existing_pp] if existing_pp else [])
        env['PYTHONPATH'] = os.pathsep.join(parts)
    return env
