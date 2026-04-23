# -*- mode: python ; coding: utf-8 -*-
import os

_spec_dir = os.path.dirname(os.path.abspath(SPEC))
_scripts = os.path.join(_spec_dir, "scripts")
_assets = os.path.join(_spec_dir, "assets")
_over = os.path.join(_spec_dir, "overrides", "smart_zoomer.py")
_pjd_assets = os.path.join(_scripts, "vendor", "pyJianYingDraft", "assets")
datas = [
    (_scripts, "jy_skill\\scripts"),
    (_assets, "jy_skill\\assets"),
    (_over, "jy_skill\\overrides"),
    (_pjd_assets, "jy_skill\\scripts\\vendor\\pyJianYingDraft\\assets"),
]
binaries = []
hiddenimports = ['difflib', 'asyncio', 'asyncio.events', 'asyncio.base_events', 'pymediainfo', 'uiautomation', 'comtypes', 'win32ctypes', 'pynput', 'pynput.mouse', 'pynput.keyboard', 'jy_wrapper', 'smart_zoomer', 'pyJianYingDraft']


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
