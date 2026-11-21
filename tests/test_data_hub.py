# -*- coding: utf-8 -*-
"""
data_hub 统一数据中心回归测试与静态门禁校验
覆盖：能力路由与主备切换、能力级熔断与冷却恢复、全市场共享缓存、单股两融 9 列映射、
动态机构持股报告期、前复权多源降级，以及历史坏味道静态审计。
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import data_hub
from data_hub import market_cache
from data_hub.providers import eastmoney as em_prov
from data_hub.transport import SourceCircuitBreaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DataHubRoutingAndBreakerTest(unittest.TestCase):
    def setUp(self):
        self.breaker = data_hub.get_circuit_breaker()
        self.breaker.reset()
        self._saved_registry = {k: list(v) for k, v in data_hub.CAPABILITY_REGISTRY.items()}

    def tearDown(self):
        data_hub.CAPABILITY_REGISTRY.clear()
        data_hub.CAPABILITY_REGISTRY.update(self._saved_registry)
        self.breaker.reset()

    def test_required_capabilities_registered(self):
        caps = data_hub.list_capabilities()
        for required in (
            "stock_qfq_daily",
            "stock_realtime_quote",
            "stock_margin",
            "stock_ex_dividend",
            "stock_profit_forecast_em",
            "stock_profit_forecast_ths",
            "stock_org_holdings",
            "stock_north_holdings",
            "stock_shareholder_num",
            "stock_shareholders",
            "stock_company_basic",
            "stock_financial_report",
            "stock_em_financial",
            "stock_f10_report",
            "stock_valuation",
            "stock_fund_flow",
            "shenwan_levels",
            "broad_index_daily",
            "sector_board_list",
        ):
            self.assertIn(required, caps, f"缺少核心能力注册: {required}")
            self.assertGreaterEqual(len(caps[required]), 1)

        # 前复权与实时行情必须包含多源兜底链
        self.assertGreaterEqual(len(caps["stock_qfq_daily"]), 3)
        self.assertEqual(caps["stock_realtime_quote"], ["eastmoney", "tencent", "sina"])
        self.assertEqual(caps["stock_margin"], ["eastmoney", "exchange"])

    def test_primary_fails_switches_to_fallback_and_raises_when_all_fail(self):
        calls = []
        switch_events = []

        def primary_bad(symbol):
            calls.append("primary")
            raise ConnectionError("主源超时")

        def backup_ok(symbol):
            calls.append("backup")
            return pd.DataFrame([{"date": "2026-11-20", "close": 10.5}])

        data_hub.register_provider("test_cap", "primary", primary_bad, priority=0)
        data_hub.register_provider("test_cap", "backup", backup_ok, priority=1)

        df, used = data_hub.fetch_with_source(
            "test_cap",
            symbol="000001.SZ",
            on_fallback=lambda s, n, e: switch_events.append((s, n)),
        )
        self.assertEqual(used, "backup")
        self.assertEqual(len(df), 1)
        self.assertEqual(calls, ["primary", "backup"])
        self.assertEqual(switch_events, [("primary", "backup")])

        # 全失败必须抛出 DataHubError 并带出每个源的错误上下文
        data_hub.register_provider("test_cap", "backup", lambda symbol: (_ for _ in ()).throw(RuntimeError("备源也挂")), priority=1)
        with self.assertRaises(data_hub.DataHubError) as ctx:
            data_hub.fetch("test_cap", symbol="000001.SZ")
        self.assertIn("primary", ctx.exception.errors)
        self.assertIn("backup", ctx.exception.errors)

    def test_circuit_breaker_capability_isolation_and_recovery(self):
        primary_calls = []

        def broken_a(**kw):
            primary_calls.append("broken_a")
            raise TimeoutError("sub-api timeout")

        def backup_a(**kw):
            return {"ok": True}

        def healthy_b(**kw):
            primary_calls.append("healthy_b")
            return {"ok": "b"}

        data_hub.register_provider("cap_a", "eastmoney_test", broken_a, priority=0)
        data_hub.register_provider("cap_a", "backup_test", backup_a, priority=1)
        data_hub.register_provider("cap_b", "eastmoney_test", healthy_b, priority=0)

        # 连续失败 3 次触发 cap_a:eastmoney_test 熔断
        for _ in range(3):
            res = data_hub.fetch("cap_a")
            self.assertEqual(res, {"ok": True})
        self.assertEqual(primary_calls.count("broken_a"), 3)

        # 第 4 次调用 cap_a 应直接跳过 broken_a
        data_hub.fetch("cap_a")
        self.assertEqual(primary_calls.count("broken_a"), 3)

        # 同源的另一个能力 cap_b 不受 cap_a 熔断牵连（能力级隔离）
        res_b = data_hub.fetch("cap_b")
        self.assertEqual(res_b, {"ok": "b"})
        self.assertEqual(primary_calls.count("healthy_b"), 1)

        # 验证 SourceCircuitBreaker 冷却期到期自动恢复半开
        local_breaker = SourceCircuitBreaker(failure_threshold=2, cooldown_seconds=1.0)
        local_breaker.record_failure("src_x", RuntimeError("err1"))
        self.assertFalse(local_breaker.is_open("src_x"))
        local_breaker.record_failure("src_x", RuntimeError("err2"))
        self.assertTrue(local_breaker.is_open("src_x"))
        # 模拟冷却期过期
        local_breaker._opened_at["src_x"] -= 2.0
        self.assertFalse(local_breaker.is_open("src_x"))


class MarketCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gp_hub_cache_")
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)
        self._orig_get_cache_dir = market_cache.get_cache_dir
        market_cache.get_cache_dir = lambda: Path(self.tmp_dir)

    def tearDown(self):
        market_cache.get_cache_dir = self._orig_get_cache_dir

    def test_df_cache_hit_miss_and_numeric_dtype(self):
        fetches = []

        def build_df():
            fetches.append(1)
            return pd.DataFrame([{"报告日": "20260331", "营业收入": 1234.56, "净利润": 100.5}])

        df1 = market_cache.get_or_fetch_df(
            "test_fin_profit",
            build_df,
            ttl_seconds=60.0,
            dtype={"报告日": str},
        )
        self.assertEqual(len(fetches), 1)
        self.assertEqual(df1.iloc[0]["报告日"], "20260331")

        # 第二次命中磁盘缓存且保留数值列精度，支持直接算术运算
        df2 = market_cache.get_or_fetch_df(
            "test_fin_profit",
            build_df,
            ttl_seconds=60.0,
            dtype={"报告日": str},
        )
        self.assertEqual(len(fetches), 1)
        self.assertGreater(float(df2.iloc[0]["营业收入"]), 1000.0)
        self.assertIsInstance(df2.iloc[0]["报告日"], str)

        # 过期后重新拉取
        meta_path = Path(self.tmp_dir) / "test_fin_profit.csv.meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["created_ts"] = time.time() - 120.0
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        market_cache.get_or_fetch_df("test_fin_profit", build_df, ttl_seconds=60.0, dtype={"报告日": str})
        self.assertEqual(len(fetches), 2)


class MarginAndCollectorsBehaviorTest(unittest.TestCase):
    def setUp(self):
        data_hub.get_circuit_breaker().reset()

    def tearDown(self):
        data_hub.get_circuit_breaker().reset()

    def test_eastmoney_single_stock_margin_9_columns_and_non_margin_empty(self):
        sample_rows = [
            {
                "DATE": "2026-11-18 00:00:00",
                "SCODE": "002668",
                "SECNAME": "TCL智家",
                "RZMRE": 1000.0,
                "RZYE": 20000.0,
                "RQMCL": 100.0,
                "RQYL": 200.0,
                "RQYE": 1800.0,
                "RZRQYE": 21800.0,
            }
        ]
        with mock.patch("data_hub.providers.eastmoney.fetch_eastmoney_datacenter", return_value=sample_rows):
            df = data_hub.fetch("stock_margin", ticker="002668.SZ", start_date="20261101", end_date="20261120")
        self.assertEqual(
            list(df.columns),
            ["证券代码", "证券简称", "融资买入额", "融资余额", "融券卖出量", "融券余量", "融券余额", "融资融券余额", "date"],
        )
        self.assertEqual(df.iloc[0]["date"], "20261118")
        self.assertEqual(float(df.iloc[0]["融资余额"]), 20000.0)

        # 非两融标的（东财正常返回空列表）不得触发慢速交易所回退或熔断
        exchange_called = []
        with mock.patch("data_hub.providers.eastmoney.fetch_eastmoney_datacenter", return_value=[]), \
             mock.patch("data_hub.providers.exchange.fetch_stock_margin_exchange", side_effect=lambda *a, **kw: exchange_called.append(1)):
            df_empty, src = data_hub.fetch_with_source("stock_margin", ticker="300999.SZ", start_date="20261101", end_date="20261120")
        self.assertTrue(df_empty.empty)
        self.assertEqual(src, "eastmoney")
        self.assertEqual(exchange_called, [])

    def test_batch_margin_collector_uses_data_hub_in_normal_mode(self):
        import batch_margin_collector as bmc

        tmp_data = tempfile.mkdtemp(prefix="gp_bmc_hub_")
        self.addCleanup(shutil.rmtree, tmp_data, True)
        with mock.patch.object(bmc, "DATA_DIR", tmp_data), \
             mock.patch("data_hub.providers.eastmoney.fetch_eastmoney_datacenter", return_value=[]):
            summary = bmc.batch_collect_margin_data("20261110", "20261120", tickers=["300888.SZ"])
        self.assertEqual(summary["not_applicable"], ["300888.SZ"])
        self.assertTrue(os.path.isfile(os.path.join(tmp_data, "300888.SZ", "300888.SZ_margin_na.json")))

    def test_org_hold_dynamic_report_date_and_data_dir(self):
        import org_hold_collector as ohc

        tmp_data = tempfile.mkdtemp(prefix="gp_org_hub_")
        self.addCleanup(shutil.rmtree, tmp_data, True)
        sample_df = pd.DataFrame([
            {
                "ORG_TYPE": "01",
                "SECUCODE": "002668.SZ",
                "REPORT_DATE": "2026-09-30 00:00:00",
                "HOLDER_CODE": "110011",
                "HOLDER_NAME": "测试基金A",
                "TOTAL_SHARES": 100000,
                "HOLD_VALUE": 900000,
            }
        ])
        with mock.patch.object(ohc, "DATA_DIR", tmp_data), \
             mock.patch("data_hub.fetch", return_value=sample_df) as m_fetch:
            save_path = os.path.join(tmp_data, "002668.SZ", "002668.SZ_institutional_holdings.csv")
            records = ohc.fetch_org_hold_detail("002668.SZ", report_date=None, save_path=save_path)
        self.assertEqual(len(records), 1)
        m_fetch.assert_called_once_with("stock_org_holdings", ticker="002668.SZ", report_date=None)
        self.assertTrue(os.path.isfile(save_path))

    def test_data_collector_routes_through_data_hub_on_primary_failure(self):
        import data_collector as dc

        expected_df = pd.DataFrame([
            {
                "date": pd.to_datetime("2026-11-20").date(),
                "open": 10.0,
                "high": 10.5,
                "low": 9.9,
                "close": 10.4,
                "volume": 100000.0,
                "amount": 1020000.0,
                "outstanding_share": 10000000.0,
                "turnover": 0.01,
            }
        ])
        with mock.patch("data_hub.fetch", return_value=expected_df) as m_fetch:
            df = dc._fetch_qfq_history("sz002668", "20261101", "20261120")
        self.assertEqual(len(df), 1)
        m_fetch.assert_called_once()
        self.assertEqual(m_fetch.call_args[0][0], "stock_qfq_daily")


class StaticHygieneAuditTest(unittest.TestCase):
    def test_no_private_proxy_override_in_sector_modules(self):
        sector_collector = (PROJECT_ROOT / "sector_data_collector.py").read_text(encoding="utf-8")
        self.assertNotIn("def _disable_system_proxy", sector_collector)
        self.assertNotIn("urllib.request.getproxies = lambda: {}", sector_collector)

        sector_api = (PROJECT_ROOT / "api" / "sector.py").read_text(encoding="utf-8")
        self.assertNotIn("urllib.request.getproxies = lambda: {}", sector_api)

    def test_no_hardcoded_relative_data_paths_or_stale_report_date(self):
        for fname in ("org_hold_collector.py", "north_holdings.py", "shareholders_collector.py"):
            content = (PROJECT_ROOT / fname).read_text(encoding="utf-8")
            self.assertNotIn('f"data/{ticker}', content, f"{fname} 仍含硬编码相对路径")
            self.assertNotIn("f'data/{ticker}", content, f"{fname} 仍含硬编码相对路径")

        org_content = (PROJECT_ROOT / "org_hold_collector.py").read_text(encoding="utf-8")
        self.assertNotIn("default='2025-12-31'", org_content)
        self.assertNotIn('default="2025-12-31"', org_content)

    def test_floe_spec_includes_data_hub(self):
        spec_text = (PROJECT_ROOT / "packaging" / "pyinstaller" / "floe.spec").read_text(encoding="utf-8")
        self.assertIn("data_hub", spec_text)
        self.assertIn("collect_submodules('data_hub')", spec_text)


if __name__ == "__main__":
    unittest.main()
