import os
import sys
import threading
import subprocess


def resource_path(relative):
    """Get path to resource, works in dev and PyInstaller bundle."""
    if getattr(sys, '_MEIPASS', None):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.dirname(__file__), relative)


def get_downloads_dir():
    return os.path.join(os.path.expanduser('~'), 'Downloads', 'YTDownloader')


# Patch environment so yt-dlp can find bundled ffmpeg
def setup_ffmpeg():
    bundled = resource_path('ffmpeg')
    if os.path.isfile(bundled):
        os.environ['PATH'] = os.path.dirname(bundled) + ':' + os.environ.get('PATH', '')


PORT = 7777


def run_server():
    os.environ['YT_DL_DOWNLOADS'] = get_downloads_dir()
    os.environ['YT_DL_STATIC'] = resource_path('.')

    setup_ffmpeg()

    from flask import Flask, request, jsonify, send_file, send_from_directory
    from flask_cors import CORS
    import yt_dlp
    import uuid

    DOWNLOAD_DIR = get_downloads_dir()
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    STATIC_DIR = resource_path('.')

    app = Flask(__name__, static_folder=STATIC_DIR)
    CORS(app)

    jobs = {}

    def yt_dlp_opts_base():
        opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 20,
            'retries': 5,
            'fragment_retries': 5,
            'extractor_retries': 3,
        }
        ffmpeg_loc = resource_path('ffmpeg')
        if os.path.isfile(ffmpeg_loc):
            opts['ffmpeg_location'] = os.path.dirname(ffmpeg_loc)
        return opts

    @app.route('/')
    def index():
        return send_from_directory(STATIC_DIR, 'index.html')

    @app.route('/api/info', methods=['POST'])
    def get_info():
        data = request.get_json()
        url = data.get('url', '').strip()
        if not url:
            return jsonify({'error': 'URL이 필요합니다.'}), 400

        opts = {**yt_dlp_opts_base(), 'skip_download': True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            return jsonify({'error': f'영상 정보를 가져오지 못했습니다: {str(e)}'}), 400

        formats = info.get('formats', [])
        quality_map = {}
        for f in formats:
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            height = f.get('height')
            if not height or vcodec == 'none':
                continue
            has_audio = acodec != 'none'
            tbr = f.get('tbr') or 0
            existing = quality_map.get(height)
            if existing is None:
                quality_map[height] = {'height': height, 'has_audio': has_audio, 'tbr': tbr}
            elif (has_audio and not existing['has_audio']) or (has_audio == existing['has_audio'] and tbr > existing['tbr']):
                quality_map[height] = {'height': height, 'has_audio': has_audio, 'tbr': tbr}

        qualities = sorted(quality_map.values(), key=lambda x: x['height'], reverse=True)
        quality_list = [{'label': '최고 화질 (자동)', 'value': 'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'}]
        labels = {144: '144p', 240: '240p', 360: '360p', 480: '480p', 720: '720p (HD)', 1080: '1080p (FHD)', 1440: '1440p (2K)', 2160: '4K'}
        for q in qualities:
            h = q['height']
            label = labels.get(h, f'{h}p')
            fmt = f'bestvideo[height<={h}][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}]'
            quality_list.append({'label': label, 'value': fmt})

        return jsonify({
            'title': info.get('title', ''),
            'thumbnail': info.get('thumbnail', ''),
            'duration': info.get('duration', 0),
            'uploader': info.get('uploader', ''),
            'qualities': quality_list,
        })

    @app.route('/api/download', methods=['POST'])
    def start_download():
        data = request.get_json()
        url = data.get('url', '').strip()
        fmt = data.get('format', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best')
        title = data.get('title', 'video')

        if not url:
            return jsonify({'error': 'URL이 필요합니다.'}), 400

        job_id = str(uuid.uuid4())
        jobs[job_id] = {'status': 'pending', 'progress': 0, 'filename': None, 'error': None}

        def do_download():
            safe_title = ''.join(c for c in title if c.isalnum() or c in ' _-').strip()[:60] or 'video'
            out_template = os.path.join(DOWNLOAD_DIR, f'{safe_title}.%(ext)s')

            def progress_hook(d):
                if d['status'] == 'downloading':
                    pct = d.get('_percent_str', '0%').strip().replace('%', '')
                    try:
                        jobs[job_id]['progress'] = float(pct)
                    except ValueError:
                        pass
                    jobs[job_id]['status'] = 'downloading'
                elif d['status'] == 'finished':
                    jobs[job_id]['progress'] = 95
                    jobs[job_id]['status'] = 'converting'

            def pp_hook(d):
                if d['status'] == 'started':
                    jobs[job_id]['status'] = 'converting'
                elif d['status'] == 'finished':
                    jobs[job_id]['progress'] = 100

            opts = {
                **yt_dlp_opts_base(),
                'format': fmt,
                'outtmpl': out_template,
                'merge_output_format': 'mp4',
                'progress_hooks': [progress_hook],
                'postprocessor_hooks': [pp_hook],
                'postprocessors': [
                    {
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4',
                    },
                ],
                'postprocessor_args': {
                    'FFmpegVideoConvertor': ['-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-movflags', '+faststart'],
                },
            }

            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    final_path = ydl.prepare_filename(info)
                    base = os.path.splitext(final_path)[0]
                    mp4_path = base + '.mp4'
                    if os.path.exists(mp4_path):
                        final_path = mp4_path
                    elif not os.path.exists(final_path):
                        for f in os.listdir(DOWNLOAD_DIR):
                            if f.startswith(safe_title):
                                final_path = os.path.join(DOWNLOAD_DIR, f)
                                break
                    jobs[job_id]['filename'] = os.path.basename(final_path)
                    jobs[job_id]['status'] = 'done'
            except Exception as e:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = str(e)

        threading.Thread(target=do_download, daemon=True).start()
        return jsonify({'job_id': job_id})

    @app.route('/api/status/<job_id>')
    def job_status(job_id):
        job = jobs.get(job_id)
        if not job:
            return jsonify({'error': '작업을 찾을 수 없습니다.'}), 404
        return jsonify(job)

    @app.route('/api/file/<job_id>')
    def download_file(job_id):
        job = jobs.get(job_id)
        if not job or job['status'] != 'done' or not job['filename']:
            return jsonify({'error': '파일이 준비되지 않았습니다.'}), 404
        filepath = os.path.join(DOWNLOAD_DIR, job['filename'])
        if not os.path.exists(filepath):
            return jsonify({'error': '파일을 찾을 수 없습니다.'}), 404
        return send_file(filepath, as_attachment=True, download_name=job['filename'])

    @app.route('/api/open-folder', methods=['POST'])
    def open_folder():
        subprocess.Popen(['open', DOWNLOAD_DIR])
        return jsonify({'ok': True})

    app.run(port=PORT, debug=False, use_reloader=False, threaded=True)


def _open_browser_when_ready():
    """서버 포트가 열리면 기본 브라우저로 다운로드 화면을 연다(번들에서 확실히 동작)."""
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


class GetshoongApp(rumps.App):
    def __init__(self):
        icon_path = resource_path('menubar.png')
        kwargs = {'quit_button': None}
        if os.path.isfile(icon_path):
            kwargs['icon'] = icon_path
            kwargs['template'] = False  # 겟슝 캐릭터 컬러 아이콘(단색 실루엣 방지)
            kwargs['title'] = None
        super().__init__("겟슝", **kwargs)
        self.menu = [
            rumps.MenuItem("다운로드 화면 열기", callback=self._open_ui),
            None,
            rumps.MenuItem("다운로드 폴더 열기", callback=self._open_folder),
            None,
            rumps.MenuItem("종료", callback=self._quit),
        ]

    def _open_ui(self, _):
        subprocess.Popen(['open', f'http://localhost:{PORT}'])

    def _open_folder(self, _):
        d = get_downloads_dir()
        os.makedirs(d, exist_ok=True)
        subprocess.Popen(['open', d])

    def _quit(self, _):
        rumps.quit_application()


def main():
    # Flask 서버는 백그라운드 스레드에서, 메뉴바 앱은 메인 스레드에서 실행
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    GetshoongApp().run()


if __name__ == '__main__':
    main()
