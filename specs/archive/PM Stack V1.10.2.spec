# -*- mode: python ; coding: utf-8 -*-

import sys
if sys.version_info < (3, 12):
    raise RuntimeError('Build with Python 3.12+: .venv-review/Scripts/python.exe -m PyInstaller')

import matplotlib
from PyInstaller.utils.hooks import collect_all, collect_submodules

review_datas = []
review_binaries = []
review_hiddenimports = collect_submodules('core.reviews')
for package in (
    'playwright', 'supabase', 'postgrest', 'supabase_auth', 'storage3',
    'realtime', 'supabase_functions',
):
    collected = collect_all(package)
    review_datas += collected[0]
    review_binaries += collected[1]
    review_hiddenimports += collected[2]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=review_binaries,
    datas=[
        ('config.json', '.'),
        ('core', 'core'),
        ('modules', 'modules'),
        ('scripts', 'scripts'),
        (matplotlib.get_data_path(), 'matplotlib'),
    ] + review_datas,
    hiddenimports=[
        'PyQt6.QtNetwork',
        'core.matrix_workspace',
        'pandas',
        'openpyxl',
        'xlsxwriter',
        'matplotlib',
        'matplotlib.pyplot',
        'matplotlib.backends.backend_agg',
        'numpy',
        'seaborn',
        'openai',
        'requests',
        'tqdm',
        'PIL',
        'PIL.Image',
        'PyQt6.sip',
        'contourpy',
        'fontTools',
    ] + review_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'test',
        'tests',
        'scipy',
        'pyarrow',
        'IPython',
        'jupyter',
        'jupyter_client',
        'jupyter_core',
        'zmq',
        'jedi',
        'parso',
        'pygments',
        'lxml',
        'win32com',
        'pythoncom',
        'pywintypes',
        'psutil',
    ],
    noarchive=False,
    optimize=0,
)

# Qt 6 resolves Windows' system ICU.  Some developer shells add an unrelated
# Poppler ICU build to PATH; PyInstaller may collect that as a root-level DLL,
# where it shadows the compatible system DLL and makes QtWidgets fail with
# WinError 127.  Never ship those accidental PATH-derived binaries.
_path_icu_names = {'icuuc.dll', 'icudt78.dll'}
a.binaries = [
    item for item in a.binaries
    if item[0].replace('\\', '/').lower() not in _path_icu_names
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PM Stack',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir='%TEMP%',
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
