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
    OCRService,
    VideoCompressor,
    AudioCompressor,
    ImageCompressor
)
from .websocket import emit_progress, emit_complete, emit_error
from ..services.stats import stats_service as stats

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


@api_bp.route('/upload-url', methods=['POST'])
def upload_from_url():
    data = request.get_json()
    if not data or 'url' not in data:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'URL required'}, success=False), 400
        
    url = data['url']
    
    try:
        from ..utils.file_handler import download_file_from_url
        upload_folder = current_app.config['UPLOAD_FOLDER']
        
        file_id, saved_path, original_filename = download_file_from_url(url, upload_folder)
        
        file_type = get_file_type(original_filename)
        if not file_type:
            ext = get_file_extension(original_filename)
            return api_response(error={'type': 'UnsupportedFormatError', 'message': f'Unsupported file format: {ext}'}, success=False), 400
            
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
        return api_response(error={'type': 'DownloadError', 'message': str(e)}, success=False), 500


@api_bp.route('/upload-archive', methods=['POST'])
def upload_archive():
    if 'file' not in request.files:
        return api_response(error={'type': 'NoFileError', 'message': 'No file provided'}, success=False), 400
    
    file = request.files['file']
    if not file.filename:
        return api_response(error={'type': 'NoFileError', 'message': 'No file selected'}, success=False), 400
        
    try:
        from ..services.archive import archive_service
        upload_folder = current_app.config['UPLOAD_FOLDER']
        archive_service.upload_folder = upload_folder # Ensure correct folder
        
        # Save archive first
        file_id, saved_path, original_filename = save_uploaded_file(file, upload_folder)
        
        # Extract
        extract_dir = os.path.join(upload_folder, f"extracted_{file_id}")
        os.makedirs(extract_dir, exist_ok=True)
        
        extracted_files = archive_service.extract_archive(saved_path, extract_dir)
        
        result_files = []
        for file_path in extracted_files:
            # Register as uploaded file
            f_name = os.path.basename(file_path)
            f_id = generate_file_id()
            f_ext = get_file_extension(f_name)
            
            # Move to main upload folder or keep in extracted? 
            # Keeping in extracted might be messy for cleanup.
            # Let's move to upload folder with unique name
            new_path = os.path.join(upload_folder, f"{f_id}.{f_ext}") if f_ext else os.path.join(upload_folder, f_id)
            import shutil
            shutil.move(file_path, new_path)
            
            f_type = get_file_type(f_name)
            if not f_type: continue # Skip unsupported for now or treat as 'other'
            
            output_formats = get_output_formats_for_type(f_type)
            
            conversion_jobs[f_id] = {
                'status': 'uploaded',
                'input_path': new_path,
                'original_filename': f_name,
                'file_type': f_type,
                'output_formats': output_formats,
                'progress': 0
            }
            
            result_files.append({
                'file_id': f_id,
                'filename': f_name,
                'file_type': f_type,
                'output_formats': output_formats,
                'size': os.path.getsize(new_path)
            })
            
        # Cleanup archive and empty dir
        try:
            os.remove(saved_path)
            os.rmdir(extract_dir) # Only if empty, but we moved files
        except:
            pass
            
        return api_response(data={'files': result_files})
        
    except Exception as e:
        return api_response(error={'type': 'ArchiveError', 'message': str(e)}, success=False), 500


def get_output_formats_for_type(file_type: str) -> list:
    if file_type == 'audio':
        return sorted(AudioConverter.get_supported_output_formats())
    elif file_type == 'video':
        return sorted(VideoConverter.get_supported_output_formats())
    elif file_type == 'image':
        return sorted(['png', 'jpg', 'jpeg', 'webp', 'ico', 'ocr-pdf', 'ocr-docx', 'ocr-txt', 'ocr-md', 'ocr-html'])
    elif file_type == 'document':
        return sorted(['pdf', 'docx', 'ocr-docx', 'txt', 'ocr-txt', 'md', 'ocr-md', 'ocr-pdf', 'html', 'ocr-html'])
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
    
    target_extension = output_format
    if output_format.lower().startswith('ocr-'):
        target_extension = output_format[4:]
        
    output_path = get_output_path(output_folder, job['original_filename'], target_extension)
    
    job_id = generate_file_id()
    
    job['status'] = 'converting'
    job['job_id'] = job_id
    job['output_format'] = output_format
    job['output_path'] = output_path
    job['progress'] = 0
    
    conversion_jobs[job_id] = job
    
    def progress_callback(progress):
        job['progress'] = progress
        emit_progress(job_id, progress)
    
    thread = threading.Thread(target=run_conversion, args=(job, output_format, options, progress_callback))
    thread.start()
    
    return api_response(data={'job_id': job_id, 'status': 'converting'})


