from flask import Blueprint, render_template, request, jsonify, current_app, send_file
from ..services.video_downloader import VideoDownloaderService, DownloadError
import os
import threading
import uuid
import time
import re
import shutil
import logging

logger = logging.getLogger(__name__)

youtube_bp = Blueprint('youtube', __name__)

JOBS = {}
JOBS_LOCK = threading.Lock()

MAX_CONCURRENT_DOWNLOADS = 3
download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)

JOB_TTL_SECONDS = 3600


def cleanup_old_jobs():
    now = time.time()
    to_remove = []
    with JOBS_LOCK:
        for job_id, job in JOBS.items():
            age = now - job.get('created_at', now)
            if age > JOB_TTL_SECONDS and job.get('status') in ('completed', 'error'):
                to_remove.append(job_id)

        for job_id in to_remove:
            job = JOBS.pop(job_id, {})
            file_path = job.get('path')
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass


def background_download(job_id, app, url, format_id, is_playlist):
    acquired = download_semaphore.acquire(timeout=60)
    if not acquired:
        with JOBS_LOCK:
            JOBS[job_id]['status'] = 'error'
            JOBS[job_id]['error'] = 'Too many downloads in progress. Please wait and try again.'
            JOBS[job_id]['category'] = 'rate_limited'
        return

    try:
        with app.app_context():
            with JOBS_LOCK:
                JOBS[job_id]['status'] = 'downloading'
                JOBS[job_id]['progress'] = 0

            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            cookies_path = os.path.join(base_dir, 'cookies.txt')
            cookies_file = cookies_path if os.path.exists(cookies_path) else None

            service = VideoDownloaderService(
                current_app.config['OUTPUT_FOLDER'],
                cookies_file=cookies_file
            )

            def progress_hook(d):
                try:
                    if d['status'] == 'downloading':
                        total = d.get('total_bytes') or d.get('total_bytes_estimate')
                        downloaded = d.get('downloaded_bytes', 0)
                        if total and total > 0:
                            p = min((downloaded / total) * 100, 99)
                            with JOBS_LOCK:
                                JOBS[job_id]['progress'] = p
                                JOBS[job_id]['speed'] = d.get('speed')
                                JOBS[job_id]['eta'] = d.get('eta')
                    elif d['status'] == 'finished':
                        with JOBS_LOCK:
                            JOBS[job_id]['progress'] = 95
                            JOBS[job_id]['status_text'] = 'Processing...'
                except Exception as e:
                    logger.debug(f"Progress hook error (non-fatal): {e}")

            if is_playlist:
                files = service.download_playlist(url, format_id, progress_hook=progress_hook)

                if not files:
                    raise DownloadError(
                        "No files were downloaded from the playlist. Some videos may be unavailable.",
                        category='not_found'
                    )

                playlist_dir = os.path.dirname(files[0])
                zip_path = shutil.make_archive(playlist_dir, 'zip', playlist_dir)
                shutil.rmtree(playlist_dir, ignore_errors=True)

                with JOBS_LOCK:
                    JOBS[job_id]['status'] = 'completed'
                    JOBS[job_id]['progress'] = 100
                    JOBS[job_id]['path'] = zip_path
                    JOBS[job_id]['filename'] = os.path.basename(zip_path)

            else:
                file_path = service.download_video(url, format_id, progress_hook=progress_hook)

                if not file_path or not os.path.exists(file_path):
                    raise DownloadError(
                        "Download completed but file was not found on disk.",
                        category='unknown',
                        retry_possible=True
                    )

                if os.path.getsize(file_path) == 0:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                    raise DownloadError(
                        "Downloaded file is empty. The source may be unavailable.",
                        category='not_found'
                    )

                with JOBS_LOCK:
                    JOBS[job_id]['status'] = 'completed'
                    JOBS[job_id]['progress'] = 100
                    JOBS[job_id]['path'] = file_path
                    JOBS[job_id]['filename'] = os.path.basename(file_path)

    except DownloadError as e:
        logger.error(f"Job {job_id} failed ({e.category}): {e}")
        with JOBS_LOCK:
            JOBS[job_id]['status'] = 'error'
            JOBS[job_id]['error'] = str(e)
            JOBS[job_id]['category'] = e.category
            JOBS[job_id]['retry_possible'] = e.retry_possible

    except Exception as e:
        msg = str(e)
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        msg = ansi_escape.sub('', msg)
        msg = msg.replace('ERROR:', '').strip()

        logger.error(f"Job {job_id} unexpected error: {msg}")
        with JOBS_LOCK:
            JOBS[job_id]['status'] = 'error'
            JOBS[job_id]['error'] = msg[:300] if len(msg) > 300 else msg
            JOBS[job_id]['category'] = 'unknown'
            JOBS[job_id]['retry_possible'] = True

    finally:
        download_semaphore.release()


