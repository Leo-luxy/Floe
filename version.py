# version.py
# Floe 统一版本与渠道元数据单一真源

APP_NAME = "Floe"
APP_SLOGAN_ZH = "适合中国宝宝体质的 A 股选股软件"
APP_SLOGAN_EN = "A-Share Screener Tailored for CN Investors"
APP_DISPLAY_ZH = f"{APP_NAME} · {APP_SLOGAN_ZH}"
APP_DISPLAY_EN = f"{APP_NAME} · {APP_SLOGAN_EN}"
APP_VERSION = "2.0.3"
AUTHOR_EMAIL = "luleo856@gmail.com"

GITHUB_REPO = "Leo-luxy/Floe"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"

CLI_COMMAND = "floe"
HOMEBREW_TAP = "Leo-luxy/tap"
HOMEBREW_CASK = "floe"
NPM_PACKAGE = "@leo-luxy/floe"

RELEASE_CHANGELOG_ZH = """### Floe v2.0.3 更新内容
- **修复 Windows 版市场选股中文乱码与 `batch_backtest_filter.py` 返回码 3 崩溃**：在 `floe_app.py`（含 `--run-script` 内部子脚本调度）、`app_paths.py` 及各采集/选股脚本入口全局强制将 `sys.stdout` / `sys.stderr` 重配置为 `UTF-8 (errors='replace')`，彻底解决 Windows `cp936/GBK` 控制台因无法编码替换符 `\ufffd` 或状态图标导致批筛预检第 1 只股票即异常终止的问题。
- **全链路子进程管道双编码安全解码**：统一为市场选股、完整/快速分析、策略回测、板块分析与日更数据检查 (`check_data_updates.py`) 的实时管道读取接入「UTF-8 优先、失败自动回退 `GB18030`」解码机制，并在 Windows 全部子进程调用中启用 `CREATE_NO_WINDOW`。
- **加固打包态 `config.py` 模板兜底**：在 `packaging/pyinstaller/floe.spec` 与 `app_paths.activate_runtime_paths()` 中增加缺失 `config.py` 时自动由 `config.example.py` 初始化的保护，确保所有构建环境生成的安装包开箱即用。"""

RELEASE_CHANGELOG_EN = """### Floe v2.0.3 Release Highlights
- **Fixed Windows Screener Mojibake & `batch_backtest_filter.py` Exit Code 3 Crash**: Enforced `UTF-8 (errors='replace')` on `sys.stdout` / `sys.stderr` at startup across `floe_app.py` (including `--run-script` subprocesses), `app_paths.py`, and screener/collector scripts, preventing Windows `cp936/GBK` consoles from raising `UnicodeEncodeError` on `\ufffd` or status symbols during batch preflight.
- **Dual-Encoding Subprocess Stream Decoding**: Upgraded real-time pipe readers across market screening, full/quick analysis, strategy backtest, sector analysis, and `check_data_updates.py` to decode `UTF-8` with automatic `GB18030` fallback, while ensuring `CREATE_NO_WINDOW` across all Windows subprocess calls.
- **Packaged `config.py` Auto-Fallback**: Added automatic fallback initialization from `config.example.py` in both `packaging/pyinstaller/floe.spec` and `app_paths.activate_runtime_paths()` for clean build environments."""
