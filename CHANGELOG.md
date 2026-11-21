# v2.0.2 — 统一数据中心 `data_hub` · 全链路多源容灾 · 跨平台桌面与选股稳定性加固

> 🛠️ 核心主题：**统一数据中心 `data_hub` 架构重构与跨平台桌面端（macOS / Windows / Linux）全链路选股、AI 研判、权限隔离及网络连通性加固**。

---

## 🆕 新增

- **统一数据中心 `data_hub`（35 项能力路由 + 能力级源熔断 + 共享磁盘缓存）**：
  - 将全项目 17 个数据采集、实时行情、全市场选股与板块入口全部收口至 `data_hub`，统一由 6 大底层适配器（`eastmoney` / `tencent` / `sina` / `ths` / `exchange` / `tushare`）按优先级链调度，内置 `UnifiedTransport`（18s HTTP / 25s 全局 socket 超时、`net_guard` 协同护盾、拟真浏览器头）。
  - **能力级 `SourceCircuitBreaker`**：单个子接口连续失败 3 次后进入 120s 冷却自动跳过并切换备选源，且按能力粒度隔离，避免冷门接口故障误伤同源核心行情通道。
  - **`market_cache` 原子级共享磁盘缓存**：对历史分红（`6h`）、东财盈利预测（`6h`）、板块列表与成分股（`1h~6h`）、申万一/二/三级分类（`7d`）及三大财务报表（`600s`）启用原子缓存，消除多股分析时重复下载全市场大表与 `stock_company_info_collector` / `financial_indicators_collector` 双份重拉。
- **全链路多源降级与单股极速采集**：
  - **融资融券**：`batch_margin_collector.py` 优先使用东财单股直查（`0.2s` 返回 9 列完整历史，非两融标的自动记录 7 天 `_margin_na.json` 跳过标记），失败时仅按股票所属单一交易所按日回溯，彻底消除五维分析第 6 步卡顿。
  - **前复权与行情/基本面**：前复权日线支持「新浪 → 东财 → 腾讯纯 JSON 分片 → Tushare」4 级自动切换；估值支持「东财 → 乐咕」；主股东支持「新浪 → 东财 F10」；资金流支持「akshare → 东财 `push2his` 直连」；板块列表/日线支持「东财 → 同花顺」；机构持股 `org_hold_collector.py` 动态探测最新可用报告期并移除硬编码相对路径。
  - **分析子进程合并**：五维完整分析与详细面板将 5 次串行 `eastmoney_fetcher.py` 子进程合并为单次 `--type all`。

---

## 🐛 修复

- **选股 `step2` 免费 Tushare 账号同日全集自动补齐**：积分不足或频次受限时自动经公开批量行情网关（约 `0.5s`）补齐同日基础指标，并严格校验 `trade_date` 与 100% 沪深代码覆盖。
- **选股日志保留与失败状态收敛**：修复 `api/stock_selection.py` 子进程输出脱离与失败后状态框残留；支持失败原因实时展示。
- **打包态只读应用包路径隔离**：修复 `Process/` 决策模块、`shenwan_config/`、`api/common.py` 与 `data_collector.py` 读取或写入包内相对路径的问题，全部收归用户可写数据目录。
- **防后台子进程弹窗重启与静默执行**：冻结态统一走 `--run-script` + `FLOE_SUBPROCESS=1` 防嵌套 GUI 守卫，Windows 启用 `CREATE_NO_WINDOW` 与 UTF-8 管道编码。
- **修复 `mini-racer` 依赖冲突与无 V8 兜底**：`requirements.txt` 与打包工作流由 `py_mini_racer` 修正为 `mini-racer>=0.12.4`，并支持无 V8 时无感切换纯 JSON 前复权通道。
- **日更超限防挂起**：全采集脚本启用 25s socket 超时与 240s 命令树超时终止（Windows 使用 `taskkill /F /T`），实时透传子进程进度。
- **修复云端 DeepSeek API 长响应 3 秒误杀超时与误报检查 Ollama**：修复本机存在存活代理端口时 `net_guard.urlopen_with_optional_proxy` 将大模型 `180s` 对话超时误截断为 `3s` 及 HTTPS 显式隧道协议错误；全量分析器按实际后端动态打印日志与精准错误提示，不再在云端 API 模式下误报「请检查Ollama服务」。
- **修复推理模型思考链耗尽 `max_tokens=8192` 导致分析报告为空**：`call_openai_compatible_chat` 不再对常规研报分析强行截断 `max_tokens=8192`（留空以适配 `deepseek-flash` 等带思考链推理模型的原生输出配额，并兼容强制要求 `max_tokens` 网关的 HTTP 400 回退），新增思考超限空正文自愈重试与显式报错兜底，同步修复估值分析未读取 `_company_basic.json` 与两层决策空仓时当前价显示 `0.00` 等问题。
- **修复股东/机构/北向季度数据被按 5 交易日误判过期**：`shareholder_num`、`shareholder`、`institutional`、`north_holdings` 改按报告季度（`kind='quarter'`, 滞后 0 季度）核验，最新季报与季中户数披露不再误判失效；综合分析实时股价接入 `data_hub`，申万成分上游列数漂移时温和降级。

