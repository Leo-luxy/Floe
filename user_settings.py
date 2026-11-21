"""用户本地配置存储与云端 OpenAI 兼容 API（如 DeepSeek）桥接层。

设计目标：
1. Web 界面写入的 API Key / Tushare Token 独立保存在 gitignore 的 user_settings.json，
   不污染受版本控制的模板代码，避免同步发布时泄露密钥。
2. 当用户选择云端 API（默认推荐 DeepSeek API）时，透明接管各分析脚本中的 ollama.Client.chat，
   无需改动 16 个分析模块的调用方式即可直接使用云端大模型。
"""
import json
import os
import sys
import types
import urllib.error
import urllib.request
import uuid

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
try:
    from app_paths import get_settings_file as _get_settings_file
    SETTINGS_FILE = _get_settings_file()
except Exception:
    _get_settings_file = None
    SETTINGS_FILE = os.path.join(PROJECT_ROOT, 'user_settings.json')
_INITIAL_SETTINGS_FILE = SETTINGS_FILE

DEFAULT_API_BASE = 'https://api.deepseek.com'
DEFAULT_API_MODEL = 'deepseek-chat'
DEEPSEEK_PLATFORM_URL = 'https://platform.deepseek.com/api_keys'
TUSHARE_TOKEN_URL = 'https://tushare.pro/user/token'
PLACEHOLDER_TOKEN = 'YOUR_TUSHARE_TOKEN'

_ORIGINAL_OLLAMA_CLIENT = None


def resolve_settings_file(path=None):
    """动态解析当前生效的 user_settings.json 路径（兼容单测打桩 SETTINGS_FILE 与运行时目录回退）。"""
    if path:
        return path
    if SETTINGS_FILE != _INITIAL_SETTINGS_FILE:
        return SETTINGS_FILE
    if _get_settings_file is not None:
        return _get_settings_file()
    return SETTINGS_FILE


class _AttrDict(dict):
    """同时支持 dict['message']['content'] 与 obj.message.content 访问。"""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def mask_secret(secret):
    """对密钥做脱敏展示，保留前 4 位与后 4 位。"""
    s = str(secret or '').strip()
    if not s or s == PLACEHOLDER_TOKEN:
        return ''
    if len(s) <= 10:
        return s[:2] + '****' + s[-2:]
    return f'{s[:4]}****{s[-4:]}'


