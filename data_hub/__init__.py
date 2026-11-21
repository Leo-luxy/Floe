# -*- coding: utf-8 -*-
"""
统一数据中心（data_hub）
为全市场选股、个股分析、板块扫描、实时行情与持仓估值提供统一的能力路由、
超时保护、源级熔断、多源自动降级与全市场共享缓存。
"""

from data_hub.registry import (  # noqa: F401
    CAPABILITY_REGISTRY,
    DataHubError,
    fetch,
    fetch_with_source,
    get_provider_chain,
    list_capabilities,
    register_provider,
)
from data_hub.transport import (  # noqa: F401
    DEFAULT_TIMEOUT,
    SourceCircuitBreaker,
    UnifiedTransport,
    get_circuit_breaker,
    get_transport,
)
from data_hub.market_cache import (  # noqa: F401
    clear_cache,
    get_or_fetch_df,
    get_or_fetch_json,
)

__all__ = [
    "CAPABILITY_REGISTRY",
    "DEFAULT_TIMEOUT",
    "DataHubError",
    "SourceCircuitBreaker",
    "UnifiedTransport",
    "clear_cache",
    "fetch",
    "fetch_with_source",
    "get_circuit_breaker",
    "get_or_fetch_df",
    "get_or_fetch_json",
    "get_provider_chain",
    "get_transport",
    "list_capabilities",
    "register_provider",
]
