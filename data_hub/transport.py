# -*- coding: utf-8 -*-
"""
统一网络传输与数据源熔断层
收口 HTTP 请求超时、浏览器请求头、代理策略协同（net_guard）、源级熔断器与东方财富数据中心分页客户端。
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

import requests

import net_guard

DEFAULT_TIMEOUT: float = 18.0

_DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_GUARD_APPLIED = False
_GUARD_LOCK = threading.Lock()


def ensure_network_guard(socket_timeout: float = 25.0) -> None:
    """幂等地激活全局 socket 超时与代理策略，防止第三方库无限阻塞。"""
    global _GUARD_APPLIED
    with _GUARD_LOCK:
        if not _GUARD_APPLIED:
            try:
                net_guard.apply_collector_socket_timeout(socket_timeout)
            except Exception:
                pass
            _GUARD_APPLIED = True


def call_akshare(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """统一调用 akshare 函数：自动激活 socket 超时守护，并在代理异常时切换直连重试。"""
    ensure_network_guard(25.0)
    return net_guard.retry_on_proxy_error(fn, *args, **kwargs)


class SourceCircuitBreaker:
    """线程安全的数据源级熔断器。

    当同一底层源（如 akshare_em / sina / eastmoney_dc）在短时间内连续失败达到阈值时，
    在冷却期内直接跳过该源并路由到备选源，避免反复卡死在坏接口上。
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 120.0) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self._lock = threading.Lock()
        self._failures: Dict[str, int] = {}
        self._opened_at: Dict[str, float] = {}
        self._last_error: Dict[str, str] = {}

    def is_open(self, source: str) -> bool:
        """判断数据源当前是否处于熔断开启状态。"""
        with self._lock:
            opened_at = self._opened_at.get(source)
            if opened_at is None:
                return False
            elapsed = time.monotonic() - opened_at
            if elapsed >= self.cooldown_seconds:
                # 冷却期结束，进入半开探测状态：放行一次请求并重置计数
                self._opened_at.pop(source, None)
                self._failures[source] = max(0, self.failure_threshold - 1)
                return False
            return True

    def record_success(self, source: str) -> None:
        """记录成功请求并关闭对应数据源的熔断状态。"""
        with self._lock:
            self._failures.pop(source, None)
            self._opened_at.pop(source, None)
            self._last_error.pop(source, None)

    def record_failure(self, source: str, exc: Optional[Exception] = None, trip: bool = True) -> None:
        """记录失败；当 trip=True 且连续失败达到阈值时打开熔断器。"""
        if not trip:
            return
        with self._lock:
            count = self._failures.get(source, 0) + 1
            self._failures[source] = count
            if exc is not None:
                self._last_error[source] = f"{type(exc).__name__}: {exc}"
            if count >= self.failure_threshold:
                self._opened_at[source] = time.monotonic()

    def reset(self, source: Optional[str] = None) -> None:
        """重置指定源或全部源的熔断状态。"""
        with self._lock:
            if source is None:
                self._failures.clear()
                self._opened_at.clear()
                self._last_error.clear()
            else:
                self._failures.pop(source, None)
                self._opened_at.pop(source, None)
                self._last_error.pop(source, None)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        """返回各数据源熔断状态的只读快照，便于诊断输出与单测校验。"""
        now = time.monotonic()
        with self._lock:
            sources = set(self._failures.keys()) | set(self._opened_at.keys())
            result: Dict[str, Dict[str, Any]] = {}
            for src in sorted(sources):
                opened_at = self._opened_at.get(src)
                remaining = 0.0
                is_open = False
                if opened_at is not None:
                    remaining = max(0.0, self.cooldown_seconds - (now - opened_at))
                    is_open = remaining > 0.0
                result[src] = {
                    "failures": self._failures.get(src, 0),
                    "is_open": is_open,
                    "remaining_seconds": round(remaining, 2),
                    "last_error": self._last_error.get(src, ""),
                }
            return result