def load_user_settings(path=None):
    """读取本地 user_settings.json，不存在或格式损坏时返回空字典。"""
    target = resolve_settings_file(path)
    if not os.path.isfile(target):
        return {}
    try:
        with open(target, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_user_settings(data, path=None):
    """原子写入 user_settings.json。"""
    target = resolve_settings_file(path)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    tmp = f'{target}.{uuid.uuid4().hex}.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def get_ui_language(path=None):
    """获取当前配置的界面与研报输出语言（'zh-CN' 或 'en-US'）。"""
    ui_cfg = load_user_settings(path).get('ui') or {}
    lang = str(ui_cfg.get('language') or 'zh-CN').strip()
    return 'en-US' if lang.lower().startswith('en') else 'zh-CN'


def get_network_mode(path=None):
    """获取当前保存的网络连接策略（'direct' 国内直连 或 'proxy' 跟随系统代理）。"""
    net_cfg = load_user_settings(path).get('network') or {}
    mode = str(net_cfg.get('mode') or '').strip().lower()
    if mode in ('direct', 'proxy'):
        return mode
    return 'proxy' if os.environ.get('GP_ANA_NET_MODE', '').strip().lower() == 'proxy' else 'direct'


def _prepare_messages_for_language(messages, path=None):
    """若当前语言为 English，自动注入专业英文投研输出系统指令（无需改动各分析脚本提示词）。"""
    msg_list = list(messages or [])
    if get_ui_language(path) != 'en-US' or not msg_list:
        return msg_list
    # 单句连通性探活不额外膨胀提示词
    if len(msg_list) == 1 and len(str(msg_list[0].get('content') or '')) <= 24:
        return msg_list
    en_sys_note = (
        'CRITICAL OUTPUT LANGUAGE DIRECTIVE: The user interface language is set to English. '
        'Regardless of the language of the prompt or raw data below, write your entire '
        'research analysis, section headings, tables, risk warnings, and actionable trading '
        'decisions in clear, professional institutional financial English. Keep 6-digit stock '
        'tickers (e.g., 600519.SH) intact; you may include original Chinese stock/sector names '
        'in parentheses on first mention.'
    )
    return [{'role': 'system', 'content': en_sys_note}] + msg_list


def get_saved_tushare_tokens(path=None):
    """从 user_settings.json 提取有效的 Tushare token 列表。"""
    cfg = load_user_settings(path).get('tushare') or {}
    if not isinstance(cfg, dict):
        return []
    raw_list = [cfg.get('primary_token', '')]
    backups = cfg.get('backup_tokens') or []
    if isinstance(backups, str):
        raw_list.extend(backups.replace('\n', ',').split(','))
    elif isinstance(backups, list):
        raw_list.extend(backups)
    tokens = []
    for item in raw_list:
        val = str(item or '').strip()
        if val and val != PLACEHOLDER_TOKEN and val not in tokens:
            tokens.append(val)
    return tokens


def _build_chat_endpoints(api_base):
    """根据用户填写的 Base URL 生成候选 chat/completions 地址。"""
    base = str(api_base or DEFAULT_API_BASE).strip().rstrip('/')
    if base.endswith('/chat/completions'):
        return [base]
    if base.endswith('/v1'):
        return [f'{base}/chat/completions']
    return [f'{base}/chat/completions', f'{base}/v1/chat/completions']


def _build_models_endpoints(api_base):
    """根据用户填写的 Base URL 生成候选 /models 模型列表查询地址。"""
    base = str(api_base or DEFAULT_API_BASE).strip().rstrip('/')
    if base.endswith('/chat/completions'):
        base = base[:-len('/chat/completions')].rstrip('/')
    if base.endswith('/models'):
        return [base]
    if base.endswith('/v1'):
        return [f'{base}/models']
    return [f'{base}/models', f'{base}/v1/models']


def _urlopen_cloud_api(req, timeout):
    """发送云端大模型 API 请求：自动保障打包态 SSL 根证书，并在直连受阻时可选复用存活系统代理。"""
    try:
        import net_guard
        return net_guard.urlopen_with_optional_proxy(req, timeout=timeout)
    except ImportError:
        return urllib.request.urlopen(req, timeout=timeout)


def fetch_openai_compatible_models(api_base, api_key, timeout=10):
    """验证 OpenAI 兼容接口（如 DeepSeek API）连接并返回服务端可用模型 ID 列表。"""
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {str(api_key or "").strip()}',
        'User-Agent': 'GP_ANA/1.6',
    }
    endpoints = _build_models_endpoints(api_base)
    last_err = None
    for idx, url in enumerate(endpoints):
        req = urllib.request.Request(url, headers=headers, method='GET')
        try:
            with _urlopen_cloud_api(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode('utf-8', errors='replace'))
            raw_items = body.get('data') if isinstance(body, dict) else None
            if raw_items is None and isinstance(body, dict):
                raw_items = body.get('models')
            models = []
            for item in (raw_items or []):
                if isinstance(item, str):
                    mid = item.strip()
                elif isinstance(item, dict):
                    mid = str(item.get('id') or item.get('name') or '').strip()
                else:
                    mid = ''
                if mid and mid not in models:
                    models.append(mid)
            if not models:
                raise RuntimeError('接口连通但未返回可用模型列表，请检查 API 地址是否正确')
            # 若存在 deepseek-chat，排在首位方便默认选中
            if DEFAULT_API_MODEL in models:
                models.remove(DEFAULT_API_MODEL)
                models.insert(0, DEFAULT_API_MODEL)
            return models
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode('utf-8', errors='replace')[:240]
            if exc.code == 404 and idx + 1 < len(endpoints):
                last_err = RuntimeError(f'HTTP 404 ({url})')
                continue
            if exc.code in (401, 403):
                raise RuntimeError(f'API Key 鉴权失败 (HTTP {exc.code})，请核对密钥是否正确') from exc
            raise RuntimeError(f'HTTP {exc.code}: {err_body}') from exc
        except Exception as exc:
            last_err = exc
            raise
    raise last_err or RuntimeError('获取模型列表失败')


def call_openai_compatible_chat(api_base, api_key, model, messages, options=None, timeout=180):
    """调用 OpenAI 兼容格式（DeepSeek 等）的 Chat Completions 接口。"""
    opts = options or {}
    temperature = float(opts.get('temperature', 0.3))
    max_tokens = int(opts.get('num_predict') or opts.get('max_tokens') or 4096)
    max_tokens = max(128, min(max_tokens, 8192))

    final_messages = _prepare_messages_for_language(messages)
    payload = json.dumps({
        'model': model or DEFAULT_API_MODEL,
        'messages': final_messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
        'stream': False,
    }).encode('utf-8')

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key.strip()}',
        'User-Agent': 'GP_ANA/1.6',
    }

    last_err = None
    endpoints = _build_chat_endpoints(api_base)
    for idx, url in enumerate(endpoints):
        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        try:
            with _urlopen_cloud_api(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode('utf-8', errors='replace'))
            choices = body.get('choices') or []
            if not choices:
                raise RuntimeError(f'API 未返回 choices: {body}')
            content = (choices[0].get('message') or {}).get('content') or ''
            return _AttrDict({
                'model': body.get('model', model),
                'message': _AttrDict({'role': 'assistant', 'content': content}),
            })
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode('utf-8', errors='replace')[:300]
            last_err = RuntimeError(f'HTTP {exc.code}: {err_body}')
            if exc.code == 404 and idx + 1 < len(endpoints):
                continue
            raise last_err from exc
        except Exception as exc:
            last_err = exc
            raise
    raise last_err or RuntimeError('API 调用失败')


