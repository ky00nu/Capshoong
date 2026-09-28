# -*- mode: python ; coding: utf-8 -*-
# 줍숑 (YouTube 다운로더) PyInstaller 스펙.
#   빌드:  pyinstaller Jupshoong.spec
#   산출물: dist/줍숑.app
import shutil
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ffmpeg_path = shutil.which('ffmpeg')
ffprobe_path = shutil.which('ffprobe')

binaries_list = []
if ffmpeg_path:
    binaries_list.append((ffmpeg_path, '.'))
if ffprobe_path:
    binaries_list.append((ffprobe_path, '.'))

# yt_dlp_ejs는 선택 사항(없어도 대부분 동작). 미설치여도 빌드가 깨지지 않게 가드.
try:
    ejs_datas, ejs_binaries, ejs_hiddenimports = collect_all('yt_dlp_ejs')
except Exception:
    ejs_datas, ejs_binaries, ejs_hiddenimports = [], [], []
binaries_list += ejs_binaries

# 메뉴바 앱(rumps) + PyObjC 바인딩 포함
menubar_hidden = ['rumps', 'objc', 'Foundation', 'AppKit']
for pkg in ('rumps', 'objc', 'Foundation', 'AppKit'):
    try:
        menubar_hidden += collect_submodules(pkg)
    except Exception:
        pass

# menubar.png 있으면 datas에 포함(없어도 빌드는 진행 → 텍스트 폴백)
extra_datas = [('index.html', '.')]
if os.path.exists('menubar.png'):
    extra_datas.append(('menubar.png', '.'))

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries_list,
    datas=extra_datas + ejs_datas,
    hiddenimports=['flask', 'flask_cors', 'yt_dlp', 'yt_dlp.utils', 'yt_dlp.extractor', 'yt_dlp.downloader', 'yt_dlp.postprocessor'] + menubar_hidden + ejs_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'scipy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Getshoong',
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
    name='Getshoong',
)
app = BUNDLE(
    coll,
    name='겟슝.app',
    icon='AppIcon.icns',
    bundle_identifier='com.gravity.getshoong',
    info_plist={
        'CFBundleName': '겟슝',
        'CFBundleDisplayName': '겟슝',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSUIElement': True,
        'LSMinimumSystemVersion': '11.0',
    },
)
