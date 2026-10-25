import os
import time
from flask import jsonify, current_app

conversion_jobs = {}

def api_response(data=None, error=None, success=True):
    return jsonify({'success': success, 'data': data, 'error': error})

def touch_file(file_id):
    job = conversion_jobs.get(file_id)
    if not job:
        return
    job['created_at'] = time.time()
    path = job.get('input_path')
    if path and os.path.exists(path):
        try:
            os.utime(path, None)
        except OSError:
            pass

def file_expiry(file_id):
    job = conversion_jobs.get(file_id) or {}
    path = job.get('input_path')
    hours = current_app.config.get('CLEANUP_AFTER_HOURS', 1)
    mtime = os.path.getmtime(path) if path and os.path.exists(path) else time.time()
    expires_at = mtime + hours * 3600
    return {'file_id': file_id, 'expires_at': int(expires_at * 1000), 'ttl_seconds': max(0, int(expires_at - time.time()))}

def register_result_file(path, filename=None):
    from ..utils.file_handler import generate_file_id
    file_id = generate_file_id()
    conversion_jobs[file_id] = {
        'status': 'uploaded',
        'input_path': path,
        'original_filename': filename or os.path.basename(path),
        'file_type': 'document',
        'output_formats': get_output_formats_for_type('document'),
        'progress': 0,
        'created_at': time.time(),
    }
    return file_id

def unique_output_base(folder, base_name, suffix, extensions=('.pdf', '.zip', '.png', '.jpg')):
    candidate = f"{base_name}_{suffix}"
    counter = 2
    while any(os.path.exists(os.path.join(folder, candidate + ext)) for ext in extensions):
        candidate = f"{base_name}_{suffix}_{counter}"
        counter += 1
    return os.path.join(folder, candidate)

def get_output_formats_for_type(file_type: str) -> list:
    from ..services import AudioConverter, VideoConverter
    if file_type == 'audio':
        return sorted(AudioConverter.get_supported_output_formats())
    elif file_type == 'video':
        return sorted(VideoConverter.get_supported_output_formats())
    elif file_type == 'image':
        return sorted(['png', 'jpg', 'jpeg', 'webp', 'ico', 'ocr-pdf', 'ocr-docx', 'ocr-txt', 'ocr-md', 'ocr-html'])
    elif file_type == 'document':
        return sorted(['docx', 'html', 'md', 'ocr-docx', 'ocr-html', 'ocr-md', 'ocr-pdf', 'ocr-txt', 'pdf', 'txt', 'images', 'csv', 'xlsx', 'epub', 'cbz'])
    return []