def install_llm_bridge(ai_config):
    """根据 AI_CONFIG 切换云端 API 桥接或恢复原生本地 Ollama 客户端。"""
    global _ORIGINAL_OLLAMA_CLIENT
    provider = ai_config.get('provider', 'ollama')
    api_key = str(ai_config.get('api_key') or '').strip()

    try:
        import ollama
    except ImportError:
        ollama = types.ModuleType('ollama')
        sys.modules['ollama'] = ollama

    if _ORIGINAL_OLLAMA_CLIENT is None and hasattr(ollama, 'Client'):
        _ORIGINAL_OLLAMA_CLIENT = ollama.Client

    if provider == 'api' and api_key:
        api_base = ai_config.get('api_base') or DEFAULT_API_BASE
        api_model = ai_config.get('api_model') or DEFAULT_API_MODEL

        class _CloudCompatClient:
            def __init__(self, host=None, **kwargs):
                self.host = host

            def chat(self, model=None, messages=None, options=None, **kwargs):
                use_model = api_model or model or DEFAULT_API_MODEL
                return call_openai_compatible_chat(
                    api_base=api_base,
                    api_key=api_key,
                    model=use_model,
                    messages=messages or [],
                    options=options,
                )

            def list(self):
                return {'models': [{'name': api_model}]}

        ollama.Client = _CloudCompatClient
    elif _ORIGINAL_OLLAMA_CLIENT is not None:
        if get_ui_language() == 'en-US':
            orig_cls = _ORIGINAL_OLLAMA_CLIENT

            class _LocalizedOllamaClient(orig_cls):
                def chat(self, model=None, messages=None, **kwargs):
                    localized = _prepare_messages_for_language(messages)
                    return super().chat(model=model, messages=localized, **kwargs)

            ollama.Client = _LocalizedOllamaClient
        else:
            ollama.Client = _ORIGINAL_OLLAMA_CLIENT


def apply_ai_settings(ai_config, path=None):
    """将本地保存的 AI 与网络配置合并进运行时并激活对应客户端桥接。"""
    ai_config.setdefault('provider', 'ollama')
    ai_config.setdefault('ollama_base_url', ai_config.get('base_url', 'http://localhost:11434'))
    ai_config.setdefault('ollama_model', ai_config.get('model', 'qwen3.6:35b-a3b-mlx-bf16'))
    ai_config.setdefault('api_base', DEFAULT_API_BASE)
    ai_config.setdefault('api_key', '')
    ai_config.setdefault('api_model', DEFAULT_API_MODEL)

    full_saved = load_user_settings(path)
    net_cfg = full_saved.get('network') or {}
    if isinstance(net_cfg, dict) and net_cfg.get('mode') in ('direct', 'proxy'):
        try:
            import net_guard
            net_guard.reconfigure_network_mode(net_cfg['mode'])
        except Exception:
            pass

    saved = full_saved.get('ai') or {}
    if isinstance(saved, dict) and saved:
        if saved.get('provider') in ('api', 'ollama'):
            ai_config['provider'] = saved['provider']
        if saved.get('api_base'):
            ai_config['api_base'] = str(saved['api_base']).strip()
        if 'api_key' in saved and saved['api_key'] is not None:
            ai_config['api_key'] = str(saved['api_key']).strip()
        if saved.get('api_model'):
            ai_config['api_model'] = str(saved['api_model']).strip()
        if saved.get('ollama_base_url'):
            ai_config['ollama_base_url'] = str(saved['ollama_base_url']).strip()
        if saved.get('ollama_model'):
            ai_config['ollama_model'] = str(saved['ollama_model']).strip()

    if ai_config['provider'] == 'api' and ai_config.get('api_key'):
        ai_config['model'] = ai_config['api_model']
        ai_config['fallback_models'] = []
    else:
        ai_config['base_url'] = ai_config['ollama_base_url']
        ai_config['model'] = ai_config['ollama_model']

    install_llm_bridge(ai_config)
    return ai_config


def probe_ollama(base_url='http://localhost:11434', timeout=0.8):
    """轻量探测本机 Ollama 服务是否在线并返回已下载模型名列表。"""
    url = str(base_url or 'http://localhost:11434').strip().rstrip('/') + '/api/tags'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GP_ANA/1.6'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='replace'))
        models = []
        for item in (data.get('models') or []):
            name = item.get('name') or item.get('model')
            if name:
                models.append(str(name))
        return True, models, ''
    except Exception as exc:
        return False, [], str(exc)