class UnifiedTransport:
    """统一 HTTP 传输客户端：内置默认超时、真实浏览器头与代理协同。"""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = float(timeout)
        self._thread_local = threading.local()

    def _get_session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(_DEFAULT_HEADERS)
            self._thread_local.session = session
        return session

    @staticmethod
    def _is_proxy_mode() -> bool:
        try:
            mode = os.environ.get("GP_ANA_NET_MODE", "").strip().lower()
            if not mode and hasattr(net_guard, "get_net_mode"):
                mode = str(net_guard.get_net_mode() or "").strip().lower()
            return mode == "proxy"
        except Exception:
            return False

    def request_raw(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        method: str = "GET",
        json_body: Any = None,
        data: Any = None,
        timeout: Optional[float] = None,
        retries: int = 1,
    ) -> requests.Response:
        """发送 HTTP 请求并返回校验状态码后的 Response。"""
        ensure_network_guard(max(self.timeout, 25.0))
        eff_timeout = float(timeout) if timeout is not None else self.timeout
        merged_headers = dict(_DEFAULT_HEADERS)
        if headers:
            merged_headers.update(headers)

        def _do_request() -> requests.Response:
            session = self._get_session()
            # 直连模式下确保不读系统残留失效代理；代理模式则跟随 net_guard 的实时代理设置
            proxies = None if self._is_proxy_mode() else {"http": None, "https": None}
            resp = session.request(
                method=method.upper(),
                url=url,
                params=params,
                headers=merged_headers,
                json=json_body,
                data=data,
                timeout=eff_timeout,
                proxies=proxies,
            )
            resp.raise_for_status()
            return resp

        last_exc: Optional[Exception] = None
        attempts = max(1, int(retries) + 1)
        for idx in range(attempts):
            try:
                return net_guard.retry_on_proxy_error(_do_request)
            except Exception as exc:
                last_exc = exc
                if idx + 1 < attempts:
                    time.sleep(min(0.6 * (idx + 1), 1.5))
        assert last_exc is not None
        raise last_exc

    def request_json(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        method: str = "GET",
        json_body: Any = None,
        data: Any = None,
        timeout: Optional[float] = None,
        retries: int = 1,
    ) -> Any:
        """发送 HTTP 请求并解析 JSON 响应。"""
        resp = self.request_raw(
            url,
            params=params,
            headers=headers,
            method=method,
            json_body=json_body,
            data=data,
            timeout=timeout,
            retries=retries,
        )
        return resp.json()

    def request_text(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
        timeout: Optional[float] = None,
        retries: int = 1,
    ) -> str:
        """发送 HTTP GET 请求并返回文本内容。"""
        resp = self.request_raw(
            url,
            params=params,
            headers=headers,
            method="GET",
            timeout=timeout,
            retries=retries,
        )
        if encoding:
            resp.encoding = encoding
        return resp.text

    def urlopen_text(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        encoding: str = "utf-8",
        timeout: Optional[float] = None,
    ) -> str:
        """通过 urllib.request.urlopen 获取文本，兼顾标准库拦截单测与代理协同。"""
        ensure_network_guard(max(self.timeout, 25.0))
        eff_timeout = float(timeout) if timeout is not None else self.timeout
        merged_headers = dict(_DEFAULT_HEADERS)
        if headers:
            merged_headers.update(headers)
        req = urllib.request.Request(url, headers=merged_headers)

        def _open() -> bytes:
            if self._is_proxy_mode() and hasattr(net_guard, "urlopen_with_optional_proxy"):
                with net_guard.urlopen_with_optional_proxy(req, timeout=eff_timeout) as resp:
                    return resp.read()
            with urllib.request.urlopen(req, timeout=eff_timeout) as resp:
                return resp.read()

        raw = net_guard.retry_on_proxy_error(_open)
        return raw.decode(encoding, errors="replace")


_DEFAULT_TRANSPORT = UnifiedTransport(timeout=DEFAULT_TIMEOUT)
_DEFAULT_BREAKER = SourceCircuitBreaker(failure_threshold=3, cooldown_seconds=120.0)


def get_transport() -> UnifiedTransport:
    """获取全局共享 UnifiedTransport 实例。"""
    return _DEFAULT_TRANSPORT


def get_circuit_breaker() -> SourceCircuitBreaker:
    """获取全局共享 SourceCircuitBreaker 实例。"""
    return _DEFAULT_BREAKER


def fetch_eastmoney_datacenter_raw(
    report_name: str,
    *,
    filter_expr: str = "",
    columns: str = "ALL",
    sort_columns: str = "",
    sort_types: str = "",
    page_number: int = 1,
    page_size: int = 500,
    source: str = "WEB",
    client: str = "WEB",
    timeout: Optional[float] = None,
    transport: Optional[UnifiedTransport] = None,
) -> Dict[str, Any]:
    """调用东方财富数据中心单页接口并返回原始 result 字典。"""
    client_tx = transport or get_transport()
    params: Dict[str, Any] = {
        "reportName": report_name,
        "columns": columns or "ALL",
        "pageNumber": int(page_number),
        "pageSize": int(page_size),
        "source": source,
        "client": client,
    }
    if filter_expr:
        params["filter"] = filter_expr
    if sort_columns:
        params["sortColumns"] = sort_columns
    if sort_types:
        params["sortTypes"] = sort_types

    payload = client_tx.request_json(
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        params=params,
        headers={"Referer": "https://data.eastmoney.com/"},
        timeout=timeout or DEFAULT_TIMEOUT,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"东财数据中心返回非 JSON 对象: {report_name}")
    # 东财接口 code=9201 通常表示无匹配数据而非网络故障
    code = payload.get("code")
    if payload.get("success") is False and code not in (0, 9201, None):
        msg = payload.get("message") or f"code={code}"
        raise RuntimeError(f"东财数据中心接口异常 ({report_name}): {msg}")
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def fetch_eastmoney_datacenter(
    report_name: str,
    *,
    filter_expr: str = "",
    columns: str = "ALL",
    sort_columns: str = "",
    sort_types: str = "",
    page_size: int = 500,
    max_pages: int = 20,
    source: str = "WEB",
    client: str = "WEB",
    timeout: Optional[float] = None,
    transport: Optional[UnifiedTransport] = None,
) -> List[Dict[str, Any]]:
    """自动分页拉取东方财富数据中心接口，返回合并后的记录列表。"""
    rows: List[Dict[str, Any]] = []
    for page in range(1, max(1, int(max_pages)) + 1):
        result = fetch_eastmoney_datacenter_raw(
            report_name,
            filter_expr=filter_expr,
            columns=columns,
            sort_columns=sort_columns,
            sort_types=sort_types,
            page_number=page,
            page_size=page_size,
            source=source,
            client=client,
            timeout=timeout,
            transport=transport,
        )
        data = result.get("data")
        if not isinstance(data, list) or not data:
            break
        rows.extend(item for item in data if isinstance(item, dict))
        total_pages = int(result.get("pages") or 1)
        if page >= total_pages or len(data) < page_size:
            break
    return rows