---

## ✅ 质量

- 回归单元测试扩充至 **338 项**（全部通过），新增 `tests/test_data_hub.py`、`tests/test_daily_update_stall.py` 与云端 API 长超时/思考链配额防截断专项校验。

---

# v2.0.1 — 桌面安装包 HTTPS 证书链修复 · 境外检查更新局部代理回退 · Windows 便携回退

> 🛠️ 核心主题：**跨平台桌面安装包开箱即用连通性与权限容错补强**。解决云端构建桌面包在用户设备上丢失 OpenSSL 默认根证书路径导致的 HTTPS 报错，并完善受限网络与受控目录环境下的零配置启动体验。

---

## 🐛 修复

- **桌面安装包 HTTPS 根证书链自动挂载 (`app_paths.py`, `packaging/pyinstaller/floe.spec`)**：修复 GitHub Actions 云端构建的桌面二进制因 `libcrypto` 硬编码构建机证书路径（下载至用户设备后路径不存在）导致 API 连接验证、检查更新及实时行情探测报 `[SSL: CERTIFICATE_VERIFY_FAILED]` / `URLError` 的问题；现打包内置 `certifi` 根证书束并在启动时自动注入 `SSL_CERT_FILE`、`REQUESTS_CA_BUNDLE` 及 `ssl._create_default_https_context`，同时透传给全部 `--run-script` 子进程。
- **境外检查更新与云端 API 局部代理智能回退 (`net_guard.py`, `user_settings.py`, `api/settings.py`)**：在保持全部 A 股国内数据源 `100%` 纯净直连（`no_proxy=*`）的前提下，当检查 GitHub 更新或访问境外大模型接口发生网络阻断/超时且检测到本机系统代理端口在线时，自动构造无全局污染的局部隧道单次重试，并展开显示 `URLError` 内部具体异常类型。
- **Windows AppData 权限受阻自动回退便携模式 (`app_paths.py`, `floe_app.py`)**：修复部分开启「受控文件夹访问」或安装第三方安全管家的 Windows 设备拦截 `%APPDATA%\Floe` 写入（`[WinError 5] 拒绝访问`）导致启动失败的问题；自动实测目录写权限并降级至程序同级 `Floe_Data` 便携目录，同步收拢受限的 `TEMP`、`WEBVIEW2_USER_DATA_FOLDER` 与 `MPLCONFIGDIR` 缓存。
- **npm 全局包规范化 (`packaging/npm/package.json`)**：规范化 `bin` 入口相对路径，消除 npm 10+ 校验警告。

---

## ✅ 质量

- 回归单元测试扩充至 **311 项**（全部通过），新增失效构建机证书路径修复、局部代理隧道回退与 Windows 受控目录自动便携降级专项测试。

