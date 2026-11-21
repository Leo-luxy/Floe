# net_guard.py
# -*- coding:utf-8 -*-
"""
网络代理守护模块

设计前提
--------
本机的系统代理（127.0.0.1:10808，v2rayN）只是用来翻墙的，**平时并不常开**；
而本项目的全部数据源都是国内站点（新浪财经、东方财富、Tushare、同花顺、巨潮…），
本地 LLM 则是 localhost，**没有一个需要走代理**。

因此本模块的默认行为是：**本项目所有进程一律直连，不使用系统代理**。
这样代理开不开都不影响抓数——代理开着也走直连，代理关了照样能抓。

反面教材（2026-09-30 事故）
--------------------------
系统代理指向 127.0.0.1:10808，v2rayN 关机后没有自启，端口无人监听；
Python 的 requests / urllib 自动读取系统代理设置，于是 akshare、Tushare
的请求全部抛 ProxyError，行情抓取整体失败，脚本又把异常吞掉，
最后拿旧数据算出一份「看起来正常」的结果。

使用方式
--------
    import net_guard
    net_guard.ensure_network_ready()          # 进程内直连（默认行为）

特殊情况
--------
  * 若某天必须在代理环境下运行（例如海外网络直连不到国内源）：
        设置环境变量 GP_ANA_NET_MODE=proxy
    此时优先走系统代理；代理连不上会自动回退直连并打印警告。
  * 命令行自检：
        python net_guard.py

注意：环境变量名不要以 `_proxy` 结尾，否则会被 urllib 当成代理配置读进去。
"""

import base64
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

_STATE = {
    'checked': False,   # 是否已初始化
    'mode': None,       # 见 _MODE_TEXT
    'targets': [],      # 系统配置的代理 (host, port)
    'detail': '',       # 说明文字
}

_MODE_TEXT = {
    'direct-default': '直连（默认：不使用系统代理）',
    'proxy-active': '使用系统代理（GP_ANA_NET_MODE=proxy）',
    'direct-fallback': '代理不可用 → 已回退直连',
    'proxy-none': '要求走代理但系统未配置代理 → 直连',
}

# 只承认这些 scheme，避免把无关的环境变量误当成代理配置
_KNOWN_SCHEMES = ('http', 'https', 'socks', 'socks5', 'all', 'ftp')

# 探测顺序：urllib 里对同一份代理配置会给出 http/https/socks 多个键
_DEFAULT_PORTS = {'http': 80, 'https': 443, 'socks': 1080, 'socks5': 1080,
                  'all': 1080, 'ftp': 21}

# 直连时清掉的环境变量
_PROXY_ENV_KEYS = (
    'http_proxy', 'https_proxy', 'all_proxy', 'ftp_proxy',
    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'FTP_PROXY',
)

_ORIG_URLLIB_GETPROXIES = urllib.request.getproxies
_INITIAL_PROXY_ENV = {
    k: os.environ[k] for k in _PROXY_ENV_KEYS if os.environ.get(k, '').strip()
}


def _ensure_ssl_ready():
    """确保打包态与源码态均已挂载有效的 CA 根证书束。"""
    try:
        import app_paths
        return app_paths.ensure_ssl_certificates()
    except Exception:
        return ''


def _raw_system_proxy_dict():
    """读取操作系统原生代理配置与初始环境变量代理（不受运行时 no_proxy=* 短路干扰）。"""
    merged = {}
    for getter_name in ('getproxies_macosx_sysconf', 'getproxies_registry'):
        getter = getattr(urllib.request, getter_name, None)
        if callable(getter):
            try:
                sys_map = getter() or {}
                if isinstance(sys_map, dict):
                    merged.update(sys_map)
            except Exception:
                pass

    try:
        orig_map = _ORIG_URLLIB_GETPROXIES() or {}
        if isinstance(orig_map, dict):
            for k, v in orig_map.items():
                if str(k).lower() not in ('no', 'no_proxy') and v:
                    merged.setdefault(k, v)
    except Exception:
        pass

    for env_key, env_val in _INITIAL_PROXY_ENV.items():
        scheme = env_key.lower().replace('_proxy', '')
        if scheme and env_val:
            merged.setdefault(scheme, env_val)

    return merged


