
# web_ui.py
# 股票分析Web界面
import os
import socket
import sys
from flask import Flask, render_template, request, jsonify, send_file, make_response

# 添加项目根目录到Python路径并初始化跨平台数据路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app_paths import activate_runtime_paths, get_bundle_dir
activate_runtime_paths()

# 网络代理守护：默认直连、不使用系统代理（子进程会继承该设置）
from net_guard import ensure_network_ready
ensure_network_ready()

_bundle_root = get_bundle_dir()
app = Flask(
    __name__,
    template_folder=os.path.join(_bundle_root, 'templates'),
    static_folder=os.path.join(_bundle_root, 'static'),
)

# 导入API模块
from api.analysis import analysis_bp
from api.trading import trading_bp
from api.detailed import detailed_bp
from api.report_viewer import report_viewer_bp
from api.quick_analysis import quick_analysis_bp
from api.backtest import backtest_bp
from api.sector import sector_bp
from api.stock_selection import stock_selection_bp
from api.watchlist import watchlist_bp
from api.settings import settings_bp

# 注册蓝图
app.register_blueprint(analysis_bp, url_prefix='/api')
app.register_blueprint(trading_bp, url_prefix='/api')
app.register_blueprint(detailed_bp, url_prefix='/api')
app.register_blueprint(report_viewer_bp, url_prefix='/api')
app.register_blueprint(quick_analysis_bp, url_prefix='/api')
app.register_blueprint(backtest_bp, url_prefix='/api/backtest')
app.register_blueprint(sector_bp, url_prefix='/api')
app.register_blueprint(stock_selection_bp, url_prefix='/api')
app.register_blueprint(watchlist_bp, url_prefix='/api')
app.register_blueprint(settings_bp, url_prefix='/api')

@app.route('/')
def index():
    # 前端是单页面，浏览器可能缓存旧 HTML/JS，导致改版后刷新仍看到旧界面。
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-store, must-revalidate'
    return response


def _parse_bool(value):
    """解析环境变量中的布尔值。"""
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def is_port_available(host, port):
    """检测指定 (host, port) 是否空闲且当前用户有权限绑定。"""
    family = socket.AF_INET6 if ':' in str(host) else socket.AF_INET
    probe_host = '::1' if family == socket.AF_INET6 else (
        '127.0.0.1' if host in ('0.0.0.0', '') else host
    )
    # 1. 先探测是否已有进程正在该端口 LISTEN（防止 Windows SO_REUSEADDR 或通配网卡假阴性）
    with socket.socket(family, socket.SOCK_STREAM) as conn:
        conn.settimeout(0.15)
        if conn.connect_ex((probe_host, port)) == 0:
            return False

    # 2. 尝试按 Werkzeug 同等套接字选项试绑，确认无占用且无特权端口权限拦截
    with socket.socket(family, socket.SOCK_STREAM) as srv:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((host, port))
            return True
        except OSError:
            return False


def pick_available_port(host, preferred_port, max_tries=30):
    """若首选端口被占用或无权限，自动向后顺延寻找空闲端口；全部占满时由系统分配。"""
    pref = int(preferred_port)
    if is_port_available(host, pref):
        return pref

    start = max(1024, pref + 1)
    for candidate in range(start, min(65535, start + max_tries)):
        if is_port_available(host, candidate):
            return candidate

    # 兜底：交由操作系统分配任意可用端口
    family = socket.AF_INET6 if ':' in str(host) else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as srv:
        srv.bind((host, 0))
        return int(srv.getsockname()[1])


def get_run_config():
    """读取 Web 服务监听配置，返回 (host, port, debug)。

    默认只监听本机 127.0.0.1 且关闭调试模式，避免把服务暴露到局域网；
    需要覆盖时设置环境变量 GP_ANA_WEB_HOST / GP_ANA_WEB_PORT / GP_ANA_WEB_DEBUG。
    """
    host = os.environ.get('GP_ANA_WEB_HOST', '127.0.0.1').strip() or '127.0.0.1'
    raw_port = os.environ.get('GP_ANA_WEB_PORT', '').strip()
    port = int(raw_port) if raw_port.isdigit() and 1 <= int(raw_port) <= 65535 else 3130
    debug = _parse_bool(os.environ.get('GP_ANA_WEB_DEBUG', ''))
    return host, port, debug


if __name__ == '__main__':
    run_host, preferred_port, run_debug = get_run_config()
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' and os.environ.get('_GP_ANA_ACTUAL_PORT'):
        run_port = int(os.environ['_GP_ANA_ACTUAL_PORT'])
    else:
        run_port = pick_available_port(run_host, preferred_port)
        os.environ['_GP_ANA_ACTUAL_PORT'] = str(run_port)
        if run_port != preferred_port:
            print(f"⚠️  端口 {preferred_port} 已被占用或不可用，已自动切换至空闲端口：{run_port}")

    # 项目按 Python 3.10/3.11 的依赖锁定（numpy 1.26 等）；用更高版本解释器起服务时，
    # 子进程会用同一个解释器跑指标/回测，容易踩依赖或数值口径差异，这里显式提示。
    if sys.version_info >= (3, 12):
        print(f"⚠️  当前解释器是 Python {sys.version.split()[0]}，项目按 3.10/3.11 验证。")
        print("   建议使用 Python 3.10 或 3.11 环境运行 web_ui.py")
    print(f"股票分析 Web 界面：http://{run_host}:{run_port}（debug={run_debug}）")
    if run_host in ('0.0.0.0', '::'):
        print("提示：当前监听所有网卡，局域网内其他设备可以访问该服务")
    app.run(host=run_host, port=run_port, debug=run_debug)
