# -*- mode: python ; coding: utf-8 -*-

import matplotlib

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.json', '.'),
        ('core', 'core'),
        ('modules', 'modules'),
        ('scripts', 'scripts'),
        (matplotlib.get_data_path(), 'matplotlib'),
    ],
    hiddenimports=[
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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'test',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PM Stack V1.9',
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