def _system_proxy_targets():
    """返回系统配置的代理 [(host, port), ...]（去重）"""
    proxies = _raw_system_proxy_dict()

    targets = []
    for scheme, url in proxies.items():
        scheme = scheme.lower()
        if not url or scheme in ('no', 'no_proxy') or scheme not in _KNOWN_SCHEMES:
            continue
        netloc = url.split('//', 1)[1] if '//' in url else url
        netloc = netloc.rstrip('/')
        if '@' in netloc:
            netloc = netloc.rsplit('@', 1)[1]
        host, _, port = netloc.partition(':')
        if not host:
            continue
        port = int(port) if port.isdigit() else _DEFAULT_PORTS.get(scheme, 80)
        if (host, port) not in targets:
            targets.append((host, port))
    return targets


def _reachable(host, port, timeout=0.8):
    """TCP 探测代理端口是否真的有人监听"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def force_direct():
    """
    让本进程（及其子进程）内的 requests / urllib 全部直连。

    只影响当前进程树，不会改动 macOS 的系统代理设置，也不影响浏览器和 git。
    """
    os.environ['no_proxy'] = '*'
    os.environ['NO_PROXY'] = '*'
    for key in _PROXY_ENV_KEYS:
        os.environ.pop(key, None)

    # 兜底：系统代理（macOS 系统设置）不走环境变量，requests 通过 getproxies() 读取，
    # 这里直接替换掉，确保任何路径都不会再挂到那个代理端口上。
    try:
        import requests.utils as requests_utils
        requests_utils.getproxies = lambda: {}
    except Exception:
        pass
    try:
        urllib.request.getproxies = lambda: {}
    except Exception:
        pass


def _normalize_http_proxy_url(raw_url: str) -> str:
    """规范化 HTTP 代理地址；修正 Windows 注册表常见的本地代理被误标为 https://127.0.0.1:PORT 导致 TLS 握手失败的问题。"""
    text = str(raw_url or '').strip()
    if not text:
        return ''
    if '://' not in text:
        text = 'http://' + text
    parsed = urllib.parse.urlsplit(text)
    scheme = (parsed.scheme or 'http').lower()
    host = (parsed.hostname or '').lower()
    if scheme not in ('http', 'https') or not host:
        return ''
    # 本地回环代理客户端（Clash / v2rayN / Surge 等）的 HTTP 混合端口均为明文 HTTP CONNECT 协议
    if scheme == 'https' and host in ('127.0.0.1', 'localhost', '::1'):
        scheme = 'http'
    port = parsed.port or (443 if scheme == 'https' else 80)
    auth = ''
    if parsed.username:
        user_q = urllib.parse.quote(urllib.parse.unquote(parsed.username), safe='')
        if parsed.password is not None:
            pwd_q = urllib.parse.quote(urllib.parse.unquote(parsed.password), safe='')
            auth = f'{user_q}:{pwd_q}@'
        else:
            auth = f'{user_q}@'
    host_fmt = f'[{host}]' if ':' in host and not host.startswith('[') else host
    return f'{scheme}://{auth}{host_fmt}:{port}'


def restore_system_proxy():
    """恢复使用操作系统配置的代理（供设置面板热切换至代理模式时调用）。"""
    if os.environ.get('no_proxy') == '*':
        os.environ.pop('no_proxy', None)
    if os.environ.get('NO_PROXY') == '*':
        os.environ.pop('NO_PROXY', None)
    for key, val in _INITIAL_PROXY_ENV.items():
        if val and not os.environ.get(key):
            os.environ[key] = val
    try:
        raw_map = _raw_system_proxy_dict()
        clean_map = {}
        for k, v in (raw_map or {}).items():
            kl = str(k).lower()
            if kl in ('http', 'https'):
                norm = _normalize_http_proxy_url(v)
                if norm:
                    clean_map[kl] = norm
        urllib.request.getproxies = (lambda: dict(clean_map)) if clean_map else _ORIG_URLLIB_GETPROXIES
        handlers = [urllib.request.ProxyHandler(clean_map)] if clean_map else []
        urllib.request.install_opener(urllib.request.build_opener(*handlers))
    except Exception:
        pass
    try:
        import requests.utils as requests_utils
        requests_utils.getproxies = urllib.request.getproxies
    except Exception:
        pass


