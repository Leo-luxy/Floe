# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 跨平台打包规范 (macOS .app / Windows .exe / Linux binary)
用法：
    pyinstaller --noconfirm --clean packaging/pyinstaller/floe.spec
"""
import glob
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.abspath(os.path.join(SPEC_DIR, '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
import version as _floe_ver

# 严禁打入发布包的私密/本地缓存文件黑名单
EXCLUDED_ROOT_PY = {
    'trading_records.py',
    'watchlist.py',
}

datas = [
    (os.path.join(PROJECT_ROOT, 'templates'), 'templates'),
    (os.path.join(PROJECT_ROOT, 'static'), 'static'),
    (os.path.join(PROJECT_ROOT, 'packaging', 'icons'), os.path.join('packaging', 'icons')),
]

# 收集根目录与子目录业务 .py 脚本（供冻结态 --run-script 动态调度执行）
root_py_files = glob.glob(os.path.join(PROJECT_ROOT, '*.py'))
has_config_py = any(os.path.basename(p) == 'config.py' for p in root_py_files)
for py_file in root_py_files:
    bname = os.path.basename(py_file)
    if bname not in EXCLUDED_ROOT_PY:
        datas.append((py_file, '.'))
if not has_config_py:
    # 干净构建环境未带 config.py 时，确保把 config.example.py 自动打包为 config.py 兜底
    cfg_ex_path = os.path.join(PROJECT_ROOT, 'config.example.py')
    if os.path.isfile(cfg_ex_path):
        import shutil as _spec_shutil
        cfg_gen_path = os.path.join(PROJECT_ROOT, 'config.py')
        _spec_shutil.copyfile(cfg_ex_path, cfg_gen_path)
        datas.append((cfg_gen_path, '.'))

for subdir in ('api', 'Process', 'daily', 'weekly', 'shenwan_config', 'data_hub', os.path.join('data_hub', 'providers')):
    src_dir = os.path.join(PROJECT_ROOT, subdir)
    if os.path.isdir(src_dir):
        for py_file in glob.glob(os.path.join(src_dir, '*.py')):
            datas.append((py_file, subdir))

# stocks_filter 仅打包 .py 脚本，绝不打包本地运行产生的 .csv / .json 缓存
sf_dir = os.path.join(PROJECT_ROOT, 'stocks_filter')
if os.path.isdir(sf_dir):
    for py_file in glob.glob(os.path.join(sf_dir, '*.py')):
        datas.append((py_file, 'stocks_filter'))

# 第三方科学计算、HTTPS 根证书束与金融库内置资源文件及动态链接库
binaries = []
for pkg_data in ('certifi', 'akshare', 'tushare', 'py_mini_racer'):
    try:
        datas += collect_data_files(pkg_data)
    except Exception:
        pass

for pkg_bin in ('py_mini_racer', 'talib'):
    try:
        binaries += collect_dynamic_libs(pkg_bin)
    except Exception:
        pass

hiddenimports = [
    'certifi',
    'flask',
    'werkzeug',
    'jinja2',
    'webview',
    'pandas',
    'numpy',
    'scipy',
    'sklearn',
    'matplotlib',
    'matplotlib.backends.backend_agg',
    'seaborn',
    'talib',
    'talib.stream',
    'akshare',
    'tushare',
    'requests',
    'lxml',
    'lxml.etree',
    'lxml._elementpath',
    'ollama',
    'openpyxl',
    'PIL',
    'py_mini_racer',
]

try:
    hiddenimports += collect_submodules('webview')
except Exception:
    pass
try:
    hiddenimports += collect_submodules('data_hub')
except Exception:
    pass

icon_mac = os.path.join(PROJECT_ROOT, 'packaging', 'icons', 'floe.icns')
icon_win = os.path.join(PROJECT_ROOT, 'packaging', 'icons', 'floe.ico')

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'floe_app.py')],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest', 'IPython', 'notebook', 'jupyter', 'tkinter.test',
        'torch', 'torchvision', 'torchaudio', 'tensorflow', 'tensorboard', 'jax', 'jaxlib',
        'ultralytics', 'cv2', 'docx', 'pptx',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Floe' if os.name == 'nt' else 'floe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False if (sys.platform == 'darwin' or os.name == 'nt') else True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=icon_win if (os.name == 'nt' and os.path.isfile(icon_win)) else (
        icon_mac if (sys.platform == 'darwin' and os.path.isfile(icon_mac)) else None
    ),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Floe',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Floe.app',
        icon=icon_mac if os.path.isfile(icon_mac) else None,
        bundle_identifier='io.github.leoluxy.floe',
        info_plist={
            'CFBundleName': 'Floe',
            'CFBundleDisplayName': 'Floe',
            'CFBundleShortVersionString': _floe_ver.APP_VERSION,
            'CFBundleVersion': _floe_ver.APP_VERSION,
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
            'LSMinimumSystemVersion': '11.0',
            'NSAppTransportSecurity': {
                'NSAllowsLocalNetworking': True,
            },
        },
    )
