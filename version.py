# version.py
# Floe 统一版本与渠道元数据单一真源

APP_NAME = "Floe"
APP_SLOGAN_ZH = "适合中国宝宝体质的 A 股选股软件"
APP_SLOGAN_EN = "A-Share Screener Tailored for CN Investors"
APP_DISPLAY_ZH = f"{APP_NAME} · {APP_SLOGAN_ZH}"
APP_DISPLAY_EN = f"{APP_NAME} · {APP_SLOGAN_EN}"
APP_VERSION = "2.1.0"
AUTHOR_EMAIL = "luleo856@gmail.com"

GITHUB_REPO = "Leo-luxy/Floe"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"

CLI_COMMAND = "floe"
HOMEBREW_TAP = "Leo-luxy/tap"
HOMEBREW_CASK = "floe"
NPM_PACKAGE = "@leo-luxy/floe"

RELEASE_CHANGELOG_ZH = """### Floe v2.1.0 更新内容
- **全局单任务运行互斥保护（前后端协同防并发冲突）**：在 `api/common.py` 引入全局活跃任务槽锁（`try_acquire_active_task` / `get_active_task_info`）与 `/api/active_task` 实时状态端点，统一覆盖市场选股、策略回测、快速研判、完整五维分析、板块分析/采集与系统运维数据/脚本执行；同时为 `web_ui.py` 与 `floe_app.py --web` 启用 `threaded=True`，防止同步运维操作阻塞状态轮询。
- **动态运行态按钮与冲突进度实时弹窗**：当前正在运行任务的启动按钮自动切换为旋转加载态并显示对应任务名称（如「正在进行市场选股」「正在进行策略回测」等）；点击其他任意「开始任务」按钮时即时弹出实时监控弹窗，展示正在运行的任务、百分比进度条、最新步骤日志与一键跳转入口，刷新页面后可自动恢复状态与轮询。
- **修复 Homebrew Cask 架构声明被哈希更新脚本误覆盖的问题**：收紧 `packaging/scripts/update_cask_sha.py` 正则表达式仅匹配 `sha256` 区块并恢复 `floe.rb` 的 `arch arm: "arm64", intel: "x64"`，确保 macOS Homebrew 双架构分发链接正确。"""

RELEASE_CHANGELOG_EN = """### Floe v2.1.0 Release Highlights
- **Global Single-Task Execution Guard**: Added a thread-safe global active-task coordinator (`try_acquire_active_task` / `get_active_task_info`) in `api/common.py` and `GET /api/active_task` across market screening, backtesting, quick/full stock AI, sector AI/collection, and ops scripts; enabled `threaded=True` on `web_ui.py` and `floe_app.py --web` so status polling remains responsive during synchronous ops commands.
- **Dynamic Running Button State & Conflict Progress Modal**: The active task's start button transitions to a loading state showing the running task name, while clicking any other task button opens a live modal displaying the active task, progress bar, latest step output, and a quick-jump button (auto-restoring after page refresh).
- **Fixed Homebrew Cask `arch` Mapping**: Restricted `packaging/scripts/update_cask_sha.py` regex replacement to the `sha256` block and restored `arch arm: "arm64", intel: "x64"` in `floe.rb` for macOS Homebrew distribution."""