def reconfigure_network_mode(mode='direct', verbose=False):
    """在运行期动态切换 'direct'（国内直连）或 'proxy'（跟随系统代理）。"""
    clean = str(mode or 'direct').strip().lower()
    if clean == 'proxy':
        os.environ['GP_ANA_NET_MODE'] = 'proxy'
        restore_system_proxy()
    else:
        os.environ['GP_ANA_NET_MODE'] = 'direct'
    _STATE['checked'] = False
    return ensure_network_ready(verbose=verbose)


def apply_collector_socket_timeout(seconds=25):
    """为数据采集子进程设置全局 socket 超时（akshare/requests 内部多数请求未传 timeout，
    遇到对端不响应会无限挂起，表现为分析步骤「一直卡着」直到被整步超时杀掉）。

    只在采集脚本里调用；不要在 Flask 主进程里调用，以免影响长连接。
    """
    try:
        if socket.getdefaulttimeout() is None:
            socket.setdefaulttimeout(float(seconds))
    except Exception:
        pass


def is_proxy_error(exc):
    """判断异常是否由代理不可用引起"""
    text = f'{type(exc).__name__}: {exc}'.lower()
    return 'proxy' in text


def _use_proxy_requested():
    """只有显式声明 GP_ANA_NET_MODE=proxy 时才考虑使用系统代理"""
    return os.environ.get('GP_ANA_NET_MODE', '').strip().lower() == 'proxy'


def ensure_network_ready(verbose=False):
    """
    初始化本进程的网络模式与 SSL 根证书束。幂等，可重复调用。

    默认直接直连；只有显式设置 GP_ANA_NET_MODE=proxy 时才考虑使用系统代理。

    返回 'direct-default' | 'proxy-active' | 'direct-fallback' | 'proxy-none'
    """
    _ensure_ssl_ready()
    if _STATE['checked']:
        return _STATE['mode']

    _STATE['checked'] = True
    _STATE['targets'] = _system_proxy_targets()

    if not _use_proxy_requested():
        force_direct()
        _STATE['mode'] = 'direct-default'
        _STATE['detail'] = '默认直连，不使用系统代理'
        _announce(verbose)
        return _STATE['mode']

    targets = _STATE['targets']
    if not targets:
        force_direct()
        _STATE['mode'] = 'proxy-none'
        _STATE['detail'] = 'GP_ANA_NET_MODE=proxy，但系统未配置代理，按直连处理'
        _announce(verbose)
        return _STATE['mode']

    dead = [f'{h}:{p}' for h, p in targets if not _reachable(h, p)]
    if dead:
        force_direct()
        _STATE['mode'] = 'direct-fallback'
        _STATE['detail'] = 'GP_ANA_NET_MODE=proxy，但系统代理无法连接（%s），已回退直连' % ', '.join(dead)
    else:
        _STATE['mode'] = 'proxy-active'
        _STATE['detail'] = '按要求使用系统代理：' + ', '.join(f'{h}:{p}' for h, p in targets)
    _announce(verbose)
    return _STATE['mode']


def _resolve_live_http_proxy(target_scheme='https'):
    """查找本机系统配置中在线可连的 HTTP/HTTPS 代理，返回规范化 proxy_url（如 'http://127.0.0.1:7897'）或 None。"""
    proxies = _raw_system_proxy_dict()
    if not proxies:
        return None

    t_scheme = str(target_scheme or 'https').lower()
    raw_url = (proxies.get(t_scheme) or proxies.get('https') or proxies.get('http') or proxies.get('all') or '').strip()
    norm_url = _normalize_http_proxy_url(raw_url)
    if not norm_url:
        return None

    parsed = urllib.parse.urlsplit(norm_url)
    if not parsed.hostname or not parsed.port:
        return None
    if not _reachable(parsed.hostname, parsed.port, timeout=0.6):
        return None
    return norm_url


