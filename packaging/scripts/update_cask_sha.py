#!/usr/bin/env python3
"""根据 GitHub Release 生成的 SHA256SUMS.txt 自动更新 Homebrew Cask (floe.rb) 的版本号与哈希值。"""
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, PROJECT_ROOT)
import version  # noqa: E402


def update_cask(sums_file: str):
    arm_sha = None
    x64_sha = None
    with open(sums_file, 'r', encoding='utf-8') as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            digest, filename = parts[0], parts[-1]
            if filename.endswith('-macos-arm64.dmg'):
                arm_sha = digest
            elif filename.endswith('-macos-x64.dmg'):
                x64_sha = digest

    if not arm_sha or not x64_sha:
        raise RuntimeError(f'Missing macOS dmg hashes in {sums_file} (arm64={arm_sha}, x64={x64_sha})')

    cask_path = os.path.join(PROJECT_ROOT, 'packaging', 'homebrew', 'Casks', 'floe.rb')
    with open(cask_path, 'r', encoding='utf-8') as fh:
        text = fh.read()

    text = re.sub(r'version\s+"[^"]+"', f'version "{version.APP_VERSION}"', text, count=1)
    text, count = re.subn(
        r'(sha256\s+arm:\s+)"[^"]+"(\s*,\s*\n\s*intel:\s+)"[^"]+"',
        rf'\g<1>"{arm_sha}"\g<2>"{x64_sha}"',
        text,
    )
    if count != 1:
        raise RuntimeError(f'Failed to locate sha256 arm/intel block in {cask_path}')

    with open(cask_path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    print(f'Updated {cask_path} -> v{version.APP_VERSION}\n  arm64: {arm_sha}\n  x64  : {x64_sha}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python packaging/scripts/update_cask_sha.py <path/to/SHA256SUMS.txt>')
        sys.exit(1)
    update_cask(sys.argv[1])
