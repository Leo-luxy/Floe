#!/usr/bin/env python3
"""将前端依赖的第三方 CSS/JS 静态化下载至 static/vendor/，彻底消除运行时对外部 CDN 的依赖。"""
import os
import urllib.request

VENDOR_FILES = [
    (
        'bootstrap.min.css',
        [
            'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
            'https://unpkg.com/bootstrap@5.3.0/dist/css/bootstrap.min.css',
            'https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css',
        ],
    ),
    (
        'bootstrap.bundle.min.js',
        [
            'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js',
            'https://unpkg.com/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/js/bootstrap.bundle.min.js',
        ],
    ),
    (
        'marked.min.js',
        [
            'https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js',
            'https://unpkg.com/marked@9.1.6/marked.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/marked/9.1.6/marked.min.js',
        ],
    ),
]


def fetch_vendor_assets(project_root: str):
    vendor_dir = os.path.join(project_root, 'static', 'vendor')
    os.makedirs(vendor_dir, exist_ok=True)
    for filename, urls in VENDOR_FILES:
        dest = os.path.join(vendor_dir, filename)
        if os.path.isfile(dest) and os.path.getsize(dest) > 5000:
            print(f'[SKIP] {filename} already exists ({os.path.getsize(dest)} bytes)')
            continue
        ok = False
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 Floe-Build/2.0'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                if len(data) > 5000:
                    with open(dest, 'wb') as fh:
                        fh.write(data)
                    print(f'[OK] {filename} <- {url} ({len(data)} bytes)')
                    ok = True
                    break
            except Exception as exc:
                print(f'[WARN] {url} failed: {exc}')
        if not ok:
            raise RuntimeError(f'Failed to download {filename} from all mirrors')


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    fetch_vendor_assets(root)