---

# v2.0.0 — 品牌焕新 Floe · 现代量化工作台 · 跨平台桌面应用与多渠道分发

> 🚀 核心主题：**开箱即用的跨平台桌面软件与量化工作流全面升级**。项目正式命名为 **Floe**（适合中国宝宝体质的 A 股选股软件），告别繁琐配置与显卡门槛，实现「一键安装 + 云端/本地双模 AI + 三步闭环选股回测 + 分厘级 FIFO 台账」。

---

## 🆕 新增

### 1. 跨平台独立桌面端与多渠道分发
- **独立桌面应用 (`floe_app.py`)**：基于 `pywebview` 原生系统渲染引擎封装独立桌面窗口，macOS 集成黑白极简小企鹅菜单栏状态图标（`NSStatusBar`），Windows / Linux 集成系统托盘（`pystray`），支持 `--web` 浏览器模式与 `--doctor` 命令行诊断。
- **用户数据目录安全隔离 (`app_paths.py`)**：打包模式下自动将配置、自选股、交易台账与行情报告隔离至系统标准应用数据目录（macOS `~/Library/Application Support/Floe`、Windows `%APPDATA%\Floe`、Linux `~/.local/share/floe`），升级替换安装包零数据丢失；冻结二进制支持 `--run-script` 统一调度全部子进程。
- **自动化打包与三端分发 (`packaging/`)**：提供 PyInstaller 精简打包流水线（排除冗余深度学习体积依赖）、GitHub Actions 三大系统自动构建 Release 工作流、Homebrew Cask (`brew install --cask floe`) 与 npm 全局 CLI (`@leo-luxy/floe`)。

### 2. 全新现代量化工作台 UI 与个性化体验
- **三步闭环主线导航**：左侧暗色导航栏 + 顶栏流水线胶囊将核心动线收敛为 `01 市场选股 → 02 关注股票池 → 03 策略回测与监控`，配备浅色/深色双主题及内置离线前端静态资源（零外网 CDN 阻塞）。
- **红涨 / 绿跌双企鹅应用图标**：内置「红涨昂首瞭望款」与「绿跌委屈闭眼款」两套高清圆角图标，支持在「系统设置」中实时切换（同步更新侧边栏、网页 Favicon 及 macOS Dock 图标）。
- **中英双语界面与英文 AI 研报 (`static/js/i18n.js`)**：支持 `简体中文 / English` 一键切换；切换为英文后，新生成的个股与板块 AI 分析报告自动注入英文撰写指令。
- **关于我们与在线更新检查**：顶栏新增「关于我们」弹窗（展示当前版本号、核心能力、版本更新日志、GitHub 仓库主页与作者联系邮箱），设置页支持一键在线比对 GitHub 最新 Release、环境/权限体检及全量个人数据 `.zip` 备份导出/导入（带 AST 安全语法校验）。

### 3. 云端 DeepSeek / OpenAI 兼容 API + 本地 Ollama 双引擎
- **图形化两步强制校验接入 (`user_settings.py`, `api/settings.py`)**：支持 DeepSeek、硅基流动、通义千问、Moonshot 及任意 OpenAI 兼容接口；必须先点击「1. 连接并拉取模型列表」真实连通并选定模型后方可保存，全局透明桥接全仓库 `ollama.Client` / `ollama.chat` 调用。
- **Tushare Token 界面化管理**：支持直接在网页端验证并保存主备 Tushare Token，无需手动修改受 Git 跟踪的源码文件。