def _validate_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    return url.startswith(('http://', 'https://')) and len(url) < 2048


@youtube_bp.route('/youtube')
def index():
    return render_template('youtube.html')


@youtube_bp.route('/api/youtube/info', methods=['POST'])
def get_info():
    cleanup_old_jobs()

    data = request.get_json()
    url = (data or {}).get('url', '').strip()

    if not _validate_url(url):
        return jsonify({'success': False, 'error': 'Please enter a valid URL'}), 400

    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cookies_path = os.path.join(base_dir, 'cookies.txt')
        cookies_file = cookies_path if os.path.exists(cookies_path) else None

        service = VideoDownloaderService(
            current_app.config['OUTPUT_FOLDER'],
            cookies_file=cookies_file
        )
        info = service.get_video_info(url)

        info['success'] = True
        return jsonify(info)

    except DownloadError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'category': e.category,
            'retry_possible': e.retry_possible
        }), 400

    except Exception as e:
        logger.error(f"get_info error: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to fetch video info: {str(e)[:200]}'
        }), 500


@youtube_bp.route('/api/youtube/download', methods=['POST'])
def download():
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    format_id = data.get('format_id')
    is_playlist = data.get('is_playlist', data.get('playlist', False))

    if not _validate_url(url):
        return jsonify({'success': False, 'error': 'Please enter a valid URL'}), 400

    job_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[job_id] = {
            'status': 'pending',
            'progress': 0,
            'created_at': time.time(),
            'url': url,
        }

    app = current_app._get_current_object()

    thread = threading.Thread(
        target=background_download,
        args=(job_id, app, url, format_id, is_playlist),
        daemon=True,
        name=f"download-{job_id[:8]}"
    )
    thread.start()

    return jsonify({'success': True, 'job_id': job_id})


@youtube_bp.route('/api/youtube/status/<job_id>')
def job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        return jsonify({'error': 'Job not found'}), 404

    response = {
        'status': job.get('status'),
        'progress': job.get('progress', 0),
    }

    if job.get('status') == 'completed':
        response['filename'] = job.get('filename')

    if job.get('status') == 'error':
        response['error'] = job.get('error', 'Unknown error')
        response['category'] = job.get('category', 'unknown')
        response['retry_possible'] = job.get('retry_possible', True)

    if job.get('speed'):
        response['speed'] = job['speed']
    if job.get('eta'):
        response['eta'] = job['eta']
    if job.get('status_text'):
        response['status_text'] = job['status_text']

    return jsonify(response)


@youtube_bp.route('/api/youtube/download-file/<job_id>')
@youtube_bp.route('/api/youtube/download_file/<job_id>')
def download_file(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job or job.get('status') != 'completed':
        return jsonify({'error': 'File not ready'}), 404

    file_path = job.get('path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found on disk'}), 404

    return send_file(file_path, as_attachment=True, download_name=job.get('filename'))

@youtube_bp.route('/api/youtube/smart-rename/<job_id>', methods=['POST'])
def smart_rename_youtube(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job or job.get('status') != 'completed':
        return jsonify({'error': 'File not ready'}), 404

    file_path = job.get('path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found on disk'}), 404

    try:
        from ..services.llm import LLMService
        service = LLMService()
        filename = job.get('filename')
        
        prompt = f"You are a file renamer. Extract a clean, highly readable, and professional title from this raw filename: '{filename}'. Remove generic phrases like 'official music video', random alphanumeric strings, hashes, IDs, 'hd', '1080p', underscores, and extensions. Keep author/artist names if present. Return ONLY the clean name, nothing else. DO NOT return the extension."
        
        payload = {
            "model": "ministral-3-8b-instruct-2512",
            "system_prompt": "You are a smart filename cleaner.",
            "input": prompt,
            "temperature": 0.1,
            "stream": False
        }
        
        if 'LLM_FORMATTING_MODEL' in os.environ:
            payload["model"] = os.environ.get("LLM_FORMATTING_MODEL")
            
        result = service._send_request(payload)
        
        clean_name = filename
        if 'output' in result and len(result['output']) > 0:
            for item in result['output']:
                if item.get('type') == 'message':
                    clean_name = item['content'].strip()
                    break
        
        ext = os.path.splitext(filename)[1]
        if not clean_name.endswith(ext):
            clean_name += ext
            
        clean_name = re.sub(r'[\\/*?:"<>|]', "", clean_name)
            
        new_path = os.path.join(os.path.dirname(file_path), clean_name)
        os.rename(file_path, new_path)
        
        with JOBS_LOCK:
            job['path'] = new_path
            job['filename'] = clean_name
            
        return jsonify({'success': True, 'new_name': clean_name})
        
    except Exception as e:
        logger.error(f"Rename error: {e}")
        return jsonify({'error': f'Failed to rename: {str(e)}'}), 500
