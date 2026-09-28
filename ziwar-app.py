import os
import sys
import glob
import signal
import threading
import webbrowser


def resource_path(relative):
    """Get path to resource, works in dev and PyInstaller bundle."""
    if getattr(sys, '_MEIPASS', None):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.dirname(__file__), relative)


HOME = os.path.expanduser('~')
PORT = 7788

# 스캔할 앱 위치 (시스템 기본 앱이 있는 /System/Applications 은 제외)
APP_DIRS = ['/Applications', os.path.join(HOME, 'Applications')]

# 절대 삭제 대상에서 제외 (자기 자신 + 필수 도구)
PROTECTED_BUNDLE_PREFIXES = ('com.apple.',)
PROTECTED_NAMES = {'지워', 'Ziwar', 'Finder', 'Safari'}


def _plist_get(app_path, key):
    plist = os.path.join(app_path, 'Contents', 'Info.plist')
    if not os.path.isfile(plist):
        return None
    try:
        import plistlib
        with open(plist, 'rb') as f:
            data = plistlib.load(f)
        return data.get(key)
    except Exception:
        return None


def app_meta(app_path):
    name = os.path.splitext(os.path.basename(app_path))[0]
    bid = _plist_get(app_path, 'CFBundleIdentifier') or ''
    ver = _plist_get(app_path, 'CFBundleShortVersionString') or ''
    return {'name': name, 'path': app_path, 'bundle_id': bid, 'version': ver}


def list_apps():
    seen = set()
    apps = []
    for d in APP_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            entries = sorted(os.listdir(d), key=str.lower)
        except OSError:
            continue
        for entry in entries:
            if not entry.endswith('.app'):
                continue
            p = os.path.join(d, entry)
            if p in seen:
                continue
            seen.add(p)
            m = app_meta(p)
            bid = (m['bundle_id'] or '').lower()
            if bid.startswith(PROTECTED_BUNDLE_PREFIXES):
                continue
            if m['name'] in PROTECTED_NAMES:
                continue
            apps.append(m)
    return apps


def dir_size(path):
    total = 0
    if os.path.islink(path):
        try:
            return os.lstat(path).st_size
        except OSError:
            return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.lstat(fp).st_size
            except OSError:
                pass
    return total


def _add(items, seen, path, kind):
    if not path or path in seen:
        return
    if not os.path.lexists(path):
        return
    seen.add(path)
    items.append({
        'path': path,
        'kind': kind,
        'size': dir_size(path),
    })


def related_files(app_path):
    """AppCleaner 스타일: 번들ID/앱이름으로 연관 파일을 표준 위치에서 검색."""
    m = app_meta(app_path)
    bid = m['bundle_id']
    name = m['name']
    L = os.path.join(HOME, 'Library')

    items = []
    seen = set()

    # 앱 본체
    _add(items, seen, app_path, '앱 본체')

    # 번들 ID 기반 (가장 신뢰도 높음)
    if bid:
        candidates = [
            (os.path.join(L, 'Application Support', bid), '지원 파일'),
            (os.path.join(L, 'Caches', bid), '캐시'),
            (os.path.join(L, 'Preferences', bid + '.plist'), '환경설정'),
            (os.path.join(L, 'Containers', bid), '컨테이너'),
            (os.path.join(L, 'Saved Application State', bid + '.savedState'), '저장된 상태'),
            (os.path.join(L, 'HTTPStorages', bid), '웹 저장소'),
            (os.path.join(L, 'HTTPStorages', bid + '.binarycookies'), '쿠키'),
            (os.path.join(L, 'WebKit', bid), 'WebKit 데이터'),
            (os.path.join(L, 'Cookies', bid + '.binarycookies'), '쿠키'),
            (os.path.join(L, 'Logs', bid), '로그'),
            (os.path.join(L, 'Application Scripts', bid), '앱 스크립트'),
        ]
        for p, kind in candidates:
            _add(items, seen, p, kind)

        # glob 패턴 (환경설정 변형, LaunchAgents, ByHost, Group Containers 등)
        globs = [
            (os.path.join(L, 'Preferences', bid + '*.plist'), '환경설정'),
            (os.path.join(L, 'Preferences', 'ByHost', bid + '*.plist'), '환경설정(ByHost)'),
            (os.path.join(L, 'LaunchAgents', bid + '*.plist'), '실행 항목'),
            (os.path.join(L, 'Group Containers', '*' + bid + '*'), '그룹 컨테이너'),
            (os.path.join(L, 'Containers', '*' + bid + '*'), '컨테이너'),
        ]
        for pattern, kind in globs:
            for p in glob.glob(pattern):
                _add(items, seen, p, kind)

    # 앱 이름 기반 (번들ID로 못 찾은 흔적 보완)
    if name:
        name_candidates = [
            (os.path.join(L, 'Application Support', name), '지원 파일'),
            (os.path.join(L, 'Caches', name), '캐시'),
            (os.path.join(L, 'Logs', name), '로그'),
        ]
        for p, kind in name_candidates:
            _add(items, seen, p, kind)

    total = sum(i['size'] for i in items)
    return {'app': m, 'items': items, 'total': total}