### 4. 核心选股、回测与实盘台账升级
- **市场选股仅展示当日新入场**：默认严格过滤 `入场日期 == 数据截止日` 的当日新触发信号标的，自动剥离早期入场的存量持仓副产物。
- **默认简化版策略与本机选股追踪**：回测页面默认启用简化版策略（`MA5 > MA20`），新增 `/api/backtest/get_selected_performance` 追踪本设备历次选股新入场标的自首次入选日起的真实累计回测收益。
- **三位小数（`0.001` 元）FIFO 买卖记录台账**：支持分厘级成交价录入与单条删除，按先进先出（FIFO）逐手核算已落袋实现收益、实时现价浮动盈亏与账户累计总收益，支持展开逐手明细；关注池新增行内修改股票名称功能。
- **端口冲突自动顺延**：默认安全绑定 `127.0.0.1:3130`（`debug=False`），若端口被占用或受限自动探测顺延至 `3131+` 空闲端口。

---

## ✅ 质量

- 回归单元测试扩充至 **309 项**（全部通过），新增端口冲突顺延、三位小数 FIFO 核算、选股队列绩效与跨平台桌面路径隔离专项测试。

---

# v1.6.0 — 选股统一交易日 · 回测身份校验 · 失败可观测

> 🎯 核心主题：**结果可信**。让“显示完成”不再等于“结果正确”，并让失败的批次显式暴露、可复盘。

---

## 🆕 新增

### 选股：整批统一交易日
- 整批冻结唯一行情截止日，候选的行情、指标、回测全部在隔离快照内计算，真实数据不被截断
- 当日行情未齐时整批回退前一交易日；个别停牌（不超过 0.5%）按正常状态处理，不再拖累全批
- 候选池日期与统一日期不一致时自动按该日期重建整套初筛，避免“今日初筛配昨日回测”

### 选股：每日留存
- 每个成功批次按交易日归档最终名单（含名单、状态指纹、运行日志），失败/限流/仅初筛不写入
- 页面新增“查看日期”，可回看历史结果；同日多次运行保留历次运行记录

### 回测：产物身份
- 回测产物带运行身份、参数指纹、来源快照与内容 SHA256；复权重建或参数变化后旧结果自动失效
- 行情与指标的来源双向绑定，同日行情变化也必须重算指标

### Tushare 主备 token
- 主 token 命中频率超限时自动切换备用 token 重试同一请求，并记住可用者；全部限流才回退

---

## 🐛 修复

- 交易日确定：删除会滞后一天的第三方探测兜底，探测与取数统一走同一接口；取到旧日期会明确告警
- 回测报告与图表不再因身份校验失败而空白：优先展示身份完整产物，缺失时回退最近文件并标注“未核验”
- 选股任务展示修复：进度条可见、结果表去重时间列、处理时间保留到秒
- 首页禁用缓存，避免升级后仍加载旧前端

---

## ⚠️ 升级提示

- 本次改动了选股、回测、数据更新与前端展示，**升级后建议重跑一次批量回测**，以生成带新身份的产物
- 旧的选股结果文件不会自动迁移；如需保留历史，请在升级前备份 `stocks_filter/` 下的名单文件

---

## ✅ 质量

- 回归测试扩充至 **296 项**，覆盖身份校验、失败状态、混合日期、留存与前端展示

---
# v1.5.0 — 文档重构 · 回测修复 · 依赖清理

> 🧹 核心主题：**工程整理**。重构文档体系、修复回测页默认显示问题、清理冗余脚本与依赖。

---

## 🆕 新增

### 技术文档体系
| 文档 | 内容 |
|------|------|
| `Introduction.md` | **技术详解** —— 系统架构、五维决策体系、模块技术档案、数据字典、33 个 API 路由参考、设计演进与已知限制 |
| `README.md` | 重写为面向使用者的**部署与使用主文档** —— 分平台 11 步部署流程、依赖安装、Token 申请、9 条常见问题排查、安全注意事项 |

### 任务状态持久化
- `api/common.py` —— 任务状态写入 `.task_status_cache.json`，服务重启后已完成的任务记录不再丢失

---

## 🐛 Bug 修复