def urlopen_with_optional_proxy(req, timeout=10.0, prefer_proxy_for_overseas=False):
    """
    发送非国内行情类的外部管理请求（如 GitHub Release 检查更新、境外大模型 API 验证）：
    1. 若当前已是 proxy-active 或 prefer_proxy_for_overseas=True 且检测到本机系统代理在线，
       优先使用局部 ProxyHandler({'http': proxy_url, 'https': proxy_url}) 发起标准 HTTP CONNECT 隧道请求
       （绝不修改全局 no_proxy，不影响任何 A 股国内数据源直连）；
    2. 若默认直连下发生网络层阻断/超时，且本机存在在线系统代理，自动走局部代理隧道重试一次；
       反之若局部代理失败，也会兜底尝试一次纯净直连。
    """
    _ensure_ssl_ready()

    if isinstance(req, urllib.request.Request):
        full_url = req.full_url
        data = req.data
        method = req.get_method()
        headers = dict(req.header_items())
    else:
        full_url = str(req)
        data = None
        method = 'GET'
        headers = {}

    def _clone_request():
        return urllib.request.Request(full_url, data=data, headers=dict(headers), method=method)

    class _ExplicitProxyHandler(urllib.request.ProxyHandler):
        """局部显式代理 Handler：保留标准 proxies 映射，且不受进程级 no_proxy=* 短路跳过。"""
        def proxy_open(self, r_obj, proxy, p_type):
            orig_type = r_obj.type
            parsed = urllib.parse.urlsplit(proxy if '://' in proxy else f'http://{proxy}')
            proxy_type = (parsed.scheme or orig_type or 'http').lower()
            p_port = parsed.port or (443 if proxy_type == 'https' else 80)
            hostport = f'{parsed.hostname}:{p_port}'
            if parsed.username and parsed.password:
                raw_cred = f'{urllib.parse.unquote(parsed.username)}:{urllib.parse.unquote(parsed.password)}'
                auth_hdr = 'Basic ' + base64.b64encode(raw_cred.encode('utf-8')).decode('ascii')
                r_obj.add_header('Proxy-authorization', auth_hdr)
            r_obj.set_proxy(hostport, orig_type if orig_type == 'https' else proxy_type)
            if orig_type == proxy_type or orig_type == 'https':
                return None
            return self.parent.open(r_obj, timeout=r_obj.timeout)

    def _open_via_proxy(proxy_url: str, req_timeout: float):
        proxy_map = {'http': proxy_url, 'https': proxy_url}
        opener = urllib.request.build_opener(_ExplicitProxyHandler(proxy_map))
        return opener.open(_clone_request(), timeout=req_timeout)

    def _open_direct(req_timeout: float):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(_clone_request(), timeout=req_timeout)

    parsed_target = urllib.parse.urlsplit(full_url)
    target_scheme = (parsed_target.scheme or 'https').lower()
    target_host = parsed_target.hostname or ''
    target_port = parsed_target.port or (443 if target_scheme == 'https' else 80)
    live_proxy = _resolve_live_http_proxy(target_scheme)

    # 若显式要求境外优先走代理隧道且检测到存活代理，直接走局部 ProxyHandler 隧道
    if live_proxy and prefer_proxy_for_overseas:
        try:
            return _open_via_proxy(live_proxy, timeout)
        except urllib.error.HTTPError:
            raise
        except Exception as proxy_exc:
            try:
                return _open_direct(min(timeout, 3.0))
            except urllib.error.HTTPError:
                raise
            except Exception:
                raise proxy_exc

    # 长耗时请求（例如云端 LLM 对话 timeout>15s）严禁把直连超时截断为 3s，否则会误杀正常模型生成：
    # 先快速探测目标直连 TCP 连通性，直连可达则给足完整 timeout，直连不可达则直接切代理给足完整 timeout。
    if float(timeout) > 15.0 and live_proxy and _STATE.get('mode') != 'proxy-active':
        direct_tcp_ok = bool(target_host) and _reachable(target_host, target_port, timeout=2.5)
        if not direct_tcp_ok:
            try:
                return _open_via_proxy(live_proxy, timeout)
            except urllib.error.HTTPError:
                raise
            except Exception as proxy_exc:
                try:
                    return urllib.request.urlopen(_clone_request(), timeout=timeout)
                except urllib.error.HTTPError:
                    raise
                except Exception as direct_exc:
                    raise RuntimeError(f'{direct_exc}；局部代理回退亦失败: {proxy_exc}') from proxy_exc

    # 默认先走当前全局 opener（direct 模式下为直连，proxy-active 模式下已挂载规范化系统代理）
    # 仅对 <=15s 的轻量探测在代理存活时使用 3s 快速直连探测，避免卡住桌面端无代理回退
    first_timeout = min(timeout, 3.0) if (live_proxy and float(timeout) <= 15.0) else timeout
    try:
        return urllib.request.urlopen(_clone_request(), timeout=first_timeout)
    except urllib.error.HTTPError:
        raise
    except Exception as first_exc:
        if 'CERTIFICATE_VERIFY_FAILED' in str(first_exc):
            raise
        if _STATE.get('mode') == 'proxy-active':
            # 代理模式下若代理节点异常，兜底尝试一次局部直连
            try:
                return _open_direct(min(timeout, 15.0))
            except urllib.error.HTTPError:
                raise
            except Exception as direct_exc:
                raise RuntimeError(f'{first_exc}；直连回退亦失败: {direct_exc}') from first_exc
        if not live_proxy:
            raise
        try:
            return _open_via_proxy(live_proxy, timeout)
        except urllib.error.HTTPError:
            raise
        except Exception as proxy_exc:
            raise RuntimeError(f'{first_exc}；局部代理回退亦失败: {proxy_exc}') from first_exc


