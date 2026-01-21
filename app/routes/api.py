import os
import threading
from flask import Blueprint, request, jsonify, send_file, current_app
from werkzeug.exceptions import RequestEntityTooLarge

from ..utils.file_handler import (
    get_file_extension,
    get_file_type,
    save_uploaded_file,
    get_output_path,
    generate_file_id
)
from ..utils.exceptions import (
    ConversionError,
    UnsupportedFormatError,
    FileTooLargeError,
    ConversionJobNotFoundError
)
from ..services import (
    AudioConverter,
    VideoConverter,
    ImageConverter, 
    DocumentConverter,
    OCRService
)

api_bp = Blueprint('api', __name__)
conversion_jobs = {}


def api_response(data=None, error=None, success=True):
    return jsonify({'success': success, 'data': data, 'error': error})


@api_bp.route('/capabilities', methods=['GET'])
def get_capabilities():
    capabilities = {
        'audio': {
            'input': sorted(AudioConverter.get_supported_input_formats()),
            'output': sorted(AudioConverter.get_supported_output_formats())
        },
        'video': {
            'input': sorted(VideoConverter.get_supported_input_formats()),
            'output': sorted(VideoConverter.get_supported_output_formats())
        },
        'image': {
            'input': sorted(ImageConverter.get_supported_input_formats()),
            'output': sorted(ImageConverter.get_supported_output_formats())
        },
        'document': {
            'input': sorted(DocumentConverter.get_supported_input_formats()),
            'output': sorted(DocumentConverter.get_supported_output_formats())
        },
        'ocr': {
            'input': sorted(OCRService.get_supported_input_formats()),
            'output': sorted(OCRService.get_supported_output_formats())
        }
    }
    return api_response(data=capabilities)


@api_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return api_response(error={'type': 'NoFileError', 'message': 'No file provided'}, success=False), 400
    
    file = request.files['file']
    
    if not file.filename:
        return api_response(error={'type': 'NoFileError', 'message': 'No file selected'}, success=False), 400
    
    file_type = get_file_type(file.filename)
    if not file_type:
        ext = get_file_extension(file.filename)
        return api_response(error={'type': 'UnsupportedFormatError', 'message': f'Unsupported file format: {ext}'}, success=False), 400
    
    try:
        upload_folder = current_app.config['UPLOAD_FOLDER']
        file_id, saved_path, original_filename = save_uploaded_file(file, upload_folder)
        output_formats = get_output_formats_for_type(file_type)
        
        conversion_jobs[file_id] = {
            'status': 'uploaded',
            'input_path': saved_path,
            'original_filename': original_filename,
            'file_type': file_type,
            'output_formats': output_formats,
            'progress': 0
        }
        
        return api_response(data={
            'file_id': file_id,
            'filename': original_filename,
            'file_type': file_type,
            'output_formats': output_formats
        })
        
    except Exception as e:
        return api_response(error={'type': 'UploadError', 'message': str(e)}, success=False), 500


def get_output_formats_for_type(file_type: str) -> list:
    if file_type == 'audio':
        return sorted(AudioConverter.get_supported_output_formats())
    elif file_type == 'video':
        return sorted(VideoConverter.get_supported_output_formats())
    elif file_type == 'image':
        return sorted(ImageConverter.get_supported_output_formats())
    elif file_type == 'document':
        return sorted(DocumentConverter.get_supported_output_formats())
    return []


@api_bp.route('/formats/<file_id>', methods=['GET'])
def get_formats(file_id):
    if file_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404
    
    job = conversion_jobs[file_id]
    return api_response(data={'file_id': file_id, 'file_type': job['file_type'], 'output_formats': job['output_formats']})


@api_bp.route('/convert', methods=['POST'])
def start_conversion():
    data = request.get_json()
    
    if not data:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'JSON body required'}, success=False), 400
    
    file_id = data.get('file_id')
    output_format = data.get('output_format')
    options = data.get('options', {})
    
    if not file_id or not output_format:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'file_id and output_format required'}, success=False), 400
    
    if file_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404
    
    job = conversion_jobs[file_id]
    
    if output_format.lower() not in [f.lower() for f in job['output_formats']]:
        return api_response(error={'type': 'UnsupportedFormatError', 'message': f'Format {output_format} not available'}, success=False), 400
    
    output_folder = current_app.config['OUTPUT_FOLDER']
    output_path = get_output_path(output_folder, job['original_filename'], output_format)
    
    job_id = generate_file_id()
    
    job['status'] = 'converting'
    job['job_id'] = job_id
    job['output_format'] = output_format
    job['output_path'] = output_path
    job['progress'] = 0
    
    conversion_jobs[job_id] = job
    
    def progress_callback(progress):
        job['progress'] = progress
    
    thread = threading.Thread(target=run_conversion, args=(job, output_format, options, progress_callback))
    thread.start()
    
    return api_response(data={'job_id': job_id, 'status': 'converting'})


def run_conversion(job, output_format, options, progress_callback):
    try:
        file_type = job['file_type']
        input_path = job['input_path']
        output_path = job['output_path']
        
        if file_type == 'audio':
            converter = AudioConverter(progress_callback)
        elif file_type == 'video':
            converter = VideoConverter(progress_callback)
        elif file_type == 'image':
            converter = ImageConverter(progress_callback)
        elif file_type == 'document':
            converter = DocumentConverter(progress_callback)
        else:
            raise UnsupportedFormatError(file_type)
        
        result_path = converter.convert(input_path, output_path, output_format, options)
        
        job['status'] = 'completed'
        job['progress'] = 100
        job['output_path'] = result_path
        
    except Exception as e:
        job['status'] = 'failed'
        job['error'] = str(e)


@api_bp.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    if job_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'Job not found'}, success=False), 404
    
    job = conversion_jobs[job_id]
    
    response_data = {'job_id': job_id, 'status': job['status'], 'progress': job.get('progress', 0)}
    
    if job['status'] == 'completed':
        response_data['download_ready'] = True
        response_data['filename'] = os.path.basename(job['output_path'])
    elif job['status'] == 'failed':
        response_data['error'] = job.get('error', 'Unknown error')
    
    return api_response(data=response_data)


@api_bp.route('/download/<job_id>', methods=['GET'])
def download_file(job_id):
    if job_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'Job not found'}, success=False), 404
    
    job = conversion_jobs[job_id]
    
    if job['status'] != 'completed':
        return api_response(error={'type': 'NotReadyError', 'message': 'Conversion not complete'}, success=False), 400
    
    output_path = job['output_path']
    
    if not os.path.exists(output_path):
        return api_response(error={'type': 'FileNotFoundError', 'message': 'Output file not found'}, success=False), 404
    
    return send_file(output_path, as_attachment=True, download_name=os.path.basename(output_path))


@api_bp.route('/ocr', methods=['POST'])
def ocr_file():
    data = request.get_json()
    
    if not data or 'file_id' not in data:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'file_id required'}, success=False), 400
    
    file_id = data['file_id']
    lang = data.get('lang', 'en')
    
    if file_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404
    
    job = conversion_jobs[file_id]
    
    try:
        ocr_service = OCRService()
        text = ocr_service.get_text_from_image(job['input_path'], lang)
        return api_response(data={'text': text, 'file_id': file_id})
    except Exception as e:
        return api_response(error={'type': 'OCRError', 'message': str(e)}, success=False), 500


@api_bp.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    max_size = current_app.config.get('MAX_CONTENT_LENGTH', 0) / (1024 * 1024)
    return api_response(error={'type': 'FileTooLargeError', 'message': f'File exceeds maximum size of {max_size:.0f}MB'}, success=False), 413
