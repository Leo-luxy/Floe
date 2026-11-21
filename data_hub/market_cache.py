# -*- coding: utf-8 -*-
"""
全市场数据与慢表本地共享缓存（atomic TTL cache）
避免批处理或连续分析多只个股时重复拉取 5000+ 行全市场表（如分红、盈利预测、申万成分、行业估值等）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pandas as pd

import app_paths

_CACHE_LOCKS: Dict[str, threading.Lock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


def _get_lock(key: str) -> threading.Lock:
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _CACHE_LOCKS[key] = lock
        return lock


def get_cache_dir() -> Path:
    """获取持久化缓存根目录，确保始终落在当前运行态的数据目录下。"""
    data_dir = Path(app_paths.get_data_dir())
    cache_dir = data_dir / ".market_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _sanitize_key(key: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", str(key).strip())
    if not safe or len(safe) > 120:
        digest = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:16]
        safe = f"{safe[:80]}_{digest}" if safe else digest
    return safe


def _meta_path(payload_path: Path) -> Path:
    return payload_path.with_suffix(payload_path.suffix + ".meta.json")


def _is_fresh(payload_path: Path, ttl_seconds: float, same_day_only: bool = False) -> bool:
    if not payload_path.exists() or payload_path.stat().st_size == 0:
        return False
    meta_file = _meta_path(payload_path)
    created_ts: Optional[float] = None
    created_date: Optional[str] = None
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            created_ts = float(meta.get("created_ts", 0.0))
            created_date = str(meta.get("created_date", "") or "")
        except Exception:
            created_ts = None
    if created_ts is None:
        created_ts = payload_path.stat().st_mtime
        created_date = datetime.fromtimestamp(created_ts).strftime("%Y-%m-%d")

    if same_day_only:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if created_date != today_str:
            return False

    return (time.time() - created_ts) <= max(0.0, float(ttl_seconds))


def _write_meta(payload_path: Path, key: str, extra: Optional[Dict[str, Any]] = None) -> None:
    meta_file = _meta_path(payload_path)
    now = time.time()
    meta = {
        "key": key,
        "created_ts": now,
        "created_date": datetime.fromtimestamp(now).strftime("%Y-%m-%d"),
    }
    if extra:
        meta.update(extra)
    tmp_meta = meta_file.with_suffix(".tmp")
    tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_meta, meta_file)


def _atomic_write_text(target: Path, text: str) -> None:
    tmp = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def get_or_fetch_df(
    key: str,
    fetcher: Callable[[], pd.DataFrame],
    *,
    ttl_seconds: float = 21600.0,
    same_day_only: bool = False,
    allow_empty: bool = False,
    dtype: Any = str,
) -> pd.DataFrame:
    """读取或原子刷新 DataFrame 级全市场缓存。"""
    safe_key = _sanitize_key(key)
    lock = _get_lock(f"df:{safe_key}")
    with lock:
        cache_file = get_cache_dir() / f"{safe_key}.csv"
        if _is_fresh(cache_file, ttl_seconds, same_day_only=same_day_only):
            try:
                df = pd.read_csv(cache_file, dtype=dtype)
                if allow_empty or not df.empty:
                    return df
            except Exception:
                pass

        df = fetcher()
        if not isinstance(df, pd.DataFrame):
            raise TypeError(f"缓存拉取器 {key} 未返回 DataFrame")
        if df.empty and not allow_empty:
            return df

        tmp = cache_file.with_name(f"{cache_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, cache_file)
        _write_meta(cache_file, key, {"rows": int(len(df))})
        return df


def get_or_fetch_json(
    key: str,
    fetcher: Callable[[], Any],
    *,
    ttl_seconds: float = 21600.0,
    same_day_only: bool = False,
    allow_empty: bool = False,
) -> Any:
    """读取或原子刷新 JSON 级全市场/元数据缓存。"""
    safe_key = _sanitize_key(key)
    lock = _get_lock(f"json:{safe_key}")
    with lock:
        cache_file = get_cache_dir() / f"{safe_key}.json"
        if _is_fresh(cache_file, ttl_seconds, same_day_only=same_day_only):
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if allow_empty or data:
                    return data
            except Exception:
                pass

        data = fetcher()
        if not data and not allow_empty:
            return data

        _atomic_write_text(cache_file, json.dumps(data, ensure_ascii=False, indent=2))
        _write_meta(cache_file, key)
        return data


def clear_cache(key_prefix: Optional[str] = None) -> int:
    """清理缓存目录下指定前缀或全部缓存文件，返回删除文件数。"""
    cache_dir = get_cache_dir()
    removed = 0
    prefix_safe = _sanitize_key(key_prefix) if key_prefix else ""
    for item in cache_dir.iterdir():
        if not item.is_file():
            continue
        if prefix_safe and not item.name.startswith(prefix_safe):
            continue
        try:
            item.unlink()
            removed += 1
        except Exception:
            pass
    return removed