| 问题 | 修复 |
|------|------|
| **回测页默认显示几百天前的过时报告** | 监控报告、回测结果、回测图表的「取最新」逻辑改用**真实日期排序**。原先用字符串降序，`monitor_report_simplified_20260527.md` 会因字母 `s` 大于数字而排在 `monitor_report_20260928.md` 之前 |
| 交易记录日期框硬编码为固定日期 | 改为默认显示当天；添加记录后重置为当天而非清空 |
| `em_financial_collector.py` 遇到 JSON 返回 null 时异常 | 增加空值判断 |
| 依赖清单缺少 Web 框架 | `flask` 补入 `requirements.txt` |

---

## 🧹 清理

| 项目 | 说明 |
|------|------|
| 冗余脚本 | 移除无任何引用的脚本；清理失效的模块设计文档（合并入 `Introduction.md`） |
| 冗余依赖 | 移除 `demjson`、`pandas-datareader`、`yfinance`（代码零引用）。其中 `demjson` 依赖 Python 3.12 已移除的 `imp` 模块，是此前 3.12+ 无法安装依赖的主因 |
| 运行产物 | 选股流水线 CSV、任务状态缓存、Numbers 工作文件移出版本控制并加入 `.gitignore` |

---

## ⚠️ 升级提示

- Python 支持范围明确为 **3.9 ~ 3.12**（`numpy==1.26.3` 不支持 3.13）
- 依赖清单已可直接安装，无需再手动补装 `flask`
- 部署文档已从 `DEPLOYMENT_GUIDE.md` 迁入 `README.md`，该文件不再单独存在

---

# v1.4.0 — 市场选股 · 自选股管理

> 📊 核心主题：**全市场筛选能力 + Web 交互增强**。

---

## 🆕 新增功能

| 模块 | 功能 |
|------|------|
| **市场选股** | `stocks_filter/` 四步流水线：全市场日线 → 基础指标 → 多条件筛选 → 批量趋势回测，输出最终持仓（需 Tushare token） |
| **自选股管理** | `api/watchlist.py` + `watchlist.py`，Web 界面增删查；回测与分析优先使用关注列表 |
| **板块分析增强** | 四大板块类型（大盘/行业/概念/港股）AI 深度分析 |

---

## 🐛 Bug 修复

| 问题 | 修复 |
|------|------|
| 板块分析 KDJ 计算错误 | 弃用 `talib.STOCH` 默认参数（`fastk_period=5`+SMA），改用 A 股标准 9 日 EMA 算法 |
| 板块分析大盘对比数据过时 | 分析前刷新大盘指数数据，并增加时效性检测警告 |
| 指数代码误调成分股 API 导致连接中断 | 指数代码不再调用东方财富行业板块成分股接口 |
| `collect_broad_index_daily` 变量未初始化 | 修复 `NameError` |

---

## 🔧 增强

- 回测报告显示公司简称
- 数据抓取增加超时控制
- 大盘指数采集增加新浪财经主力数据源，东方财富降级为兜底

---

# v1.3.0 — 板块分析 · 数据源增强

> 📊 从 v1.2.0 的 55 个模块扩展到 **58 个模块**。核心主题：**板块维度覆盖 + 数据源可靠性**。

---

## 🆕 新增功能

### 板块分析系统
从个股维度扩展到板块维度，支持四大板块类型的 AI 深度分析：

| 模块 | 功能 |
|------|------|
| `sector_data_collector.py` | **板块数据采集器** — 支持大盘指数 / 行业板块 / 概念板块 / 港股指数，新浪财经主力数据源+东方财富兜底 |
| `analyze_sector.py` | **板块分析引擎** — 技术指标计算 + LLM 分析报告生成，支持 single（单板块深度）和 broad（大盘全景）两种模式 |
| `api/sector.py` | **板块分析 API** — 自包含 Blueprint，数据采集/分析触发/状态轮询/报告获取全流程 |

### Web 界面扩展
- `templates/index.html` — 新增板块分析页面：类型选择（大盘/行业/港股）、板块下拉选择/手动输入、AI 分析按钮、任务进度实时展示、历史报告浏览
- `web_ui.py` — 注册 sector API 蓝图