def run_conversion(job, output_format, options, progress_callback):
    print(f"DEBUG: run_conversion started for {job['job_id']} format={output_format} type={job['file_type']}")
    file_type = job['file_type']
    
    if output_format.startswith('ocr-'):
        options['force_ocr'] = True
        output_format = output_format[4:]
        print(f"DEBUG: Force OCR enabled, new format={output_format}")
    
    try:
        input_path = job['input_path']
        output_path = job['output_path']
        
        print(f"DEBUG: Selecting converter for {file_type}...")
        if file_type == 'audio':
            converter = AudioConverter(progress_callback)
        elif file_type == 'video':
            converter = VideoConverter(progress_callback)
        elif file_type == 'image':
            if output_format in ['txt', 'docx', 'md', 'html'] or (output_format == 'pdf' and options.get('force_ocr')):
                print("DEBUG: Using OCRService for image")
                try:
                    converter = OCRService(progress_callback)
                    print("DEBUG: OCRService instantiated success")
                except Exception as ie:
                    print(f"DEBUG: OCRService init failed: {ie}")
                    raise ie
            else:
                converter = ImageConverter(progress_callback)
        elif file_type == 'document':
            if options.get('force_ocr'):
                print("DEBUG: Using OCRService for document")
                converter = OCRService(progress_callback)
            else:
                converter = DocumentConverter(progress_callback)
        else:
            raise UnsupportedFormatError(file_type)
        
        print(f"DEBUG: Starting converter.convert...")
        result_path = converter.convert(input_path, output_path, output_format, options)
        print(f"DEBUG: Convert finished, result={result_path}")
        
        job['status'] = 'completed'
        job['progress'] = 100
        job['output_path'] = result_path
        
        try:
            input_size = os.path.getsize(input_path)
            output_size = os.path.getsize(result_path)
            input_ext = os.path.splitext(job['original_filename'])[1].lower().replace('.', '')
            stats.record_conversion(input_ext, output_format, input_size, output_size)
        except Exception:
            pass
        
        emit_complete(job['job_id'], os.path.basename(result_path))
        
    except Exception as e:
        job['status'] = 'failed'
        job['error'] = str(e)
        emit_error(job['job_id'], str(e))


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


@api_bp.route('/download-archive/<filename>', methods=['GET'])
def download_archive_file(filename):
    import re
    if not re.match(r'^[\w\-. ]+$', filename):
        return api_response(error={'type': 'InvalidFilenameError', 'message': 'Invalid filename'}, success=False), 400
    
    output_folder = current_app.config['OUTPUT_FOLDER']
    file_path = os.path.join(output_folder, filename)
    
    if not os.path.exists(file_path):
        return api_response(error={'type': 'FileNotFoundError', 'message': 'File not found in archive'}, success=False), 404
    
    if not os.path.abspath(file_path).startswith(os.path.abspath(output_folder)):
        return api_response(error={'type': 'SecurityError', 'message': 'Access denied'}, success=False), 403
    
    return send_file(file_path, as_attachment=True, download_name=filename)


