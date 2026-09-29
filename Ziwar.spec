# -*- mode: python ; coding: utf-8 -*-
# 지워 (맥 앱 클리너) PyInstaller 스펙.
#   빌드:  pyinstaller Ziwar.spec
#   산출물: dist/지워.app
# 빌드 폴더에는 app.py / index.html / icon.png / AppIcon.icns 가 있어야 합니다.
from PyInstaller.utils.hooks import collect_submodules

import os as _os
hidden = ['flask', 'rumps', 'objc', 'Foundation', 'AppKit', 'CoreFoundation']
# PyObjC 프레임워크 바인딩 + rumps를 넉넉히 포함 (누락 시 런타임 ImportError 방지)
for pkg in ('rumps', 'objc', 'Foundation', 'AppKit'):
    try:
        hidden += collect_submodules(pkg)
    except Exception:
        pass

_datas = [('index.html', '.'), ('icon.png', '.')]
if _os.path.exists('menubar.png'):
    _datas.append(('menubar.png', '.'))

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'scipy', 'yt_dlp'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Ziwar',
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
    icon=['AppIcon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Ziwar',
)
app = BUNDLE(
    coll,
    name='지워.app',
    icon='AppIcon.icns',
    bundle_identifier='com.gravity.ziwar',
    info_plist={
        'CFBundleName': '지워',
        'CFBundleDisplayName': '지워',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSUIElement': True,
        'LSMinimumSystemVersion': '11.0',
    },
)
