# version.py
# Floe 统一版本与渠道元数据单一真源

APP_NAME = "Floe"
APP_SLOGAN_ZH = "适合中国宝宝体质的 A 股选股软件"
APP_SLOGAN_EN = "A-Share Screener Tailored for CN Investors"
APP_DISPLAY_ZH = f"{APP_NAME} · {APP_SLOGAN_ZH}"
APP_DISPLAY_EN = f"{APP_NAME} · {APP_SLOGAN_EN}"
APP_VERSION = "2.0.0"
AUTHOR_EMAIL = "luleo856@gmail.com"

GITHUB_REPO = "Leo-luxy/Floe"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"

CLI_COMMAND = "floe"
HOMEBREW_TAP = "Leo-luxy/tap"
HOMEBREW_CASK = "floe"
NPM_PACKAGE = "@leo-luxy/floe"

RELEASE_CHANGELOG_ZH = """### Floe v2.0.0 更新内容
- **全新跨平台桌面软件架构**：升级为独立原生窗口应用（兼容 macOS / Windows / Linux），自带顶部系统菜单栏极简小企鹅常驻快捷入口，并支持端口冲突自动顺延。
- **核心量化工作流重塑**：聚焦「01 市场选股（仅展示当日新入场标的）→ 02 关注股票池 → 03 策略回测与监控（默认简化版，按本机首次入选日起算累计绩效）」三步闭环。
- **买卖记录台账与逐手收益核算**：成交均价支持三位小数（0.001），按先进先出（FIFO）核算历史已实现盈亏与最新现价浮动盈亏，支持展开查看每一手交易明细。
- **个性化与国际化设置中心**：内置「红涨瞭望 / 绿跌闭眼」双款企鹅图标切换、中英双语界面与 AI 研报输出语言联动、两步式 API 模型验证选型、系统权限体检及数据一键备份恢复。"""

RELEASE_CHANGELOG_EN = """### Floe v2.0.0 Release Highlights
- **Native Cross-Platform Desktop App**: Runs in a standalone native window on macOS, Windows, and Linux with menu-bar/tray penguin quick controls and automatic port fallback.
- **Streamlined Core Quant Workflow**: Focused 3-step pipeline: `01 Market Screener` (today's new entries only) → `02 Watchlist Pool` → `03 Backtest & Monitor` (Simple MA5>MA20 preset by default, tracking cohort returns since first local selection).
- **FIFO Trading Ledger**: 3-decimal trade fill precision (`0.001`), real-time unrealized + realized P&L calculation, and expandable lot-by-lot breakdown.
- **Settings, Dual Icons & Bilingual Engine**: Switchable Bull/Bear penguin icons, instant Chinese/English UI + AI report language sync, 2-step API model verification, permission diagnostics, and `.zip` backup/restore."""
