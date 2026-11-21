#!/usr/bin/env node
/**
 * Floe跨平台命令行启动器 (macOS / Windows / Linux)
 * 首次运行时自动按当前操作系统与架构拉取 GitHub Release 预编译二进制包并缓存至本机，
 * 后续运行零等待秒开原生桌面窗口（或传 --web 启动浏览器模式）。
 */
'use strict';

const { spawn } = require('child_process');
const { ensureBinaryInstalled } = require('../lib/installer');

async function main() {
  const userArgs = process.argv.slice(2);
  const pkg = require('../package.json');

  if (userArgs.includes('--npm-version')) {
    console.log(`Floe npm launcher v${pkg.version}`);
    process.exit(0);
  }

  try {
    const exePath = await ensureBinaryInstalled(pkg.version);
    const env = Object.assign({}, process.env, {
      FLOE_INSTALL_CHANNEL: 'npm',
      FLOE_NPM_WRAPPER: '1',
    });

    const child = spawn(exePath, userArgs, {
      stdio: 'inherit',
      env,
    });

    child.on('exit', (code) => {
      process.exit(code === null ? 0 : code);
    });
  } catch (err) {
    console.error(`\n[Floe] 启动或下载预编译运行包失败: ${err.message}`);
    console.error('提示：若国内网络直连 GitHub Release 较慢，可设置镜像前缀重试：');
    console.error('  FLOE_GITHUB_MIRROR=https://ghfast.top/ floe\n');
    process.exit(1);
  }
}

main();
