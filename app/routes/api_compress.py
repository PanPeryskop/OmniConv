import os
import threading
from flask import Blueprint, request, current_app

from .api_common import conversion_jobs, api_response, touch_file
from ..utils.file_handler import generate_file_id
from ..services import VideoCompressor, AudioCompressor, ImageCompressor, PdfCompressor
from ..services.compressor import CompressionError
from .websocket import emit_progress, emit_complete, emit_error

compress_bp = Blueprint('compress', __name__)

VIDEO_KEEP_EXT = {'.mp4', '.mkv', '.mov', '.m4v'}
AUDIO_KEEP_EXT = {'.mp3', '.ogg', '.m4a', '.aac'}
PDF_MODES = {'lossless', 'balanced', 'strong', 'extreme', 'target'}


def get_compress_kind(job):
    file_type = job['file_type']
    ext = os.path.splitext(job['original_filename'])[1].lower()
    if file_type in ('video', 'audio', 'image'):
        return file_type
    if file_type == 'document' and ext == '.pdf':
        return 'pdf'
    return None


def get_output_ext(kind, original_ext):
    original_ext = original_ext.lower()
    if kind == 'image':
        return '.jpg'
    if kind == 'pdf':
        return '.pdf'
    if kind == 'video':
        return original_ext if original_ext in VIDEO_KEEP_EXT else '.mp4'
    if kind == 'audio':
        return original_ext if original_ext in AUDIO_KEEP_EXT else '.mp3'
    return original_ext


def unique_path(folder, base_name, ext):
    path = os.path.join(folder, f"{base_name}_compressed{ext}")
    counter = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base_name}_compressed_{counter}{ext}")
        counter += 1
    return path


@compress_bp.route('/compress', methods=['POST'])
def start_compression():
    data = request.get_json(silent=True)

    if not data:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'JSON body required'}, success=False), 400

    file_id = data.get('file_id')

    if not file_id:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'file_id required'}, success=False), 400

    if file_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404

    try:
        target_size_mb = float(data.get('target_size_mb', 10))
    except (TypeError, ValueError):
        return api_response(error={'type': 'InvalidRequestError', 'message': 'target_size_mb must be a number'}, success=False), 400

    if target_size_mb <= 0:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'target_size_mb must be greater than 0'}, success=False), 400

    source = conversion_jobs[file_id]
    kind = get_compress_kind(source)

    if not kind:
        return api_response(error={'type': 'UnsupportedError', 'message': 'Only video, audio, image and PDF files can be compressed'}, success=False), 400

    if not os.path.exists(source['input_path']):
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404

    options = {}
    if kind == 'pdf':
        mode = data.get('mode', 'balanced')
        if mode not in PDF_MODES:
            return api_response(error={'type': 'InvalidRequestError', 'message': f"mode must be one of: {', '.join(sorted(PDF_MODES))}"}, success=False), 400
        options = {
            'mode': mode,
            'grayscale': bool(data.get('grayscale', False)),
            'strip_metadata': bool(data.get('strip_metadata', False)),
        }

    output_folder = current_app.config['OUTPUT_FOLDER']
    base_name, original_ext = os.path.splitext(source['original_filename'])
    output_path = unique_path(output_folder, base_name, get_output_ext(kind, original_ext))

    job_id = generate_file_id()
    touch_file(file_id)

    job = {
        'status': 'compressing',
        'job_id': job_id,
        'source_file_id': file_id,
        'input_path': source['input_path'],
        'original_filename': source['original_filename'],
        'file_type': source['file_type'],
        'output_path': output_path,
        'progress': 0,
        'target_size_mb': target_size_mb,
        'compression_kind': kind,
    }
    conversion_jobs[job_id] = job

    def progress_callback(progress):
        job['progress'] = progress
        emit_progress(job_id, progress, status='compressing')

    thread = threading.Thread(target=run_compression, args=(job, kind, target_size_mb, options, progress_callback), daemon=True)
    thread.start()

    return api_response(data={'job_id': job_id, 'status': 'compressing'})

def run_compression(job, kind, target_size_mb, options, progress_callback):
    try:
        input_path = job['input_path']
        output_path = job['output_path']

        compressors = {
            'video': VideoCompressor,
            'audio': AudioCompressor,
            'image': ImageCompressor,
            'pdf': PdfCompressor,
        }
        compressor = compressors[kind](progress_callback)
        job['_worker'] = compressor
        if job.get('cancel_requested'):
            compressor.cancel()

        result_path = compressor.compress(input_path, output_path, target_size_mb, options)
        if job.get('cancel_requested'):
            job['status'] = 'cancelled'
            job['error_code'] = 'err_cancelled'
            emit_error(job['job_id'], 'Cancelled')
            return
        if not result_path or not os.path.exists(result_path):
            raise CompressionError('err_compress_failed', "Compression produced no output")

        input_size = os.path.getsize(input_path)
        output_size = os.path.getsize(result_path)

        job['output_path'] = result_path
        job['input_size'] = input_size
        job['output_size'] = output_size
        job['compression_info'] = getattr(compressor, 'info', {})
        job['progress'] = 100
        job['status'] = 'completed'

        emit_complete(job['job_id'], os.path.basename(result_path))

    except Exception as e:
        job['status'] = 'failed'
        job['error'] = str(e)
        job['error_code'] = getattr(e, 'code', 'err_compress_failed')
        emit_error(job['job_id'], str(e))
    finally:
        job.pop('_worker', None)
