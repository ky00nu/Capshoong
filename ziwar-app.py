import os
import sys
import glob
import threading
import subprocess


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


def _iter_app_bundles(base, max_depth=2):
    """base 아래에서 .app 번들을 찾음. 하위 폴더는 max_depth까지 내려가되,
    .app 내부로는 들어가지 않음(Adobe 등 폴더 안에 든 앱, Utilities 폴더 커버)."""
    found = []

    def walk(d, depth):
        try:
            entries = sorted(os.listdir(d), key=str.lower)
        except OSError:
            return
        for e in entries:
            p = os.path.join(d, e)
            if e.endswith('.app'):
                found.append(p)                      # .app 발견 → 내부로는 안 들어감
            elif depth < max_depth and os.path.isdir(p) and not os.path.islink(p):
                walk(p, depth + 1)

    walk(base, 0)
    return found


def list_apps():
    seen = set()
    apps = []
    for d in APP_DIRS:
        if not os.path.isdir(d):
            continue
        for p in _iter_app_bundles(d):
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
    apps.sort(key=lambda a: a['name'].lower())
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


def elevated_trash(paths):
    """관리자 권한으로 휴지통(~/.Trash)에 이동. root 소유 앱 등 권한 거부 항목 처리.
    암호 프롬프트는 osascript가 한 번만 표시. 완전 삭제가 아니라 이동이라 복구 가능."""
    import subprocess
    import shlex
    trash = os.path.join(HOME, '.Trash')
    parts = ['/bin/mkdir -p ' + shlex.quote(trash)]
    for p in paths:
        if os.path.lexists(p):
            parts.append('/bin/mv -f ' + shlex.quote(p) + ' ' + shlex.quote(trash + '/'))
    script = ' && '.join(parts)
    osa = 'do shell script "%s" with administrator privileges' % (
        script.replace('\\', '\\\\').replace('"', '\\"'))
    try:
        subprocess.run(['osascript', '-e', osa], check=True, capture_output=True)
    except Exception:
        pass  # 부분 실패 가능 → 아래에서 경로 존재로 성공/실패 판정
    trashed, failed = [], []
    for p in paths:
        if not os.path.lexists(p):
            trashed.append(p)
        else:
            failed.append({'path': p, 'error': '관리자 권한 삭제 실패(취소 또는 거부)'})
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

    def _safe_paths(paths):
        # 보호 경로 방어: 홈 라이브러리/앱 위치 밖은 거부
        allowed_roots = tuple(os.path.realpath(d) for d in APP_DIRS) + \
            (os.path.realpath(os.path.join(HOME, 'Library')),)
        safe = []
        for p in paths:
            rp = os.path.realpath(p)
            if rp.startswith(allowed_roots) and rp not in ('/', HOME):
                safe.append(p)
        return safe

    @app.route('/api/trash', methods=['POST'])
    def api_trash():
        data = request.get_json(silent=True) or {}
        safe = _safe_paths(data.get('paths') or [])
        trashed, failed = trash_paths(safe)
        return jsonify({'trashed': trashed, 'failed': failed,
                        'needs_auth': len(failed) > 0})

    @app.route('/api/trash-admin', methods=['POST'])
    def api_trash_admin():
        data = request.get_json(silent=True) or {}
        safe = _safe_paths(data.get('paths') or [])
        trashed, failed = elevated_trash(safe)
        return jsonify({'trashed': trashed, 'failed': failed})

    app.run(port=PORT, debug=False, use_reloader=False)


def _open_browser_when_ready():
    """서버 포트가 열리면 기본 브라우저로 지워 화면을 연다(번들에서 확실히 동작)."""
    import socket
    import time
    url = f'http://localhost:{PORT}'
    for _ in range(60):  # 최대 ~12초 대기
        try:
            with socket.create_connection(('127.0.0.1', PORT), 0.3):
                break
        except OSError:
            time.sleep(0.2)
    subprocess.Popen(['open', url])


import rumps


class ZiwarApp(rumps.App):
    def __init__(self):
        icon_path = resource_path('menubar.png')
        kwargs = {'quit_button': None}
        if os.path.isfile(icon_path):
            kwargs['icon'] = icon_path
            kwargs['template'] = True   # 다크/라이트 메뉴바 자동 대응
            kwargs['title'] = None
        super().__init__("지워", **kwargs)
        self.menu = [
            rumps.MenuItem("지워 화면 열기", callback=self._open_ui),
            None,
            rumps.MenuItem("종료", callback=self._quit),
        ]

    def _open_ui(self, _):
        subprocess.Popen(['open', f'http://localhost:{PORT}'])

    def _quit(self, _):
        rumps.quit_application()


def main():
    # Flask 서버는 백그라운드 스레드에서, 메뉴바 앱은 메인 스레드에서 실행
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    ZiwarApp().run()


if __name__ == '__main__':
    main()
