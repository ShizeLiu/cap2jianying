# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('..\\scripts', 'jy_skill\\scripts'), ('..\\assets', 'jy_skill\\assets'), ('.\\overrides\\smart_zoomer.py', 'jy_skill\\overrides'), ('..\\scripts\\vendor\\pyJianYingDraft\\assets', 'jy_skill\\scripts\\vendor\\pyJianYingDraft\\assets')]
binaries = []
hiddenimports = ['difflib', 'asyncio', 'asyncio.events', 'asyncio.base_events', 'pymediainfo', 'uiautomation', 'comtypes', 'win32ctypes', 'pynput', 'pynput.mouse', 'pynput.keyboard', 'jy_wrapper', 'smart_zoomer', 'pyJianYingDraft']
tmp_ret = collect_all('tkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['recorder.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VideoRecorderOnly',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VideoRecorderOnly',
)
