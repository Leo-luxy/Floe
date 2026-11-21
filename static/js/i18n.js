/* static/js/i18n.js
 * Floe 双向无损中英国际化引擎（支持静态 DOM 与动态渲染表格，自动保护 Markdown 研报正文）
 */
(function () {
    'use strict';

    const EXACT_DICT = {
        // 品牌与侧边栏
        'GP_ANA · A股量化投研工作台': 'Floe · A-Share Screener for CN Investors',
        'Floe · 量化投研工作台': 'Floe · A-Share Screener for CN Investors',
        '适合中国宝宝体质的 A 股选股软件': 'A-Share Screener Tailored for CN Investors',
        '选股 · 标的池 · 趋势回测': 'Screener · Watchlist · Backtest',
        '关于我们': 'About Us',
        '当前版本': 'Current Version',
        '📋 查看更新内容': '📋 What\'s New',
        '▴ 收起更新内容': '▴ Hide Changelog',
        '🔄 检查新版本': '🔄 Check Updates',
        '项目主页': 'GitHub Repository',
        '前往主页 ↗': 'Open GitHub ↗',
        '联系邮箱': 'Contact Email',
        '复制邮箱': 'Copy',
        '发邮件': 'Email',
        '🎨 应用图标切换': '🎨 App Icon Style',
        '切换软件左上角、网页标签与 macOS 桌面 Dock 栏的小企鹅图标（红涨昂首瞭望 / 绿跌委屈闭眼）。': 'Switch the Floe penguin icon across sidebar, favicon, and macOS Dock.',
        '📈 红涨瞭望款': '📈 Bullish (Lookout)',
        '📉 绿跌闭眼款': '📉 Bearish (Eyes Closed)',
        '核心工作流': 'CORE WORKFLOW',
        '市场选股': 'Market Screener',
        '关注股票池': 'Watchlist Pool',
        '策略回测与监控': 'Backtest & Monitor',
        '扩展研判工具': 'RESEARCH TOOLS',
        '个股 AI 研判': 'Stock AI Hub',
        '板块与指数 AI': 'Sector & Index AI',
        '买卖记录台账': 'Trading Ledger',
        '报告归档中心': 'Report Archive',
        '系统设置': 'Settings',

        // 顶栏
        '01 · 市场选股': '01 · Market Screener',
        '02 · 关注股票池': '02 · Watchlist Pool',
        '03 · 策略回测与监控': '03 · Backtest & Monitor',
        '⚡ 个股 AI 研判中心': '⚡ Stock AI Research Hub',
        '🌐 板块与指数 AI 研判': '🌐 Sector & Index AI',
        '📝 买卖记录台账与收益核算': '📝 Trading Ledger & FIFO P&L',
        '📚 本地报告归档中心': '📚 Local Report Archive',
        '⚙️ 系统设置与运维中心': '⚙️ System Settings & Ops',
        '01 市场选股': '01 Screener',
        '02 关注股票池': '02 Watchlist',
        '03 策略回测监控': '03 Backtest',
        '待完成基础配置 · 去设置': 'Setup Required · Go to Settings',
        '任务运行中...': 'Task running...',
        'AI 研判': 'AI Analyze',
        '深色': 'Dark',
        '浅色': 'Light',

        // 01 市场选股
        '当日新入场标的': 'Today New Entries',
        '可入场': 'Entry',
        '仅展示入场日期 = 截止日标的': 'Only entry date = data as-of date',
        '新入场未关注': 'Unwatched New Entries',
        '可一键批量加入关注池': 'Batch-add ready to Watchlist',
        '已过滤早期入场': 'Filtered Prior Entries',
        '存量持仓重过初筛副产物': 'Legacy holdings re-passing filter',
        '数据统一截止日': 'Unified Data As-Of',
        '下一步 →': 'Next →',
        '点击前往 02 关注股票池': 'Click to open 02 Watchlist',
        '全市场趋势选股筛查台': 'Full-Market Trend Screener',
        '整批统一交易日快照 · 仅展示当日新触发入场信号标的（自动剔除早期入场存量副产物与北交所）': 'Unified trade-date snapshot · Displays only newly triggered entries today (excludes prior holdings & BSE)',
        '★ 将新入场未关注标的批量入池': '★ Batch Add Unwatched to Pool',
        '步骤 1：全市场初步筛选': 'Step 1: Market Pre-Filter',
        '步骤 2：批量趋势回测精筛': 'Step 2: Trend Backtest Filter',
        '▶ 开始市场选股': '▶ Run Market Screener',
        '留存日期：': 'History:',
        '最近有效结果': 'Latest Valid Result',
        '股票代码': 'Ticker',
        '股票名称': 'Name',
        '入场日期': 'Entry Date',
        '入场价格': 'Entry Price',
        '当前价格': 'Latest Price',
        '当前收益': 'Return',
        '关注状态': 'Watch Status',
        '联动操作': 'Actions',
        '已关注': '★ Watched',
        '+ 关注': '+ Watch',
        '⚡ 快速研判': '⚡ Quick AI',
        '🧠 完整决策': '🧠 Full AI',

        // 02 关注股票池
        '关注池总数': 'Total Watched',
        '📋 全部展示': '📋 Show All',
        '作为策略回测的输入标的池': 'Input universe for strategy backtest',
        '可入场信号': 'Entry Signals',
        '最新交易日触发趋势确认': 'Trend confirmed on latest trade day',
        '趋势持有中': 'In-Trend Hold',
        '持有': 'Hold',
        '持仓未触发离场或保护止损': 'Active trend without exit/stop hit',
        '空仓 / 冷却观望': 'Flat / Cooldown Watch',
        '观望': 'Watch',
        '等待趋势确认或 3 日冷却结束': 'Awaiting trend or 3-day cooldown',
        '关注股票池指挥台': 'Watchlist Command Deck',
        '管理核心自选股（自动同步最近一次有效回测信号与绩效），一键联动回测图、AI 研判与买卖台账': 'Manage core watchlist synced with latest verified backtest signals, charts, AI & ledger',
        '← 去选股补充标的': '← Back to Screener',
        '▶ 前往策略回测与监控 →': '▶ Go to Backtest & Monitor →',
        '+ 添加关注': '+ Add Ticker',
        '全部': 'All',
        '当前监控信号': 'Live Signal',
        '最新价 / 信号说明': 'Latest Price / Signal Detail',
        '⏳ 待回测': '⏳ Pending Backtest',
        '🔴 可入场': '🔴 Entry',
        '🔵 持有': '🔵 Hold',
        '⚪ 观望': '⚪ Watch',
        '📈 回测图': '📈 Chart',
        '📝 记账': '📝 Ledger',
        '移除': 'Remove',

        // 03 策略回测与监控
        '🔴 可入场标的': '🔴 Entry Candidates',
        '今日新信号': 'New Today',
        '趋势确认 + 空仓无冷却': 'Trend confirmed & no cooldown',
        '🔵 持有中标的': '🔵 Active Holdings',
        '趋势延续': 'Trend Intact',
        '关注移动止盈与峰值回撤': 'Track trailing stop & peak drawdown',
        '⚪ 观望 / 冷却': '⚪ Watch / Cooldown',
        '耐心等待': 'Standby',
        '离场 3 日冷却或未达多头门槛': '3-day exit cooldown or below threshold',
        '可用回测图表': 'Backtest Charts',
        '🖼️ 点击浏览': '🖼️ Browse Gallery',
        '支持弹窗内 ← → 键盘翻图': 'Use ← → arrow keys in modal',
        '关注池策略回测与实时监控': 'Watchlist Strategy Backtest & Live Monitor',
        '严格校验行情指纹与期望交易日 · 点击报告中的股票代码即可直接弹出回测 K 线图': 'Strict quote-hash & trade-date provenance · Click any ticker in report to inspect K-line chart',
        '执行流程：': 'Pipeline:',
        '完整流程（更新行情+回测）': 'Full Run (Update Quotes + Backtest)',
        '快速回测（仅回测+报告）': 'Quick Run (Backtest Cached Data)',
        '策略预设：': 'Preset:',
        '简化版（MA5 > MA20 · 默认）': 'Simple (MA5 > MA20 · Default)',
        '完整版（MA四线多头）': 'Full (MA 5/10/20/60 Alignment)',
        '▶ 开始策略回测': '▶ Run Backtest',
        '📡 实时监控报告': '📡 Live Monitor Report',
        '📊 历史回测绩效表（本机选股追踪）': '📊 Tracked Selection Performance',
        '🖼️ 股票回测图表库': '🖼️ Backtest Chart Gallery',
        '← 上一只': '← Prev',
        '下一只 →': 'Next →',
        '⚡ AI 快速研判': '⚡ Quick AI',

        // 扩展 1：个股 AI
        '个股 AI 深度研判中心': 'Stock AI Deep Research Hub',
        '日常盯盘用「快速技术研判」，重点建仓前用「五维两层完整决策」排雷': 'Use Quick Technical AI for daily tracking; run 5D Two-Layer Decision before major entries',
        '⚡ 快速技术研判（K线日更）': '⚡ Quick Technical AI (Daily K-Line)',
        '🧠 五维两层完整决策（全量排雷）': '🧠 5D Two-Layer Full Decision',
        '股票代码：': 'Ticker:',
        '交易周期：': 'Horizon:',
        '短期交易': 'Short-Term',
        '中期持仓': 'Medium-Term',
        '长期投资': 'Long-Term',
        '☆ 加入关注池': '☆ Add to Watchlist',
        '▶ 开始快速研判': '▶ Run Quick AI',
        '流程：全量采集 → 技术40% + 财务25% + 情绪估值15% + 股东10% + 研报10% → 两层决策': 'Pipeline: Full Fetch → Tech 40% + Fin 25% + Sent/Val 15% + Holders 10% + Reports 10% → 2-Layer Decision',
        '📂 查看该股已有报告': '📂 Existing Reports',
        '▶ 开始完整五维分析': '▶ Run Full 5D Analysis',
        '已生成的分析报告': 'Generated Analysis Reports',
        '← 返回报告列表': '← Back to List',

        // 扩展 2：板块 AI
        '板块与指数 AI 研判': 'Sector & Index AI Research',
        '大盘基准自动刷新对齐 · 标准 9 日 EMA KDJ': 'Auto benchmark refresh · Standard 9-day EMA KDJ',
        '板块类别': 'Category',
        '大盘指数': 'Broad Indices',
        '行业板块': 'Industries',
        '港股指数': 'HK Indices',
        '选择目标板块': 'Target Sector / Index',
        '🔄 刷新列表': '🔄 Refresh',
        '-- 请选择板块 --': '-- Select Sector / Index --',
        '或手动输入指数 / BK 代码': 'Or Enter Index / BK Code Manually',
        '▶ 开始 AI 分析': '▶ Run AI Analysis',
        '⬇ 更新数据': '⬇ Update Data',
        '📁 最近板块研报归档': '📁 Recent Sector Reports',
        '加载中...': 'Loading...',
        '执行进度': 'Progress',
        '请在左侧选择板块执行 AI 分析，或点击左下角历史报告直接阅读': 'Select a sector on the left to run AI analysis, or click a saved report below to read',

        // 扩展 3：买卖台账
        '账户累计总收益': 'Cumulative Total P&L',
        '💰 已实现 + 持仓浮盈': '💰 Realized + Unrealized',
        '已落袋实现盈亏': 'Realized P&L',
        '✅ 已平仓手次合计': '✅ Closed Lots Total',
        '按先进先出（FIFO）逐手配对': 'Matched lot-by-lot via FIFO',
        '当前持仓浮动盈亏': 'Open Unrealized P&L',
        '📈 按最新现价折算': '📈 Marked to Latest Price',
        '记账标的统计': 'Tracked Tickers',
        '📊 持仓 / 历史总股数': '📊 Open / Total Tickers',
        '点击右侧各股可展开每一手明细': 'Click any stock row to expand lot-by-lot breakdown',
        '买卖记录录入': 'Record Trade Execution',
        '录入实盘成交后自动重算分股收益，并供 AI 两层决策读取持仓成本': 'Auto-recalculates FIFO P&L and feeds cost basis into 2-Layer AI Decisions',
        '股票代码（6位数字）': 'Stock Code (6 Digits)',
        '查单股流水': 'Load Logs',
        '从关注池快速点选：': 'Quick pick from Watchlist:',
        '➕ 新增一笔成交': '➕ Add Trade Fill',
        '成交日期': 'Trade Date',
        '方向': 'Side',
        '买入 (BUY)': 'BUY',
        '卖出 (SELL)': 'SELL',
        '成交均价': 'Fill Price',
        '股数': 'Shares',
        '保存成交并更新收益': 'Save Trade & Recalculate P&L',
        '📋 单股原始流水': '📋 Raw Trade Fills',
        '🧠 持仓决策': '🧠 Position AI',
        '输入代码查看原始录入记录': 'Enter ticker to view raw trade logs',
        '分股历史收益与逐手明细': 'Per-Stock P&L & FIFO Lot Breakdown',
        '在持仓部分自动按最新现价核算浮动收益 · 点击任意股票行可展开查看每一手买卖盈亏': 'Open lots marked to latest quote · Click any row to inspect each matched lot',
        '🔄 刷新最新现价重算': '🔄 Refresh Live Quotes',
        '股票代码 / 名称': 'Ticker / Name',
        '持仓状态': 'Status',
        '成本 / 最新现价': 'Avg Cost / Latest',
        '已实现盈亏': 'Realized P&L',
        '持仓浮动盈亏': 'Unrealized P&L',
        '单股累计总收益': 'Total P&L',
        '逐手明细': 'Lot Details',
        '已清仓': 'Closed',
        '全部平仓完毕': 'All lots closed',
        '▴ 收起明细': '▴ Hide Lots',
        '流水': 'Logs',
        '手次': 'Lot',
        '状态': 'State',
        '买入日期 & 均价': 'Buy Date & Price',
        '卖出日期 / 最新现价': 'Sell Date / Latest',
        '本手盈亏额': 'Lot P&L',
        '本手收益率': 'Lot Return',
        '已平仓': 'Closed',
        '持仓中(按现价)': 'Open (Live)',
        '持仓中': 'Open',
        '日期': 'Date',
        '价格': 'Price',
        '操作': 'Action',
        '买入': 'BUY',
        '卖出': 'SELL',
        '删除': 'Delete',

        // 扩展 4：报告归档
        '本地研报归档中心': 'Local Research Report Archive',
        '三栏同屏检索本地已生成的各维度 Markdown 报告（无需来回点击返回）': 'Three-pane browser for all locally generated Markdown research reports',
        '1. 选择股票': '1. Select Ticker',
        '2. 报告清单': '2. Report List',
        '← 请先在左侧选择一只股票': '← Select a ticker on the left first',
        '3. 报告正文预览': '3. Report Reader',
        '选择中间列的报告即可在此沉浸式阅读': 'Select a report from the middle column to read here',

        // 系统设置页
        '配置 AI 大模型接口（默认推荐 DeepSeek API 或本地 Ollama）、Tushare 选股数据源以及底层运维工具': 'Configure AI LLM engine, Tushare data source, language, permissions, updates & backups',
        '🔑 AI 与数据源': '🔑 AI & Data Sources',
        '🌐 语言·权限·更新': '🌐 Lang · Perms · Update',
        '💾 数据备份与目录': '💾 Backup & Storage',
        '🔎 分类数据操作': '🔎 Data Ops',
        '⚙️ 单脚本调试': '⚙️ Script Runner',
        '🤖 AI 大模型配置': '🤖 AI Model Configuration',
        '检测中...': 'Checking...',
        '🔗 获取 DeepSeek API Key ↗': '🔗 Get DeepSeek API Key ↗',
        '推理引擎模式': 'Inference Provider',
        '☁️ 云端 API（推荐 DeepSeek）': '☁️ Cloud API (DeepSeek Recommended)',
        '💻 本地 Ollama 服务': '💻 Local Ollama Server',
        '第 1 步：配置接口地址并验证连接': 'Step 1: Configure Endpoint & Verify Connection',
        'API 接口地址 (Base URL)': 'API Base URL',
        'API Key 密钥': 'API Key',
        '本地 Ollama 服务地址': 'Local Ollama URL',
        '🔌 验证连接并获取可用模型列表': '🔌 Verify Connection & Fetch Model List',
        '第 2 步：选择服务端返回的模型并启用': 'Step 2: Select Returned Model & Activate',
        '待验证解锁': 'Verify to unlock',
        '-- 请先完成第 1 步验证连接 --': '-- Complete Step 1 verification first --',
        '💾 保存并启用所选模型': '💾 Save & Enable Selected Model',
        '📡 选股信息源（Tushare Pro）': '📡 Market Screener Source (Tushare Pro)',
        '🔗 查看/复制 Token ↗': '🔗 View / Copy Token ↗',
        '注册账号 ↗': 'Sign Up ↗',
        '主 Token (Primary Token)': 'Primary Token',
        '备用 Token 列表（可选，逗号或换行分隔）': 'Backup Tokens (Optional, comma or newline separated)',
        '💾 保存 Tushare 配置': '💾 Save Tushare Config',

        // 设置 - 语言、权限与更新面板
        '🌐 界面与研报语言': '🌐 Interface & AI Report Language',
        '切换为 English 后，软件全部界面文案切换为英文，且后续新发起的个股/板块 AI 研判报告将自动以专业英文输出。': 'When set to English, both the workbench UI and newly generated AI research reports switch to professional English.',
        '🔄 软件版本与检查更新': '🔄 Version & Software Updates',
        '立即检查更新': 'Check for Updates',
        '前往 GitHub Releases ↗': 'Open GitHub Releases ↗',
        '🛡️ 电脑权限申请与运行环境体检': '🛡️ System Permissions & Environment Check',
        'Floe 遵循最小权限原则，不请求摄像头、麦克风或通讯录等隐私权限，仅需桌面通知与本地数据读写/网络访问。': 'Floe follows least-privilege design: no camera, mic, or contacts needed—only desktop notifications, local storage, and market network access.',
        '🔔 桌面通知权限（后台选股/回测完成提醒）': '🔔 Desktop Notifications (Background Task Alerts)',
        '申请/测试桌面通知': 'Grant & Test Notification',
        '🌐 网络连接策略（国内数据源 vs 系统代理）': '🌐 Network Strategy (Direct vs System Proxy)',
        '国内直连优先（默认 · 绕过翻墙代理防断流）': 'Direct Mode (Default · Bypass VPN for CN feeds)',
        '跟随系统代理（适合海外网络或需代理连 GitHub）': 'Use System Proxy (For overseas or GitHub access)',
        '🩺 重新运行环境体检': '🩺 Re-run Diagnostics',

        // 设置 - 数据备份与目录
        '📂 本地数据存储隔离目录': '📂 Isolated User Data Directory',
        '安装包升级时不会覆盖个人数据目录，关注池、交易台账与密钥配置持久安全保留。': 'Personal data is stored separately from the app bundle so upgrades never overwrite your watchlist, ledger, or keys.',
        '📂 在系统文件管理器中打开': '📂 Reveal in File Manager',
        '💾 配置与资产台账一键备份 / 恢复': '💾 One-Click Backup & Restore',
        '导出包含关注池 (watchlist)、买卖记录台账 (trading_records) 与系统设置 (user_settings) 的加密安全校验包。': 'Export or restore a verified .zip archive containing your Watchlist, Trading Ledger, and Settings.',
        '⬇️ 导出备份包 (.zip)': '⬇️ Export Backup (.zip)',
        '⬆️ 导入恢复备份包 (.zip)': '⬆️ Restore from Backup (.zip)',

        // 运维调试
        '查询本地数据状态': 'Query Local Data Status',
        '抓取特定类型数据': 'Fetch Specific Data',
        '分析特定类型数据': 'Analyze Specific Data',
        '日更数据（行情、资金流等）': 'Daily Data (Quotes, Fund Flow)',
        '低频数据（公司信息、财务等）': 'Periodic Data (Company, Financials)',
        '业绩预告与分红数据': 'Earnings Forecast & Dividends',
        '股东结构数据': 'Shareholder Structure',
        '同行对比数据': 'Industry Peer Comparison',
        '▶ 执行操作': '▶ Execute',
        '请选择操作类型并输入股票代码执行': 'Select operation type and enter 6-digit ticker',
        '分析程序': 'Analysis Scripts',
        '计算程序': 'Calculation Scripts',
        '抓取程序': 'Collector Scripts',
        '▶ 运行脚本': '▶ Run Script',
        '请选择脚本并输入股票代码运行': 'Select a script and enter 6-digit ticker'
    };

    const PLACEHOLDER_DICT = {
        '输入6位代码研判...': '6-digit code for AI...',
        '🔍 搜索结果中的代码...': '🔍 Filter ticker code...',
        '股票代码 如 300433': 'Ticker e.g. 300433',
        '名称（留空自动识别）': 'Name (auto if blank)',
        '搜索代码或名称...': 'Filter code or name...',
        '筛选股票代码...': 'Filter ticker...',
        '例如 300433': 'e.g. 300433',
        '如 sz399991 或 BK0478': 'e.g. sz399991 or BK0478',
        '如 300433': 'e.g. 300433',
        '搜索股票代码或名称...': 'Search ticker or name...',
        '粘贴 sk-... 密钥（已保存且未改地址时可留空直接拉取）': 'Paste sk-... key (leave blank if already saved)',
        '输入 Tushare Token（已配置时留空则保持现有主 Token）': 'Enter Tushare Token (blank keeps existing)',
        '可填写 1~N 个备用 Token，主 Token 触发频控时自动接力（留空不改动现有备用池）': 'Optional 1..N backup tokens, auto-rotated on rate limit',
        '6位股票代码': '6-digit ticker'
    };

    const PATTERN_RULES = [
        [/^未配置 (.+) · 去设置$/, (_, m1) => `Missing ${m1.replace('AI模型/API', 'AI/API')} · Setup`],
        [/^查看关注池 \((\d+)\) →$/, (_, n) => `Watchlist (${n}) →`],
        [/^← 调整关注池 \((\d+)\)$/, (_, n) => `← Edit Watchlist (${n})`],
        [/^持仓 (\d+) 股$/, (_, n) => `Holding ${n} shs`],
        [/^▾ 展开 (\d+) 手明细$/, (_, n) => `▾ Expand ${n} Lots`],
        [/^共 (\d+) 笔原始录入 · 净持仓：(-?\d+) 股$/, (_, c, s) => `${c} fills · Net position: ${s} shs`],
        [/^相对累计买入额收益率 ([+-]?[\d.]+%)$/, (_, r) => `Return on cumulative buy cost ${r}`],
        [/^当前持仓总市值 (¥[\d,.]+)$/, (_, v) => `Open market value ${v}`],
        [/^(\d+) \/ (\d+) 只$/, (_, a, b) => `${a} / ${b} tickers`],
        [/^成本 ([\d.]+) \/ 现价 ([\d.]+)$/, (_, c, p) => `Cost ${c} / Last ${p}`],
        [/^已返回 (\d+) 个可用模型$/, (_, n) => `${n} models available`],
        [/^🟢 云端 API \((.+)\)$/, (_, m) => `🟢 Cloud API (${m})`],
        [/^🟢 本地 Ollama \((.+)\)$/, (_, m) => `🟢 Local Ollama (${m})`],
        [/^🔴 未配置可用 AI$/, () => '🔴 AI Not Configured'],
        [/^🟢 已配置 \((\d+) 个 Token\)$/, (_, n) => `🟢 Ready (${n} Token${n === '1' ? '' : 's'})`],
        [/^🔴 未配置 Token$/, () => '🔴 Token Missing'],
        [/^当前已存: (.+)$/, (_, m) => `Saved: ${m}`],
        [/^当前未保存密钥$/, () => 'No key saved'],
        [/^当前主 Token: (.+)$/, (_, m) => `Saved: ${m}`],
        [/^当前未配置$/, () => 'Not configured']
    ];

    let currentLang = 'zh-CN';
    try {
        const saved = localStorage.getItem('floeLang');
        if (saved === 'en-US' || saved === 'zh-CN') currentLang = saved;
    } catch (e) {}

    function translateStringToEn(zhStr) {
        const trimmed = zhStr.trim();
        if (!trimmed) return null;
        if (Object.prototype.hasOwnProperty.call(EXACT_DICT, trimmed)) {
            return zhStr.replace(trimmed, EXACT_DICT[trimmed]);
        }
        for (let i = 0; i < PATTERN_RULES.length; i++) {
            const [re, replacer] = PATTERN_RULES[i];
            if (re.test(trimmed)) {
                return zhStr.replace(trimmed, trimmed.replace(re, replacer));
            }
        }
        return null;
    }

    function shouldSkipElement(el) {
        if (!el || el.nodeType !== 1) return false;
        const tag = el.tagName;
        if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEXTAREA' || tag === 'CODE' || tag === 'PRE') {
            return true;
        }
        if (el.closest && el.closest('.markdown-body, [data-no-i18n="1"]')) {
            return true;
        }
        return false;
    }

    function processSubtree(root) {
        if (!root) return;
        const isEn = (currentLang === 'en-US');

        // 1. 处理占位符 placeholder
        const inputs = root.querySelectorAll ? root.querySelectorAll('input[placeholder], textarea[placeholder]') : [];
        inputs.forEach(inp => {
            if (inp.__origPh === undefined) {
                inp.__origPh = inp.getAttribute('placeholder') || '';
            }
            if (isEn) {
                const mapped = PLACEHOLDER_DICT[inp.__origPh];
                if (mapped) inp.setAttribute('placeholder', mapped);
            } else if (inp.__origPh) {
                inp.setAttribute('placeholder', inp.__origPh);
            }
        });

        // 2. 遍历文本节点双向切换
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
        let node;
        while ((node = walker.nextNode())) {
            const parent = node.parentElement;
            if (!parent || shouldSkipElement(parent)) continue;
            const val = node.nodeValue || '';
            if (!val.trim()) continue;

            if (isEn) {
                // 若节点值已被 JS 动态更新为新的中文，同步刷新 __origZh
                if (node.__origZh === undefined || (val !== node.__lastEn && val !== node.__origZh)) {
                    node.__origZh = val;
                }
                const enVal = translateStringToEn(node.__origZh);
                if (enVal !== null && node.nodeValue !== enVal) {
                    node.__lastEn = enVal;
                    node.nodeValue = enVal;
                }
            } else {
                if (node.__origZh !== undefined && node.nodeValue === node.__lastEn) {
                    node.nodeValue = node.__origZh;
                }
            }
        }
    }

    let rafPending = false;
    function scheduleTranslate() {
        if (rafPending) return;
        rafPending = true;
        window.requestAnimationFrame(() => {
            rafPending = false;
            processSubtree(document.body);
        });
    }

    window.wbGetLang = function () {
        return currentLang;
    };

    window.wbT = function (zhText, enText) {
        return currentLang === 'en-US' ? enText : zhText;
    };

    window.wbApplyLanguage = function (lang) {
        currentLang = (lang && String(lang).toLowerCase().startsWith('en')) ? 'en-US' : 'zh-CN';
        try {
            localStorage.setItem('floeLang', currentLang);
        } catch (e) {}
        document.documentElement.setAttribute('lang', currentLang);
        document.title = currentLang === 'en-US'
            ? 'Floe · Quant Research Workbench'
            : 'Floe · 量化投研工作台';
        processSubtree(document.body);
    };

    document.addEventListener('DOMContentLoaded', function () {
        window.wbApplyLanguage(currentLang);
        const observer = new MutationObserver(function () {
            if (currentLang === 'en-US') {
                scheduleTranslate();
            }
        });
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: false
        });
    });
})();
