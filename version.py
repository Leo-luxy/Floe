# version.py
# Floe 统一版本与渠道元数据单一真源

APP_NAME = "Floe"
APP_SLOGAN_ZH = "适合中国宝宝体质的 A 股选股软件"
APP_SLOGAN_EN = "A-Share Screener Tailored for CN Investors"
APP_DISPLAY_ZH = f"{APP_NAME} · {APP_SLOGAN_ZH}"
APP_DISPLAY_EN = f"{APP_NAME} · {APP_SLOGAN_EN}"
APP_VERSION = "2.0.2"
AUTHOR_EMAIL = "luleo856@gmail.com"

GITHUB_REPO = "Leo-luxy/Floe"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"

CLI_COMMAND = "floe"
HOMEBREW_TAP = "Leo-luxy/tap"
HOMEBREW_CASK = "floe"
NPM_PACKAGE = "@leo-luxy/floe"

RELEASE_CHANGELOG_ZH = """### Floe v2.0.2 更新内容
- **统一数据中心（`data_hub`）与全链路多源容灾**：全部 17 个数据采集、实时行情、全市场选股与板块入口统一收口至 `data_hub`，覆盖 35 项数据能力路由、18s/25s 网络超时守护、能力级源熔断隔离与全市场共享磁盘缓存。
- **彻底解决第六步采集与首轮抓取卡顿**：两融采集改用东财单股直查（`0.2s`，失败自动回退所属单边交易所）；分红/盈利预测/申万分类切换共享缓存，消除重复 5000+ 全表拉取与无意义随机等待。
- **免 V8 / 免积分多通道兜底**：前复权日线支持「新浪 → 东财 → 腾讯纯 JSON → Tushare」4 级自动切换；`mini-racer` 缺失时无感切换纯 JSON 通道；全市场选股 `step2` 在 Tushare 受限时自动回退腾讯同日批量网关。
- **跨平台桌面与网络体验加固**：内置跨平台 `certifi` CA 根证书、系统代理协同护盾、Windows 禁止弹窗闪烁（`CREATE_NO_WINDOW`）及防嵌套 GUI 重启，彻底修复桌面端联网与选股稳定性问题。
- **云端推理模型适配与研报质量加固**：修复云端 API 长响应被 3s 超时误杀及推理模型思考链耗尽 `max_tokens=8192` 导致报告为空的问题，补充思考超限自动压缩重试、季度数据校验与估值/空仓价格兜底。"""

RELEASE_CHANGELOG_EN = """### Floe v2.0.2 Release Highlights
- **Unified `data_hub` & Multi-Source Failover**: Consolidated all 17 collectors, quote endpoints, screener steps, and sector pipelines under `data_hub` with 35 registered capabilities, unified 18s/25s timeouts, per-capability circuit breakers, and atomic shared market caching.
- **Eliminated 6th-Step & First-Run Bottlenecks**: Margin history now uses single-stock datacenter queries (~0.2s) with single-exchange fallback; dividend, forecast, and Shenwan tables share TTL caches instead of re-fetching full-market tables per ticker.
- **V8-Free & Token-Resilient Fallbacks**: Adjusted K-line history routes across `Sina -> Eastmoney -> Tencent JSON -> Tushare`; screener `step2` seamlessly falls back to Tencent same-day batch quotes when Tushare quota/points are limited.
- **Cross-Platform Desktop & Network Hardening**: Bundled cross-platform `certifi` CA certificates, live proxy synergy (`net_guard`), Windows `CREATE_NO_WINDOW` + anti-nested-GUI guard, and restricted-permission portable fallback.
- **Cloud Reasoning LLM & Report Reliability**: Prevented 3s timeout truncation on long cloud LLM calls and removed the hard `max_tokens=8192` cap that starved reasoning models (`deepseek-flash` etc.), adding empty-body auto-retry, quarterly freshness rules, and valuation/flat-position price fallbacks."""