@api_bp.route('/delete-archive/<filename>', methods=['DELETE'])
def delete_archive_file(filename):
    import re
    if not re.match(r'^[\w\-. ]+$', filename):
        return api_response(error={'type': 'InvalidFilenameError', 'message': 'Invalid filename'}, success=False), 400
    
    output_folder = current_app.config['OUTPUT_FOLDER']
    upload_folder = current_app.config['UPLOAD_FOLDER']
    
    deleted_files = []
    
    # Try to delete from outputs folder
    output_path = os.path.join(output_folder, filename)
    if os.path.exists(output_path) and os.path.abspath(output_path).startswith(os.path.abspath(output_folder)):
        try:
            os.remove(output_path)
            deleted_files.append('output')
        except Exception as e:
            pass
    
    # Try to find and delete matching input file from uploads folder
    base_name = os.path.splitext(filename)[0]
    # Remove common suffixes like _compressed
    for suffix in ['_compressed', '_converted']:
        if base_name.endswith(suffix):
            base_name = base_name[:-len(suffix)]
            break
    
    # Look for files with similar base name in uploads
    if os.path.exists(upload_folder):
        for upload_file in os.listdir(upload_folder):
            # Match files that start with similar pattern (uuid_originalname)
            if os.path.abspath(os.path.join(upload_folder, upload_file)).startswith(os.path.abspath(upload_folder)):
                try:
                    upload_path = os.path.join(upload_folder, upload_file)
                    os.remove(upload_path)
                    deleted_files.append('upload')
                except Exception:
                    pass
    
    return api_response(data={'deleted': deleted_files, 'filename': filename})


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


@api_bp.route('/compress', methods=['POST'])
def start_compression():
    data = request.get_json()
    
    if not data:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'JSON body required'}, success=False), 400
    
    file_id = data.get('file_id')
    target_size_mb = data.get('target_size_mb', 10)
    
    if not file_id:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'file_id required'}, success=False), 400
    
    if file_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404
    
    job = conversion_jobs[file_id]
    file_type = job['file_type']
    
    if file_type not in ['video', 'audio', 'image']:
        return api_response(error={'type': 'UnsupportedError', 'message': 'Only video, audio, and image files can be compressed'}, success=False), 400
    
    output_folder = current_app.config['OUTPUT_FOLDER']
    original_ext = os.path.splitext(job['original_filename'])[1]
    
    if file_type == 'image':
        output_ext = '.jpg'
    else:
        output_ext = original_ext
    
    base_name = os.path.splitext(job['original_filename'])[0]
    output_filename = f"{base_name}_compressed{output_ext}"
    output_path = os.path.join(output_folder, output_filename)
    
    job_id = generate_file_id()
    
    job['status'] = 'compressing'
    job['job_id'] = job_id
    job['output_path'] = output_path
    job['progress'] = 0
    job['target_size_mb'] = target_size_mb
    
    conversion_jobs[job_id] = job
    
    def progress_callback(progress):
        job['progress'] = progress
        emit_progress(job_id, progress, status='compressing')
    
    thread = threading.Thread(target=run_compression, args=(job, target_size_mb, progress_callback))
    thread.start()
    
    return api_response(data={'job_id': job_id, 'status': 'compressing'})


def run_compression(job, target_size_mb, progress_callback):
    try:
        file_type = job['file_type']
        input_path = job['input_path']
        output_path = job['output_path']
        
        if file_type == 'video':
            compressor = VideoCompressor(progress_callback)
        elif file_type == 'audio':
            compressor = AudioCompressor(progress_callback)
        elif file_type == 'image':
            compressor = ImageCompressor(progress_callback)
        else:
            raise Exception(f"Unsupported file type: {file_type}")
        
        result_path = compressor.compress(input_path, output_path, target_size_mb)
        
        job['status'] = 'completed'
        job['progress'] = 100
        job['output_path'] = result_path
        
        try:
            input_size = os.path.getsize(input_path)
            output_size = os.path.getsize(result_path)
            input_ext = os.path.splitext(job['original_filename'])[1].lower().replace('.', '')
            stats.record_conversion(input_ext, 'compressed', input_size, output_size)
        except Exception:
            pass
        
        emit_complete(job['job_id'], os.path.basename(result_path))
        
    except Exception as e:
        job['status'] = 'failed'
        job['error'] = str(e)
        emit_error(job['job_id'], str(e))


@api_bp.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    max_size = current_app.config.get('MAX_CONTENT_LENGTH', 0) / (1024 * 1024)
    return api_response(error={'type': 'FileTooLargeError', 'message': f'File exceeds maximum size of {max_size:.0f}MB'}, success=False), 413
@api_bp.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    if not data or 'message' not in data:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'Message required'}, success=False), 400
        
    message = data.get('message')
    response_id = data.get('response_id')
    
    try:
        from ..services.llm import LLMService
        llm = LLMService()
        result = llm.chat_with_context(message, response_id)
        return api_response(data=result)
    except Exception as e:
        return api_response(error={'type': 'ChatError', 'message': str(e)}, success=False), 500