def _announce(verbose):
    # 默认直连是正常状态，不打印，避免批量抓取时每个子进程都刷一行；
    # 「要求走代理却连不上」属于异常，一定打印出来。
    if verbose or _STATE['mode'] == 'direct-fallback':
        print(f"[net_guard] {_STATE['detail']}", flush=True)


def retry_on_proxy_error(func, *args, **kwargs):
    """
    调用 func；若因代理问题失败，则切换为直连后重试一次。

    正常情况下进程启动时已经是直连，这里是双保险（例如进程启动后才打开代理、
    或 GP_ANA_NET_MODE=proxy 但代理中途挂掉）。
    """
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        if not is_proxy_error(exc):
            raise
        if _STATE['mode'] in ('direct-default', 'direct-fallback', 'proxy-none'):
            raise
        force_direct()
        _STATE['checked'] = True
        _STATE['mode'] = 'direct-fallback'
        _STATE['detail'] = '代理请求失败，已自动改为直连后重试'
        _announce(True)
        return func(*args, **kwargs)


def status():
    """返回当前网络模式与 SSL 证书状态的可读信息（供自检与排查）"""
    ensure_network_ready()
    info = dict(_STATE)
    info['ssl_cafile'] = _ensure_ssl_ready()
    return info


def _main():
    info = status()
    print('网络模式自检：')
    print(f"  系统代理配置：{info['targets'] or '无'}")
    print(f"  当前模式：{_MODE_TEXT.get(info['mode'], info['mode'])}")
    print(f"  说明：{info['detail']}")

    # 验证一个国内数据源是否真的通
    ok = True
    for name, url in (('Tushare', 'http://api.tushare.pro'),
                      ('新浪财经', 'https://finance.sina.com.cn/realstock/company/sh600048/hisdata_klc2/klc_kl.js')):
        try:
            import requests
            resp = requests.get(url, timeout=15)
            print(f"  连通性测试：{name} → HTTP {resp.status_code}")
        except Exception as exc:
            ok = False
            print(f"  连通性测试：{name} → 失败 {type(exc).__name__}: {str(exc)[:120]}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(_main())