---

## 🔧 数据源增强

| 改进 | 说明 |
|------|------|
| **新浪财经主力数据源** | 大盘指数采集增加新浪财经作为主力数据源，东方财富降级为兜底方案，提高数据获取成功率 |
| **固定文件名覆盖** | 板块异动和资金流向数据文件使用固定文件名，每次覆盖避免历史文件堆积 |

---

## 🐛 Bug 修复

| 问题 | 修复 |
|------|------|
| `collect_broad_index_daily` 中 `df` 未初始化导致 `NameError` | 修复变量作用域问题，确保异常路径也能正确处理 |
| 板块分析使用过期数据 | 分析前始终重新采集最新数据，解决数据时效性问题 |

---

## 📊 版本对比

| | v1.2.0 | v1.3.0 |
|------|--------|--------|
| 模块总数 | 55 | 58 |
| 分析维度 | 个股五维度 | 个股五维度 + 板块分析 |
| 板块类型 | — | 大盘指数 / 行业 / 概念 / 港股 |
| 数据源 | 东方财富为主 | 新浪财经主力 + 东方财富兜底 |
| API 蓝图 | 6 个 | 7 个（+板块分析） |

---

# v1.2.0 — 架构重构 · 统一 API · 多层决策

> 🏗️ 从 v1.1.0 的 41 个模块扩展到 **55 个模块**。核心主题：**统一化 + 模块化 + 智能决策**。

---

## 🏛️ 架构重构

### 统一数据抓取
- **新增** `eastmoney_fetcher.py` — 统一的东方财富数据抓取入口，支持 `--type` 参数切换数据类型
- **移除** 5 个独立 fetch 脚本：
  - ~~`fetch_stock_market_performance.py`~~
  - ~~`fetch_industry_valuation.py`~~
  - ~~`fetch_industry_peers.py`~~
  - ~~`fetch_industry_growth.py`~~
  - ~~`fetch_dupont_analysis.py`~~

### 统一批量分析
- **新增** `batch_analyze.py` — 统一的批量分析入口，`--mode periodic|daily` 切换模式
- **移除** 3 个独立 batch 脚本：
  - ~~`batch_analyze_all.py`~~
  - ~~`batch_analyze_daily.py`~~
  - ~~`batch_analyze_periodic.py`~~

### 统一数据更新检查
- **重构** `check_data_updates.py` — 合并了原 `check_periodic_data_updates.py` 的功能，`--mode daily|periodic|all`
- **移除** ~~`check_periodic_data_updates.py`~~

### API 模块共享
- **新增** `api/common.py` — 交易所映射、任务队列管理、步骤执行引擎（DRY 原则）
- `api/analysis.py`、`api/detailed.py`、`api/trading.py`、`api/report_viewer.py` 统一引用

---

## 🧠 新增 Process/ 分析引擎

五维度 JSON 摘要 + 两层决策系统，实现从原始数据到交易计划的完整 AI 决策链：

| 模块 | 功能 | 决策权重 |
|------|------|----------|
| `Process/financial_structured_analyzer.py` | 财务数据 → 结构化 JSON 摘要 | 25% |
| `Process/sentiment_valuation_analyzer.py` | 情绪 + 估值分析 → JSON | 15% |
| `Process/shareholder_structure_analyzer.py` | 股东结构分析 → JSON | 10% |
| `Process/research_report_analyzer.py` | 研报观点提取 → JSON | 10% |
| `Process/financial_analysis_enhancer.py` | 财务深度增强 | — |
| `Process/multi_strategy_analyzer.py` | 多策略 LLM 分析（趋势/波段/均值回归） | — |
| `Process/two_layer_decision_analyzer.py` | **两层决策**：冲突检测 + 持仓交易计划 | 技术 40% |

