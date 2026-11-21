# version.py
# Floe 统一版本与渠道元数据单一真源

APP_NAME = "Floe"
APP_SLOGAN_ZH = "适合中国宝宝体质的 A 股选股软件"
APP_SLOGAN_EN = "A-Share Screener Tailored for CN Investors"
APP_DISPLAY_ZH = f"{APP_NAME} · {APP_SLOGAN_ZH}"
APP_DISPLAY_EN = f"{APP_NAME} · {APP_SLOGAN_EN}"
APP_VERSION = "2.0.1"
AUTHOR_EMAIL = "luleo856@gmail.com"

GITHUB_REPO = "Leo-luxy/Floe"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"

CLI_COMMAND = "floe"
HOMEBREW_TAP = "Leo-luxy/tap"
HOMEBREW_CASK = "floe"
NPM_PACKAGE = "@leo-luxy/floe"

RELEASE_CHANGELOG_ZH = """### Floe v2.0.1 更新内容
- **修复桌面安装包 HTTPS 证书校验报错**：打包环境内置并自动挂载跨平台 `certifi` 与系统 CA 根证书束，彻底解决下载安装的桌面端在 API 连接验证、行情探测与检查更新时报 `CERTIFICATE_VERIFY_FAILED` 的问题。
- **境外检查更新与云端 API 局部代理回退**：在保持 A 股国内数据源 100% 纯净直连的前提下，若检查 GitHub 更新或访问境外 API 直连超时且检测到本机系统代理在线，自动单次局部复用代理隧道。
- **Windows 受限权限自动便携回退**：当 `%APPDATA%\\Floe` 被受控文件夹访问或第三方安全软件拦截时，自动降级至程序同级 `Floe_Data` 目录并收拢缓存，免管理员零配置启动。
- **2.0 全新桌面量化工作台**：支持「01 市场选股 → 02 关注股票池 → 03 策略回测监控」三步闭环、三位小数（`0.001`）FIFO 买卖台账、红涨/绿跌双企鹅图标与中英双语联动。"""

RELEASE_CHANGELOG_EN = """### Floe v2.0.1 Release Highlights
- **Fixed Packaged Desktop SSL Certificate Verification**: Automatically bundles and mounts cross-platform `certifi` + OS root CA certificates at startup, resolving `CERTIFICATE_VERIFY_FAILED` on API verification, market feed checks, and update checks in downloaded desktop builds.
- **Smart Local Proxy Fallback for GitHub & Overseas APIs**: Keeps all domestic A-share market feeds 100% direct while automatically retrying via active system proxy tunnels when GitHub release checks or overseas LLM endpoints time out.
- **Windows Restricted-Permission Portable Fallback**: Automatically falls back to a side-by-side `Floe_Data` portable directory when `%APPDATA%\\Floe` is blocked by Controlled Folder Access or security suites.
- **Floe 2.0 Quant Workbench**: Standalone native desktop app, 3-step `Screener → Watchlist → Backtest` pipeline, 3-decimal (`0.001`) FIFO ledger, Bull/Bear penguin icons, and Chinese/English bilingual sync."""