def trash_paths(paths):
    """Foundation NSFileManager 로 휴지통 이동 (완전 삭제 아님, 복구 가능)."""
    from Foundation import NSFileManager, NSURL
    fm = NSFileManager.defaultManager()
    trashed, failed = [], []
    for p in paths:
        if not os.path.lexists(p):
            trashed.append(p)  # 이미 없음 = 성공 취급
            continue
        try:
            url = NSURL.fileURLWithPath_(p)
            ok, _res, err = fm.trashItemAtURL_resultingItemURL_error_(url, None, None)
            if ok:
                trashed.append(p)
            else:
                msg = str(err.localizedDescription()) if err else '알 수 없는 오류'
                failed.append({'path': p, 'error': msg})
        except Exception as e:
            failed.append({'path': p, 'error': str(e)})
    return trashed, failed


def app_icon_png(app_path, size=64):
    """앱 아이콘을 PNG bytes 로 반환 (실패 시 None)."""
    try:
        from AppKit import NSWorkspace, NSBitmapImageRep
        from Foundation import NSMakeSize
        img = NSWorkspace.sharedWorkspace().iconForFile_(app_path)
        if img is None:
            return None
        img.setSize_(NSMakeSize(size, size))
        tiff = img.TIFFRepresentation()
        if tiff is None:
            return None
        rep = NSBitmapImageRep.imageRepWithData_(tiff)
        # NSBitmapImageFileTypePNG == 4
        png = rep.representationUsingType_properties_(4, {})
        if png is None:
            return None
        return bytes(png)
    except Exception:
        return None


def run_server():
    from flask import Flask, request, jsonify, send_from_directory, Response

    STATIC_DIR = resource_path('.')
    app = Flask(__name__, static_folder=STATIC_DIR)

    @app.route('/')
    def index():
        return send_from_directory(STATIC_DIR, 'index.html')

    @app.route('/api/apps')
    def api_apps():
        return jsonify({'apps': list_apps()})

    @app.route('/api/icon')
    def api_icon():
        path = request.args.get('path', '')
        if not path or not os.path.isdir(path):
            return ('', 204)
        png = app_icon_png(path)
        if not png:
            return ('', 204)
        return Response(png, mimetype='image/png',
                        headers={'Cache-Control': 'max-age=3600'})

    @app.route('/api/scan', methods=['POST'])
    def api_scan():
        data = request.get_json(silent=True) or {}
        path = (data.get('path') or '').strip()
        if not path or not path.endswith('.app') or not os.path.isdir(path):
            return jsonify({'error': '앱을 찾을 수 없습니다.'}), 400
        try:
            return jsonify(related_files(path))
        except Exception as e:
            return jsonify({'error': f'스캔 실패: {e}'}), 500

    @app.route('/api/trash', methods=['POST'])
    def api_trash():
        data = request.get_json(silent=True) or {}
        paths = data.get('paths') or []
        # 보호 경로 방어: 홈 라이브러리/앱 위치 밖은 거부
        allowed_roots = tuple(os.path.realpath(d) for d in APP_DIRS) + \
            (os.path.realpath(os.path.join(HOME, 'Library')),)
        safe = []
        for p in paths:
            rp = os.path.realpath(p)
            if rp.startswith(allowed_roots) and rp not in ('/', HOME):
                safe.append(p)
        trashed, failed = trash_paths(safe)
        return jsonify({'trashed': trashed, 'failed': failed})

    app.run(port=PORT, debug=False, use_reloader=False)


def main():
    signal.signal(signal.SIGINT, lambda *_: os._exit(0))
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))

    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    import time
    time.sleep(1.5)
    webbrowser.open(f'http://localhost:{PORT}')

    print('지워가 실행 중입니다.')
    print(f'브라우저에서 http://localhost:{PORT} 에 접속하세요.')
    print('종료하려면 이 앱을 닫으세요.')

    try:
        t.join()
    except KeyboardInterrupt:
        os._exit(0)


if __name__ == '__main__':
    main()
