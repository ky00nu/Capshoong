"""
겟슝 웹버전 (셀프호스트 · 소규모용)
- 서버가 yt-dlp로 받아 mp4로 변환해 사용자에게 전달
- 접근 코드(ACCESS_CODE), 동시 처리 제한, 영상 길이 제한, 오래된 파일 자동 정리
- 시스템 ffmpeg 사용 (Docker 이미지에 포함)

환경변수:
  PORT               (기본 8080)
  ACCESS_CODE        설정 시 이 코드가 있어야 사용 가능(지인 공유용). 비우면 무제한.
  MAX_CONCURRENT     동시 다운로드 수 (기본 2)
  MAX_DURATION_SEC   허용 최대 영상 길이 초 (기본 10800 = 3시간)
  FILE_TTL_SEC       받은 파일/작업 보관 시간 초 (기본 1800 = 30분)
  DOWNLOAD_DIR       임시 저장 경로 (기본 /tmp/getshoong-downloads)
"""
import os
import time
import uuid
import threading

from flask import Flask, request, jsonify, send_file, send_from_directory
import yt_dlp

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('PORT', '8080'))
ACCESS_CODE = os.environ.get('ACCESS_CODE', '').strip()
MAX_CONCURRENT = int(os.environ.get('MAX_CONCURRENT', '2'))
MAX_DURATION = int(os.environ.get('MAX_DURATION_SEC', str(3 * 3600)))
FILE_TTL = int(os.environ.get('FILE_TTL_SEC', str(30 * 60)))
DOWNLOAD_DIR = os.environ.get('DOWNLOAD_DIR', '/tmp/getshoong-downloads')

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=APP_DIR)
jobs = {}                     # job_id -> {status, progress, filename, error, ts, path}
_sem = threading.Semaphore(MAX_CONCURRENT)


def need_code():
    return bool(ACCESS_CODE)


def check_access(req):
    if not ACCESS_CODE:
        return True
    given = (req.headers.get('X-Access-Code') or req.args.get('code') or '').strip()
    return given == ACCESS_CODE


def deny():
    return jsonify({'error': '접근 코드가 필요합니다.', 'need_code': True}), 401


def yt_opts_base():
    return {
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'socket_timeout': 20, 'retries': 5, 'fragment_retries': 5,
        'extractor_retries': 3,
    }


@app.route('/')
def index():
    return send_from_directory(APP_DIR, 'index.html')


@app.route('/healthz')
def healthz():
    return jsonify({'ok': True, 'need_code': need_code()})


@app.route('/api/config')
def api_config():
    return jsonify({'need_code': need_code()})


@app.route('/api/info', methods=['POST'])
def api_info():
    if not check_access(request):
        return deny()
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'URL이 필요합니다.'}), 400

    opts = {**yt_opts_base(), 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({'error': f'영상 정보를 가져오지 못했습니다: {e}'}), 400

    dur = info.get('duration') or 0
    if MAX_DURATION and dur and dur > MAX_DURATION:
        mins = MAX_DURATION // 60
        return jsonify({'error': f'너무 긴 영상입니다. 최대 {mins}분까지 받을 수 있어요.'}), 400

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
        ex = quality_map.get(height)
        if ex is None:
            quality_map[height] = {'height': height, 'has_audio': has_audio, 'tbr': tbr}
        elif (has_audio and not ex['has_audio']) or (has_audio == ex['has_audio'] and tbr > ex['tbr']):
            quality_map[height] = {'height': height, 'has_audio': has_audio, 'tbr': tbr}

    qualities = sorted(quality_map.values(), key=lambda x: x['height'], reverse=True)
    quality_list = [{'label': '최고 화질 (자동)',
                     'value': 'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'}]
    labels = {144: '144p', 240: '240p', 360: '360p', 480: '480p',
              720: '720p (HD)', 1080: '1080p (FHD)', 1440: '1440p (2K)', 2160: '4K'}
    for q in qualities:
        h = q['height']
        quality_list.append({
            'label': labels.get(h, f'{h}p'),
            'value': f'bestvideo[height<={h}][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}]',
        })

    return jsonify({
        'title': info.get('title', ''),
        'thumbnail': info.get('thumbnail', ''),
        'duration': dur,
        'uploader': info.get('uploader', ''),
        'qualities': quality_list,
    })


@app.route('/api/download', methods=['POST'])
def api_download():
    if not check_access(request):
        return deny()
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    fmt = data.get('format', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best')
    title = data.get('title', 'video')
    if not url:
        return jsonify({'error': 'URL이 필요합니다.'}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {'status': 'queued', 'progress': 0, 'filename': None,
                    'error': None, 'ts': time.time(), 'path': None}

    def worker():
        acquired = _sem.acquire(timeout=600)
        if not acquired:
            jobs[job_id].update(status='error', error='서버가 혼잡합니다. 잠시 후 다시 시도해주세요.')
            return
        try:
            safe = ''.join(c for c in title if c.isalnum() or c in ' _-').strip()[:60] or 'video'
            out_tmpl = os.path.join(DOWNLOAD_DIR, f'{job_id}__{safe}.%(ext)s')

            def prog(d):
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

            opts = {
                **yt_opts_base(), 'format': fmt, 'outtmpl': out_tmpl,
                'merge_output_format': 'mp4', 'progress_hooks': [prog],
                'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
                'postprocessor_args': {'FFmpegVideoConvertor': [
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'aac', '-movflags', '+faststart']},
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                final = ydl.prepare_filename(info)
                base = os.path.splitext(final)[0]
                mp4 = base + '.mp4'
                if os.path.exists(mp4):
                    final = mp4
                jobs[job_id]['path'] = final
                jobs[job_id]['filename'] = f'{safe}.mp4'
                jobs[job_id]['status'] = 'done'
                jobs[job_id]['progress'] = 100
        except Exception as e:
            jobs[job_id].update(status='error', error=str(e))
        finally:
            _sem.release()

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/status/<job_id>')
def api_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': '작업을 찾을 수 없습니다.'}), 404
    return jsonify({k: job[k] for k in ('status', 'progress', 'filename', 'error')})


@app.route('/api/file/<job_id>')
def api_file(job_id):
    job = jobs.get(job_id)
    if not job or job.get('status') != 'done' or not job.get('path'):
        return jsonify({'error': '파일이 준비되지 않았습니다.'}), 404
    path = job['path']
    if not os.path.exists(path):
        return jsonify({'error': '파일이 만료되었습니다. 다시 받아주세요.'}), 404
    return send_file(path, as_attachment=True, download_name=job['filename'])


def _cleanup_loop():
    while True:
        time.sleep(300)
        now = time.time()
        for jid, job in list(jobs.items()):
            if now - job.get('ts', now) > FILE_TTL:
                p = job.get('path')
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                jobs.pop(jid, None)
        # 고아 파일 정리
        try:
            for f in os.listdir(DOWNLOAD_DIR):
                fp = os.path.join(DOWNLOAD_DIR, f)
                try:
                    if os.path.isfile(fp) and now - os.path.getmtime(fp) > FILE_TTL:
                        os.remove(fp)
                except OSError:
                    pass
        except OSError:
            pass


threading.Thread(target=_cleanup_loop, daemon=True).start()


if __name__ == '__main__':
    print(f'겟슝 웹버전 실행: 0.0.0.0:{PORT}  (접근코드 {"설정됨" if ACCESS_CODE else "없음"})')
    app.run(host='0.0.0.0', port=PORT, threaded=True)
