# Floe Desktop Packaging & Distribution Guide

本文档说明如何从源码构建 **Floe** 的跨平台原生桌面安装包（macOS `.dmg` / Windows `.zip` / Linux `.AppImage`），以及如何维护 Homebrew Cask 与 npm 分发包。

---

## 1. 本地运行与环境自检

```bash
# 安装依赖（Python 3.10 / 3.11）
python -m pip install -r requirements.txt
python -m pip install pywebview pyinstaller

# 启动原生独立桌面窗口
python floe_app.py

# 或启动浏览器模式
python floe_app.py --web

# 运行环境与配置自检
python floe_app.py --doctor
```

---

## 2. 本地构建桌面安装包

```bash
python packaging/scripts/build_desktop.py
```

构建完成后，对应当前操作系统的安装包与 `SHA256SUMS` 校验文件将输出至 `dist/release/` 目录。

---

## 3. GitHub Actions 四架构自动构建

推送 `v*` 版本标签后，`.github/workflows/release-floe.yml` 将自动并行构建：
- `Floe-vX.Y.Z-macos-arm64.dmg` & `.tar.gz`（Apple Silicon）
- `Floe-vX.Y.Z-macos-x64.dmg` & `.tar.gz`（Intel Mac）
- `Floe-vX.Y.Z-windows-x64.zip`（Windows x64 便携版）
- `Floe-vX.Y.Z-linux-x86_64.AppImage` & `.tar.gz`（Linux x64）
- `SHA256SUMS.txt`

---

## 4. Homebrew Cask 更新与安装

下载 Release 生成的 `SHA256SUMS.txt` 后，运行脚本自动回填 macOS 双架构哈希值：

```bash
python packaging/scripts/update_cask_sha.py path/to/SHA256SUMS.txt
```

将更新后的 `packaging/homebrew/Casks/floe.rb` 同步至 `Leo-luxy/homebrew-tap` 仓库的 `Casks/floe.rb`。用户安装命令：

```bash
brew tap Leo-luxy/tap
brew install --cask floe
```

---

## 5. npm 跨平台启动器发布与安装

```bash
cd packaging/npm
npm login --registry=https://registry.npmjs.org
npm pack --dry-run
npm publish --access public --registry=https://registry.npmjs.org
```

用户全局安装与运行命令：

```bash
npm install -g @leo-luxy/floe
floe
```