### 两层决策流程
```
第1层：五维度冲突检测与综合研判
  财务(25%) + 情绪估值(15%) + 技术趋势(40%) + 股东结构(10%) + 研报观点(10%)
  ↓
第2层：结合持仓生成具体交易计划（买入/卖出/观望 + 仓位 + 止损位）
```

---

## 🚀 新增功能模块

### API 扩展
| 模块 | 功能 |
|------|------|
| `api/quick_analysis.py` | **快速分析 API** — 仅 K 线 + 技术趋势，支持 short/medium/long 三种策略视角 |
| `api/backtest.py` | **回测 API** — 趋势跟踪策略回测 |
| `api/common.py` | 共享工具模块（交易所映射、任务队列） |

### 数据采集增强
| 模块 | 功能 |
|------|------|
| `batch_margin_collector.py` | 批量融资融券数据采集 |
| `stock_market_data_collector.py` | +融资融券数据抓取函数（SSE + SZSE） |

### 回测系统
| 模块 | 功能 |
|------|------|
| `backtest_all_stocks.py` | 全股票批量回测 |
| `trend_following_backtest.py` | 趋势跟踪策略回测引擎 |

### 技术分析增强
- `daily/data_analysis.py` — 新增 **OBV、ATR、ADX、MFI** 四项技术指标
- `calculate_technical_trend_ds.py` — DeepSeek 驱动的技术趋势分析（替代旧版 `analyze_technical_trend_ds.py`）

### 行业配置
- **新增** `shenwan_config/` — 申万行业阈值配置模块，支持按市值自动选择配置

### Web 界面
- `web_ui.py` — 注册 quick_analysis 和 backtest API 蓝图

---

## 🔧 功能增强

| 模块 | 改进内容 |
|------|---------|
| `daily/quantitative_strategy.py` | **信号去重** — 防止连续重复买卖信号；新增 `actual_buy`/`actual_sell` 列追踪实际执行；新增 `trades` 交易记录 |
| `stock_company_info_collector.py` | **CSV 去重优化** — 智能行 ID 生成；损坏文件自动检测删除；追加/覆盖模式智能切换 |
| `stock_market_data_collector.py` | **融资融券数据** — 完整的 margin data 抓取函数，支持增量更新 |
| `daily/stock_daily_indicator_calculator.py` | 换手率列优先从 qfq 文件读取 |
| `analyze_technical_trend.py` | 支持 `--strategy` 参数切换趋势跟踪/均值回归/波段/中性四种策略视角 |

---

## 🐛 Bug 修复

| 问题 | 修复 |
|------|------|
| `api/analysis.py` 中错误使用 `analyze_performance_forecast.py` 采集数据 | 改为正确的 `important_missing_data_collector.py` |
| Ollama API 参数名错误 (`max_tokens`) | 全部改为 `num_predict`，部分文件令牌上限提升至 8192 |
| 多个分析模块令牌数减半导致输出不完整 | 取消减半，使用完整 max_tokens |

---

## 🔒 安全改进

- `.gitignore` 新增 `config.py` 排除规则
- `config.example.py` 模板更新至 v1.2 配置结构（含 STRATEGY_PROMPTS）
- `trading_records.py` 保持空模板 + gitignore 保护

---

## 📊 版本对比

| | v1.1.0 | v1.2.0 |
|------|--------|--------|
| 模块总数 | 41 | 55 |
| 数据抓取入口 | 5 个独立脚本 | 1 个统一入口 + `--type` |
| 批量分析入口 | 3 个独立脚本 | 1 个统一入口 + `--mode` |
| 分析引擎 | 单层 LLM | 五维度 + 两层决策 |
| API 端点 | 4 个蓝图 | 6 个蓝图（+快速分析、回测） |
| 技术指标 | 12 个 | 16 个（+OBV, ATR, ADX, MFI） |
| 量化策略 | 基础信号 | 信号去重 + 实际执行追踪 |

---

**完整 changelog**: https://github.com/Leo-luxy/Floe/compare/v1.1.0...v1.2.0
