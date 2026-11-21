import ast
from datetime import datetime
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
import zipfile

from flask import Blueprint, jsonify, request, send_file

import app_paths
import config
import net_guard
import tushare_client
import user_settings as us
import version

settings_bp = Blueprint('settings', __name__)


def detect_install_channel() -> str:
    """识别当前 Floe 实例的安装分发渠道（homebrew / npm / app_bundle / source）。"""
    explicit = os.environ.get('FLOE_INSTALL_CHANNEL', '').strip().lower()
    if explicit in ('homebrew', 'npm', 'app_bundle', 'source'):
        return explicit
    exe_lower = os.path.abspath(sys.executable).lower()
    if 'homebrew' in exe_lower or 'cellar' in exe_lower or 'caskroom' in exe_lower:
        return 'homebrew'
    if 'node_modules' in exe_lower or os.environ.get('FLOE_NPM_WRAPPER') == '1':
        return 'npm'
    if app_paths.is_frozen():
        return 'app_bundle'
    return 'source'


def _parse_semver(ver_str: str) -> tuple:
    """解析形如 'v2.0.0' 或 '1.6.0' 的版本号用于大小比较。"""
    cleaned = str(ver_str or '').strip().lstrip('vV')
    nums = [int(x) for x in re.findall(r'\d+', cleaned)[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _match_platform_asset(assets: list) -> dict:
    """从 GitHub Release assets 中挑选最匹配当前操作系统与 CPU 架构的安装包。"""
    sys_plat = sys.platform
    mach = platform.machine().lower()
    is_arm = mach in ('arm64', 'aarch64')

    scored = []
    for item in (assets or []):
        name = str(item.get('name') or '')
        low = name.lower()
        url = str(item.get('browser_download_url') or '')
        if not name or not url or low.endswith(('.txt', '.sha256', '.sig', '.blockmap')):
            continue
        score = 0
        if sys_plat == 'darwin':
            if any(k in low for k in ('macos', 'darwin', 'mac', 'osx')) or low.endswith('.dmg'):
                score += 10
                if low.endswith('.dmg'):
                    score += 5
                if is_arm and any(k in low for k in ('arm64', 'aarch64', 'apple')):
                    score += 8
                elif (not is_arm) and any(k in low for k in ('x64', 'x86_64', 'intel', 'universal')):
                    score += 8
        elif os.name == 'nt':
            if any(k in low for k in ('win', 'windows')) or low.endswith(('.exe', '.msi')):
                score += 10
                if low.endswith('.exe'):
                    score += 5
        else:
            if 'linux' in low or low.endswith(('.appimage', '.deb', '.tar.gz')):
                score += 10
                if low.endswith('.appimage'):
                    score += 5
        if score > 0:
            scored.append((score, {
                'name': name,
                'url': url,
                'size_mb': round(int(item.get('size') or 0) / (1024 * 1024), 1),
            }))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1] if scored else None


def _validate_python_literal_assignment(source_text: str, expected_var: str, expected_type):
    """使用 AST 严格校验导入的 .py 备份文件只包含单个纯字面量赋值，杜绝任意代码执行。"""
    tree = ast.parse(source_text, mode='exec')
    found = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id != expected_var:
                raise ValueError(f'不允许的变量名：{node.targets[0].id}')
            val = ast.literal_eval(node.value)
            if not isinstance(val, expected_type):
                raise ValueError(f'{expected_var} 类型不合法')
            found = True
        else:
            raise ValueError('备份文件包含非纯数据语句，已拦截导入')
    if not found:
        raise ValueError(f'备份文件缺少 {expected_var} 定义')


@settings_bp.route('/settings/status', methods=['GET'])
def get_settings_status():
    """检测本机 AI、Tushare、界面语言、网络模式与应用版本就绪状态。"""
    saved = us.load_user_settings()
    saved_ai = saved.get('ai') if isinstance(saved.get('ai'), dict) else {}
    saved_ts = saved.get('tushare') if isinstance(saved.get('tushare'), dict) else {}
    saved_ui = saved.get('ui') if isinstance(saved.get('ui'), dict) else {}

    ollama_url = str(saved_ai.get('ollama_base_url') or config.AI_CONFIG.get('ollama_base_url')
                     or config.AI_CONFIG.get('base_url') or 'http://localhost:11434').strip()
    ollama_model = str(saved_ai.get('ollama_model') or config.AI_CONFIG.get('ollama_model')
                       or 'qwen3.6:35b-a3b-mlx-bf16').strip()
    api_base = str(saved_ai.get('api_base') or config.AI_CONFIG.get('api_base')
                   or us.DEFAULT_API_BASE).strip()
    api_model = str(saved_ai.get('api_model') or config.AI_CONFIG.get('api_model')
                    or us.DEFAULT_API_MODEL).strip()
    api_key = str(saved_ai.get('api_key') or config.AI_CONFIG.get('api_key') or '').strip()
    api_configured = bool(api_key)

    ollama_online, ollama_models, _ = us.probe_ollama(ollama_url, timeout=0.6)

    explicit_provider = saved_ai.get('provider')
    if explicit_provider in ('api', 'ollama'):
        active_provider = explicit_provider
        ui_recommended_provider = explicit_provider
    else:
        active_provider = 'ollama' if ollama_online else ('api' if api_configured else 'ollama')
        ui_recommended_provider = 'ollama' if ollama_online else 'api'

    ai_ready = ((active_provider == 'api' and api_configured)
                or (active_provider == 'ollama' and ollama_online))

    try:
        tokens = tushare_client.resolve_tokens()
    except RuntimeError:
        tokens = []
    tushare_ready = len(tokens) > 0
    primary_masked = us.mask_secret(tokens[0]) if tokens else ''
    backup_masked = [us.mask_secret(t) for t in tokens[1:]]

    missing_items = []
    if not ai_ready:
        missing_items.append('AI模型/API')
    if not tushare_ready:
        missing_items.append('Tushare')

    return jsonify({
        'success': True,
        'ai_ready': ai_ready,
        'tushare_ready': tushare_ready,
        'needs_setup': (not ai_ready) or (not tushare_ready),
        'missing_items': missing_items,
        'app': {
            'name': version.APP_NAME,
            'version': version.APP_VERSION,
            'slogan_zh': version.APP_SLOGAN_ZH,
            'slogan_en': version.APP_SLOGAN_EN,
            'email': version.AUTHOR_EMAIL,
            'changelog_zh': version.RELEASE_CHANGELOG_ZH,
            'changelog_en': version.RELEASE_CHANGELOG_EN,
            'channel': detect_install_channel(),
            'platform': sys.platform,
            'arch': platform.machine(),
            'packaged': app_paths.is_packaged_mode(),
            'user_data_dir': app_paths.get_user_data_dir(),
            'repo_url': version.GITHUB_REPO_URL,
            'releases_url': version.GITHUB_RELEASES_PAGE,
        },
        'preferences': {
            'language': us.get_ui_language(),
            'icon_variant': ('bear' if str(saved_ui.get('icon_variant') or '').strip() == 'bear' else 'bull'),
            'network_mode': us.get_network_mode(),
            'desktop_notifications': bool(saved_ui.get('desktop_notifications', True)),
            'onboarding_done': bool(saved_ui.get('onboarding_done', False)),
        },
        'ai': {
            'provider': ui_recommended_provider,
            'active_provider': active_provider,
            'api_base': api_base,
            'api_model': api_model,
            'api_models': list(saved_ai.get('api_models') or []),
            'api_configured': api_configured,
            'api_key_masked': us.mask_secret(api_key),
            'ollama_base_url': ollama_url,
            'ollama_model': ollama_model,
            'ollama_online': ollama_online,
            'ollama_models': ollama_models,
        },
        'tushare': {
            'ready': tushare_ready,
            'token_count': len(tokens),
            'primary_masked': primary_masked,
            'backup_masked': backup_masked,
            'has_saved_override': bool(saved_ts.get('primary_token') or saved_ts.get('backup_tokens')),
        },
        'links': {
            'deepseek_api': us.DEEPSEEK_PLATFORM_URL,
            'tushare_token': us.TUSHARE_TOKEN_URL,
            'tushare_register': 'https://tushare.pro/register',
            'github_releases': version.GITHUB_RELEASES_PAGE,
        },
    })


@settings_bp.route('/settings/save_preferences', methods=['POST'])
def save_preferences():
    """保存界面语言（中/英）、网络直连/代理模式及桌面通知开关，并立即在当前进程生效。"""
    payload = request.get_json(silent=True) or {}
    current = us.load_user_settings()
    ui_block = dict(current.get('ui') or {})
    net_block = dict(current.get('network') or {})

    if 'language' in payload:
        lang = str(payload.get('language') or 'zh-CN').strip()
        ui_block['language'] = 'en-US' if lang.lower().startswith('en') else 'zh-CN'

    if 'icon_variant' in payload:
        ivar = str(payload.get('icon_variant') or 'bull').strip().lower()
        if ivar in ('bull', 'bear'):
            ui_block['icon_variant'] = ivar

    if 'desktop_notifications' in payload:
        ui_block['desktop_notifications'] = bool(payload.get('desktop_notifications'))

    if 'onboarding_done' in payload:
        ui_block['onboarding_done'] = bool(payload.get('onboarding_done'))

    if 'network_mode' in payload:
        nmode = str(payload.get('network_mode') or 'direct').strip().lower()
        if nmode in ('direct', 'proxy'):
            net_block['mode'] = nmode
            net_guard.reconfigure_network_mode(nmode)

    current['ui'] = ui_block
    current['network'] = net_block
    us.save_user_settings(current)
    us.apply_ai_settings(config.AI_CONFIG)

    return jsonify({
        'success': True,
        'preferences': {
            'language': ui_block.get('language', 'zh-CN'),
            'icon_variant': ui_block.get('icon_variant', 'bull'),
            'network_mode': net_block.get('mode', 'direct'),
            'desktop_notifications': bool(ui_block.get('desktop_notifications', True)),
            'onboarding_done': bool(ui_block.get('onboarding_done', False)),
        },
        'message': 'Preferences saved' if ui_block.get('language') == 'en-US' else '偏好设置已保存并生效',
    })


@settings_bp.route('/settings/check_update', methods=['GET'])
def check_for_updates():
    """对接 GitHub Releases 检测新版本，单次超时请求不自动重试，返回匹配渠道升级方式。"""
    current_ver = version.APP_VERSION
    channel = detect_install_channel()

    upgrade_commands = {
        'homebrew': f'brew upgrade --cask {version.HOMEBREW_CASK}',
        'npm': f'npm install -g {version.NPM_PACKAGE}@latest',
        'source': 'git pull origin main',
        'app_bundle': '',
    }

    req = urllib.request.Request(
        version.GITHUB_RELEASES_API,
        headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': f'{version.APP_NAME}/{current_ver}',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            release = json.loads(resp.read().decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as exc:
        return jsonify({
            'success': False,
            'current_version': current_ver,
            'releases_url': version.GITHUB_RELEASES_PAGE,
            'message': f'GitHub Release 查询返回 HTTP {exc.code}，可点击前往发布页手动查看',
        })
    except Exception as exc:
        return jsonify({
            'success': False,
            'current_version': current_ver,
            'releases_url': version.GITHUB_RELEASES_PAGE,
            'message': f'暂时无法连接 GitHub 更新源（{type(exc).__name__}）。若处于国内受限网络，可在设置中临时切换为「跟随系统代理」或直接访问发布页。',
        })

    latest_tag = str(release.get('tag_name') or '').strip()
    latest_clean = latest_tag.lstrip('vV') or current_ver
    has_update = _parse_semver(latest_clean) > _parse_semver(current_ver)
    matched_asset = _match_platform_asset(release.get('assets') or [])

    return jsonify({
        'success': True,
        'has_update': has_update,
        'current_version': current_ver,
        'latest_version': latest_clean,
        'latest_tag': latest_tag or f'v{latest_clean}',
        'release_name': str(release.get('name') or latest_tag),
        'published_at': str(release.get('published_at') or '')[:10],
        'release_notes': str(release.get('body') or '').strip()[:3000],
        'html_url': str(release.get('html_url') or version.GITHUB_RELEASES_PAGE),
        'channel': channel,
        'upgrade_command': upgrade_commands.get(channel, ''),
        'recommended_asset': matched_asset,
    })


@settings_bp.route('/settings/diagnostics', methods=['GET'])
def run_system_diagnostics():
    """运行电脑权限与系统运行环境自检（磁盘读写、本地回环、国内行情连通、数据源与平台信任指引）。"""
    checks = []
    user_dir = app_paths.get_user_data_dir()

    # 1. 本地应用数据目录读写权限与剩余空间
    try:
        os.makedirs(user_dir, exist_ok=True)
        probe_file = os.path.join(user_dir, f'.perm_probe_{uuid.uuid4().hex[:8]}')
        with open(probe_file, 'w', encoding='utf-8') as fh:
            fh.write('ok')
        os.remove(probe_file)
        usage = shutil.disk_usage(user_dir)
        free_gb = round(usage.free / (1024 ** 3), 1)
        fb_note_zh = '（已自动启用便携目录模式）' if app_paths.is_using_fallback_data_dir() else ''
        fb_note_en = ' (portable directory fallback active)' if app_paths.is_using_fallback_data_dir() else ''
        checks.append({
            'id': 'storage',
            'ok': True,
            'title_zh': '本地数据目录读写权限',
            'title_en': 'Local Data Directory Read/Write',
            'detail_zh': f'读写正常{fb_note_zh} · 可用磁盘空间 {free_gb} GB ({user_dir})',
            'detail_en': f'Read/write granted{fb_note_en} · {free_gb} GB free ({user_dir})',
        })
    except Exception as exc:
        checks.append({
            'id': 'storage',
            'ok': False,
            'title_zh': '本地数据目录读写权限',
            'title_en': 'Local Data Directory Read/Write',
            'detail_zh': f'目录不可写：{exc}',
            'detail_en': f'Directory not writable: {exc}',
        })

    # 2. 本地回环与防火墙安全策略
    host_cfg = os.environ.get('GP_ANA_WEB_HOST', '127.0.0.1').strip() or '127.0.0.1'
    loopback_only = host_cfg in ('127.0.0.1', 'localhost', '::1')
    checks.append({
        'id': 'firewall',
        'ok': True,
        'title_zh': '本地回环监听与防火墙保护',
        'title_en': 'Loopback Binding & Firewall Safety',
        'detail_zh': (f'仅绑定本机回环 ({host_cfg})，不暴露局域网端口，无需额外开启入站防火墙权限'
                      if loopback_only else f'当前监听全部网卡 ({host_cfg})，首次启动请允许系统防火墙放行'),
        'detail_en': (f'Bound strictly to loopback ({host_cfg}); no inbound firewall rule required'
                      if loopback_only else f'Listening on {host_cfg}; allow OS firewall prompt if shown'),
    })

    # 3. 国内实时行情网关出站网络权限（东方财富 push2 轻量探测）
    net_info = net_guard.status()
    try:
        req = urllib.request.Request(
            'https://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f43,f58',
            headers={'User-Agent': 'Mozilla/5.0'},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            ok_feed = (resp.status == 200)
        checks.append({
            'id': 'market_network',
            'ok': ok_feed,
            'title_zh': '出站网络与国内行情源连通性',
            'title_en': 'Outbound Network & Market Data Feed',
            'detail_zh': f'东方财富实时接口连通正常 · 当前策略：{net_info.get("detail", "直连")}',
            'detail_en': f'Eastmoney market feed reachable · Mode: {us.get_network_mode()}',
        })
    except Exception as exc:
        checks.append({
            'id': 'market_network',
            'ok': False,
            'title_zh': '出站网络与国内行情源连通性',
            'title_en': 'Outbound Network & Market Data Feed',
            'detail_zh': f'行情源连接受阻（{type(exc).__name__}），请检查系统网络或防火墙出站限制',
            'detail_en': f'Market feed unreachable ({type(exc).__name__}); check network or firewall',
        })

    # 4. 操作系统签名与信任指引提示
    if sys.platform == 'darwin':
        os_tip_zh = 'macOS 无需摄像头/麦克风/辅助功能等隐私权限；若他机首次打开提示“无法验证开发者”，执行 xattr -cr /Applications/Floe.app 即可放行'
        os_tip_en = 'No macOS privacy TCC permissions needed; if Gatekeeper prompts on first launch, run: xattr -cr /Applications/Floe.app'
    elif os.name == 'nt':
        os_tip_zh = 'Windows 无需管理员权限即可运行；若 SmartScreen 首次提示未知发布者，点击“更多信息 → 仍要运行”即可'
        os_tip_en = 'Runs without Administrator privileges; if Windows SmartScreen appears on first run, click More info -> Run anyway'
    else:
        os_tip_zh = 'Linux 直接赋予 AppImage 可执行权限（chmod +x）即可运行，无需 root 权限'
        os_tip_en = 'Make the AppImage executable (chmod +x) and run directly as normal user'

    checks.append({
        'id': 'os_trust',
        'ok': True,
        'title_zh': '系统安全沙盒与最小权限原则',
        'title_en': 'OS Sandbox & Least-Privilege Policy',
        'detail_zh': os_tip_zh,
        'detail_en': os_tip_en,
    })

    return jsonify({
        'success': True,
        'user_data_dir': user_dir,
        'network_mode': us.get_network_mode(),
        'checks': checks,
    })


@settings_bp.route('/settings/open_data_dir', methods=['POST'])
def open_user_data_dir():
    """在操作系统的访达 / 资源管理器中打开本地数据存储目录。"""
    target = app_paths.ensure_user_data_layout()
    try:
        if sys.platform == 'darwin':
            subprocess.Popen(['open', target])
        elif os.name == 'nt':
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(['xdg-open', target])
        return jsonify({'success': True, 'path': target, 'message': f'已打开目录：{target}'})
    except Exception as exc:
        return jsonify({'success': False, 'path': target, 'message': f'无法自动打开目录（{exc}），路径：{target}'})


@settings_bp.route('/settings/export_backup', methods=['GET'])
def export_user_backup():
    """导出用户核心配置与资产台账备份包 (.zip)：包含关注池、买卖台账与 API 设置。"""
    buf = io.BytesIO()
    candidates = [
        ('user_settings.json', us.resolve_settings_file()),
        ('watchlist.py', app_paths.get_watchlist_file()),
        ('trading_records.py', app_paths.get_trading_records_file()),
    ]
    included = []
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for arcname, full_path in candidates:
            if os.path.isfile(full_path):
                zf.write(full_path, arcname=arcname)
                included.append(arcname)
        manifest = {
            'app': version.APP_NAME,
            'version': version.APP_VERSION,
            'exported_at': datetime.now().isoformat(timespec='seconds'),
            'files': included,
        }
        zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'Floe_backup_{stamp}.zip',
    )


@settings_bp.route('/settings/import_backup', methods=['POST'])
def import_user_backup():
    """从备份包 (.zip) 安全校验并恢复关注池、交易台账与系统设置。"""
    upload = request.files.get('file')
    if not upload:
        return jsonify({'success': False, 'message': '请选择要导入的 Floe 备份 .zip 文件'})

    raw_bytes = upload.read(5 * 1024 * 1024 + 1)
    if len(raw_bytes) > 5 * 1024 * 1024:
        return jsonify({'success': False, 'message': '备份文件超过 5MB 安全上限，已拒绝导入'})

    try:
        restored = []
        with zipfile.ZipFile(io.BytesIO(raw_bytes), 'r') as zf:
            names = set(zf.namelist())
            if 'user_settings.json' in names:
                cfg_data = json.loads(zf.read('user_settings.json').decode('utf-8'))
                if not isinstance(cfg_data, dict):
                    raise ValueError('user_settings.json 格式无效')
                us.save_user_settings(cfg_data)
                us.apply_ai_settings(config.AI_CONFIG)
                restored.append('user_settings.json')

            if 'watchlist.py' in names:
                wl_text = zf.read('watchlist.py').decode('utf-8')
                _validate_python_literal_assignment(wl_text, 'WATCHLIST', list)
                wl_target = app_paths.get_watchlist_file()
                os.makedirs(os.path.dirname(os.path.abspath(wl_target)), exist_ok=True)
                with open(wl_target, 'w', encoding='utf-8') as fh:
                    fh.write(wl_text)
                restored.append('watchlist.py')

            if 'trading_records.py' in names:
                tr_text = zf.read('trading_records.py').decode('utf-8')
                _validate_python_literal_assignment(tr_text, 'TRADING_RECORDS', dict)
                tr_target = app_paths.get_trading_records_file()
                os.makedirs(os.path.dirname(os.path.abspath(tr_target)), exist_ok=True)
                with open(tr_target, 'w', encoding='utf-8') as fh:
                    fh.write(tr_text)
                restored.append('trading_records.py')

        if not restored:
            return jsonify({'success': False, 'message': '压缩包中未找到可恢复的配置文件'})
        return jsonify({
            'success': True,
            'restored': restored,
            'message': f'成功恢复 {len(restored)} 项数据（{", ".join(restored)}）',
        })
    except zipfile.BadZipFile:
        return jsonify({'success': False, 'message': '文件不是有效的 ZIP 压缩包'})
    except Exception as exc:
        return jsonify({'success': False, 'message': f'备份校验或恢复失败：{exc}'})


@settings_bp.route('/settings/fetch_models', methods=['POST'])
def fetch_ai_models():
    """第一步：验证 API / 本地 Ollama 连接并实时拉取可选模型列表。"""
    payload = request.get_json(silent=True) or {}
    provider = str(payload.get('provider') or 'api').strip().lower()
    saved_ai = (us.load_user_settings().get('ai') or {})

    if provider == 'ollama':
        base_url = str(payload.get('ollama_base_url') or saved_ai.get('ollama_base_url')
                       or 'http://localhost:11434').strip()
        online, models, err = us.probe_ollama(base_url, timeout=3.0)
        if not online:
            return jsonify({'success': False, 'message': f'无法连接本地 Ollama ({base_url})：{err}'})
        if not models:
            return jsonify({'success': False, 'message': f'已连接 {base_url}，但本机尚未拉取任何模型（请先执行 ollama pull）'})
        return jsonify({
            'success': True,
            'provider': 'ollama',
            'models': models,
            'message': f'连接通过，已获取 {len(models)} 个本地可用模型，请在下方选择后保存',
        })

    api_base = str(payload.get('api_base') or saved_ai.get('api_base') or us.DEFAULT_API_BASE).strip()
    api_key = str(payload.get('api_key') or '').strip()
    if not api_key and api_base == str(saved_ai.get('api_base') or us.DEFAULT_API_BASE).strip():
        api_key = str(saved_ai.get('api_key') or '').strip()
    if not api_key:
        return jsonify({'success': False, 'message': '请先填写 API Key 再点击验证连接'})

    try:
        models = us.fetch_openai_compatible_models(api_base=api_base, api_key=api_key, timeout=12)
        return jsonify({
            'success': True,
            'provider': 'api',
            'models': models,
            'message': f'API 链接验证通过！已获取 {len(models)} 个可用模型，请在下方选择后保存',
        })
    except Exception as exc:
        return jsonify({'success': False, 'message': f'API 连接验证失败：{exc}'})


@settings_bp.route('/settings/save_ai', methods=['POST'])
def save_ai_settings():
    """第二步：在连接通过并选定返回列表中的模型后，保存 AI 配置并即时生效。"""
    payload = request.get_json(silent=True) or {}
    provider = str(payload.get('provider') or 'api').strip().lower()
    if provider not in ('api', 'ollama'):
        return jsonify({'success': False, 'message': '无效的 AI 模式，仅支持 api 或 ollama'})

    selected_model = str(payload.get('selected_model') or payload.get('api_model')
                         or payload.get('ollama_model') or '').strip()
    if not selected_model:
        return jsonify({'success': False, 'message': '请先验证连接并从返回的模型列表中选择一个模型'})

    current = us.load_user_settings()
    ai_block = dict(current.get('ai') or {})
    ai_block['provider'] = provider

    if provider == 'api':
        ai_block['api_base'] = str(payload.get('api_base') or us.DEFAULT_API_BASE).strip() or us.DEFAULT_API_BASE
        ai_block['api_model'] = selected_model
        if isinstance(payload.get('verified_models'), list) and payload['verified_models']:
            ai_block['api_models'] = [str(m).strip() for m in payload['verified_models'] if str(m).strip()]
        new_key = str(payload.get('api_key') or '').strip()
        if payload.get('clear_api_key'):
            ai_block['api_key'] = ''
        elif new_key:
            ai_block['api_key'] = new_key
        if not str(ai_block.get('api_key') or '').strip():
            return jsonify({'success': False, 'message': '请填写有效的 API Key 并先通过连接验证'})
    else:
        ai_block['ollama_base_url'] = str(payload.get('ollama_base_url') or 'http://localhost:11434').strip()
        ai_block['ollama_model'] = selected_model

    current['ai'] = ai_block
    us.save_user_settings(current)
    us.apply_ai_settings(config.AI_CONFIG)

    return jsonify({'success': True, 'message': f'已启用模型 {selected_model}，配置立即生效'})


@settings_bp.route('/settings/test_ai', methods=['POST'])
def test_ai_settings():
    """测试当前填写的云端 API 或本地 Ollama 是否连通。"""
    payload = request.get_json(silent=True) or {}
    provider = str(payload.get('provider') or 'api').strip().lower()
    saved_ai = (us.load_user_settings().get('ai') or {})

    if provider == 'ollama':
        base_url = str(payload.get('ollama_base_url') or saved_ai.get('ollama_base_url')
                       or 'http://localhost:11434').strip()
        online, models, err = us.probe_ollama(base_url, timeout=2.5)
        if not online:
            return jsonify({'success': False, 'message': f'无法连接本地 Ollama ({base_url})：{err}'})
        return jsonify({
            'success': True,
            'message': f'本地 Ollama 连接正常，共检测到 {len(models)} 个已安装模型',
            'models': models,
        })

    api_base = str(payload.get('api_base') or saved_ai.get('api_base') or us.DEFAULT_API_BASE).strip()
    api_model = str(payload.get('api_model') or saved_ai.get('api_model') or us.DEFAULT_API_MODEL).strip()
    api_key = str(payload.get('api_key') or '').strip() or str(saved_ai.get('api_key') or '').strip()
    if not api_key:
        return jsonify({'success': False, 'message': '请先输入 API Key 再进行连接测试'})

    try:
        resp = us.call_openai_compatible_chat(
            api_base=api_base,
            api_key=api_key,
            model=api_model,
            messages=[{'role': 'user', 'content': '请仅回复OK两个字母'}],
            options={'temperature': 0.0, 'num_predict': 16},
            timeout=15,
        )
        reply = (resp.get('message') or {}).get('content', '').strip()
        return jsonify({'success': True, 'message': f'API 连通测试成功（模型 {api_model} 响应：{reply[:30]}）'})
    except Exception as exc:
        return jsonify({'success': False, 'message': f'API 连通失败：{exc}'})


@settings_bp.route('/settings/save_tushare', methods=['POST'])
def save_tushare_settings():
    """保存 Tushare 主备 Token 配置并校验可用性。"""
    payload = request.get_json(silent=True) or {}
    current = us.load_user_settings()
    ts_block = dict(current.get('tushare') or {})

    primary = str(payload.get('primary_token') or '').strip()
    backup_raw = payload.get('backup_tokens')

    if payload.get('clear_tokens'):
        ts_block = {'primary_token': '', 'backup_tokens': []}
    else:
        if primary:
            if primary == us.PLACEHOLDER_TOKEN:
                return jsonify({'success': False, 'message': '请填写您真实的 Tushare Token，不要填写占位符'})
            ts_block['primary_token'] = primary
        if backup_raw is not None:
            if isinstance(backup_raw, str):
                backups = [t.strip() for t in backup_raw.replace('\n', ',').split(',')
                           if t.strip() and t.strip() != us.PLACEHOLDER_TOKEN]
            elif isinstance(backup_raw, list):
                backups = [str(t).strip() for t in backup_raw
                           if str(t).strip() and str(t).strip() != us.PLACEHOLDER_TOKEN]
            else:
                backups = []
            ts_block['backup_tokens'] = backups

    current['tushare'] = ts_block
    us.save_user_settings(current)

    try:
        tokens = tushare_client.resolve_tokens()
    except RuntimeError as exc:
        return jsonify({'success': False, 'message': str(exc)})

    return jsonify({
        'success': True,
        'message': f'Tushare 配置已保存，当前共 {len(tokens)} 个有效 Token 可用',
        'token_count': len(tokens),
    })
