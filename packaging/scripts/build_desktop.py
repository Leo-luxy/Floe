#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Floe 跨平台桌面安装包一键构建脚本 (macOS .dmg + .tar.gz / Windows .zip / Linux .tar.gz)

用法：
    python packaging/scripts/build_desktop.py
产出物位于：dist/release/
"""
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, PROJECT_ROOT)
import version  # noqa: E402


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def detect_arch_tag() -> str:
    m = platform.machine().lower()
    if m in ('arm64', 'aarch64'):
        return 'arm64'
    return 'x64'


def build():
    ver = version.APP_VERSION
    arch = detect_arch_tag()
    spec_path = os.path.join(PROJECT_ROOT, 'packaging', 'pyinstaller', 'floe.spec')
    dist_root = os.path.join(PROJECT_ROOT, 'dist')
    release_dir = os.path.join(dist_root, 'release')
    os.makedirs(release_dir, exist_ok=True)

    print(f'[1/3] Running PyInstaller for Floe v{ver} ({sys.platform}-{arch})...')
    subprocess.run(
        [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', spec_path],
        cwd=PROJECT_ROOT,
        check=True,
    )

    artifacts = []

    if sys.platform == 'darwin':
        app_bundle = os.path.join(dist_root, 'Floe.app')
        if not os.path.isdir(app_bundle):
            raise RuntimeError(f'Expected macOS bundle not found: {app_bundle}')

        print('[2/3] Applying macOS Ad-hoc signature (prevents Apple Silicon damaged-app error)...')
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-', app_bundle], check=True)

        # 产出 1：给双击安装与 Homebrew Cask 使用的拖拽式 .dmg
        dmg_name = f'Floe-v{ver}-macos-{arch}.dmg'
        dmg_path = os.path.join(release_dir, dmg_name)
        if os.path.exists(dmg_path):
            os.remove(dmg_path)
        with tempfile.TemporaryDirectory() as staging:
            staged_app = os.path.join(staging, 'Floe.app')
            subprocess.run(['ditto', app_bundle, staged_app], check=True)
            os.symlink('/Applications', os.path.join(staging, 'Applications'))
            subprocess.run([
                'hdiutil', 'create',
                '-volname', f'Floe {ver}',
                '-srcfolder', staging,
                '-ov', '-format', 'UDZO',
                dmg_path,
            ], check=True)
        artifacts.append(dmg_path)

        # 产出 2：给 npm CLI 安装器直接免挂载解压使用的 .tar.gz
        tgz_name = f'Floe-v{ver}-macos-{arch}.tar.gz'
        tgz_path = os.path.join(release_dir, tgz_name)
        with tarfile.open(tgz_path, 'w:gz') as tf:
            tf.add(os.path.join(dist_root, 'Floe'), arcname='Floe')
        artifacts.append(tgz_path)

    elif os.name == 'nt':
        win_dir = os.path.join(dist_root, 'Floe')
        zip_name = f'Floe-v{ver}-windows-{arch}.zip'
        zip_path = os.path.join(release_dir, zip_name)
        print('[2/3] Archiving Windows portable package...')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(win_dir):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, dist_root)
                    zf.write(full, arcname=rel)
        artifacts.append(zip_path)

    else:
        lin_dir = os.path.join(dist_root, 'Floe')
        tgz_name = f'Floe-v{ver}-linux-{arch}.tar.gz'
        tgz_path = os.path.join(release_dir, tgz_name)
        print('[2/3] Archiving Linux package...')
        with tarfile.open(tgz_path, 'w:gz') as tf:
            tf.add(lin_dir, arcname='Floe')
        artifacts.append(tgz_path)

    # 生成 SHA256SUMS 片段
    sums_path = os.path.join(release_dir, f'SHA256SUMS-{sys.platform}-{arch}.txt')
    print('[3/3] Computing SHA256 checksums...')
    lines = []
    for art in artifacts:
        digest = sha256_file(art)
        line = f'{digest}  {os.path.basename(art)}'
        lines.append(line)
        print('  ', line)
    with open(sums_path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')

    print(f'\n✅ Build finished! Artifacts saved in: {release_dir}')


if __name__ == '__main__':
    build()
