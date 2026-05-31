# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\tray_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('config.ini', '.'), ('src', 'src'), ('README.md', '.')],
    hiddenimports=['dnslib', 'dnslib.dns', 'pystray._win32', 'PIL', 'win32service', 'win32serviceutil', 'win32event', 'servicemanager'],
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
    a.binaries,
    a.datas,
    [],
    name='HomeGuard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
