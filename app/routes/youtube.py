from flask import Blueprint, render_template, request, jsonify, current_app, send_file
from ..services.video_downloader import VideoDownloaderService
import os
import threading
import uuid
import time

youtube_bp = Blueprint('youtube', __name__)

# Simple in-memory job store
# { job_id: { status: 'pending'|'downloading'|'completed'|'error', progress: int, filename: str, error: str, path: str } }
JOBS = {}

def background_download(job_id, app, url, format_id, is_playlist):
    with app.app_context():
        try:
            JOBS[job_id]['status'] = 'downloading'
            JOBS[job_id]['progress'] = 0
            
            service = VideoDownloaderService(current_app.config['OUTPUT_FOLDER'])
            
            def progress_hook(d):
                if d['status'] == 'downloading':
                    try:
                        total = d.get('total_bytes') or d.get('total_bytes_estimate')
                        downloaded = d.get('downloaded_bytes', 0)
                        if total:
                            p = (downloaded / total) * 100
                            JOBS[job_id]['progress'] = p
                    except:
                        pass
                elif d['status'] == 'finished':
                    JOBS[job_id]['progress'] = 100 # Phase 1 done (download), might still merge

            file_path = service.download_video(url, format_id, is_playlist, progress_hook=progress_hook)
            
            # Verify file exists and is not empty
            if not file_path or not os.path.exists(file_path):
                raise Exception("Download failed: File not found")
            
            if os.path.getsize(file_path) == 0:
                # Try to remove empty file
                try: 
                    os.remove(file_path)
                except: 
                    pass
                raise Exception("Download failed: File is empty")

            JOBS[job_id]['status'] = 'completed'
            JOBS[job_id]['progress'] = 100
            JOBS[job_id]['path'] = file_path
            JOBS[job_id]['filename'] = os.path.basename(file_path)
            
        except Exception as e:
            msg = str(e)
            # Remove ANSI color codes
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            msg = ansi_escape.sub('', msg)
            # Remove common prefixes
            msg = msg.replace('ERROR:', '').strip()
            
            print(f"Job {job_id} failed: {msg}") 
            JOBS[job_id]['status'] = 'error'
            JOBS[job_id]['error'] = msg

@youtube_bp.route('/youtube')
def index():
    return render_template('youtube.html')

@youtube_bp.route('/api/youtube/info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        service = VideoDownloaderService(current_app.config['OUTPUT_FOLDER'])
        info = service.get_video_info(url)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@youtube_bp.route('/api/youtube/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    is_playlist = data.get('is_playlist', False)
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
        
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        'status': 'pending',
        'progress': 0,
        'created_at': time.time()
    }
    
    # Pass actual app object for context
    app = current_app._get_current_object()
    
    thread = threading.Thread(
        target=background_download, 
        args=(job_id, app, url, format_id, is_playlist)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'job_id': job_id})

@youtube_bp.route('/api/youtube/status/<job_id>')
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)

@youtube_bp.route('/api/youtube/download_file/<job_id>')
def download_file(job_id):
    job = JOBS.get(job_id)
    if not job or job['status'] != 'completed':
        return jsonify({'error': 'File not ready'}), 404
        
    return send_file(job['path'], as_attachment=True, download_name=job['filename'])
