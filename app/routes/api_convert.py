import os
import threading
import shutil
import re
from flask import Blueprint, request, send_file, current_app

from .api_common import conversion_jobs, api_response, get_output_formats_for_type, touch_file, file_expiry, register_result_file
from ..utils.file_handler import get_file_extension, get_file_type, save_uploaded_file, get_output_path, generate_file_id
from ..utils.exceptions import UnsupportedFormatError
from ..services import AudioConverter, VideoConverter, ImageConverter, DocumentConverter, OCRService
from .websocket import emit_progress, emit_complete, emit_error

convert_bp = Blueprint('convert', __name__)

@convert_bp.route('/ocr', methods=['POST'])
def ocr_file():
    data = request.get_json(silent=True)
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

@convert_bp.route('/upload', methods=['POST'])
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

@convert_bp.route('/upload-url', methods=['POST'])
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

@convert_bp.route('/upload-archive', methods=['POST'])
def upload_archive():
    if 'file' not in request.files:
        return api_response(error={'type': 'NoFileError', 'message': 'No file provided'}, success=False), 400
    
    file = request.files['file']
    if not file.filename:
        return api_response(error={'type': 'NoFileError', 'message': 'No file selected'}, success=False), 400
        
    try:
        from ..services.archive import archive_service
        upload_folder = current_app.config['UPLOAD_FOLDER']
        archive_service.upload_folder = upload_folder
        
        file_id, saved_path, original_filename = save_uploaded_file(file, upload_folder)
        
        extract_dir = os.path.join(upload_folder, f"extracted_{file_id}")
        os.makedirs(extract_dir, exist_ok=True)
        
        extracted_files = archive_service.extract_archive(saved_path, extract_dir)
        
        result_files = []
        for file_path in extracted_files:
            f_name = os.path.basename(file_path)
            f_id = generate_file_id()
            f_ext = get_file_extension(f_name)
            
            new_path = os.path.join(upload_folder, f"{f_id}.{f_ext}") if f_ext else os.path.join(upload_folder, f_id)
            shutil.move(file_path, new_path)
            
            f_type = get_file_type(f_name)
            if not f_type: continue
            
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
            
        try:
            os.remove(saved_path)
            os.rmdir(extract_dir)
        except:
            pass
            
        return api_response(data={'files': result_files})
    except Exception as e:
        return api_response(error={'type': 'ArchiveError', 'message': str(e)}, success=False), 500

@convert_bp.route('/formats/<file_id>', methods=['GET'])
def get_formats(file_id):
    if file_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404
    
    job = conversion_jobs[file_id]
    return api_response(data={'file_id': file_id, 'file_type': job['file_type'], 'output_formats': job['output_formats']})

@convert_bp.route('/convert', methods=['POST'])
def start_conversion():
    data = request.get_json(silent=True)

    if not data:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'JSON body required'}, success=False), 400

    file_id = data.get('file_id')
    output_format = data.get('output_format')
    options = data.get('options') or {}
    if not isinstance(options, dict):
        return api_response(error={'type': 'InvalidRequestError', 'message': 'options must be an object'}, success=False), 400

    if not file_id or not output_format:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'file_id and output_format required'}, success=False), 400

    if file_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404

    source = conversion_jobs[file_id]

    if output_format.lower() not in [f.lower() for f in source['output_formats']]:
        return api_response(error={'type': 'UnsupportedFormatError', 'message': f'Format {output_format} not available'}, success=False), 400

    if not os.path.exists(source['input_path']):
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404

    output_folder = current_app.config['OUTPUT_FOLDER']

    target_extension = output_format.lower()
    if target_extension.startswith('ocr-'):
        target_extension = target_extension[4:]
    if target_extension == 'pdf_ocr':
        target_extension = 'pdf'

    output_path = get_output_path(output_folder, source['original_filename'], target_extension)

    job_id = generate_file_id()
    touch_file(file_id)

    job = {
        'status': 'converting',
        'job_id': job_id,
        'source_file_id': file_id,
        'input_path': source['input_path'],
        'original_filename': source['original_filename'],
        'file_type': source['file_type'],
        'output_format': output_format,
        'output_path': output_path,
        'progress': 0,
    }
    conversion_jobs[job_id] = job

    def progress_callback(progress):
        job['progress'] = progress
        emit_progress(job_id, progress)

    thread = threading.Thread(target=run_conversion, args=(job, output_format, options, progress_callback), daemon=True)
    thread.start()

    return api_response(data={'job_id': job_id, 'status': 'converting'})

def run_conversion(job, output_format, options, progress_callback):
    file_type = job['file_type']
    output_format = output_format.lower()

    if output_format.startswith('ocr-') or output_format == 'pdf_ocr':
        options['force_ocr'] = True
        output_format = 'pdf' if output_format == 'pdf_ocr' else output_format[4:]

    try:
        input_path = job['input_path']
        output_path = job['output_path']

        if file_type == 'audio':
            converter = AudioConverter(progress_callback)
        elif file_type == 'video':
            converter = VideoConverter(progress_callback)
        elif file_type == 'image':
            if options.get('force_ocr'):
                converter = OCRService(progress_callback)
            else:
                converter = ImageConverter(progress_callback)
        elif file_type == 'document':
            if options.get('force_ocr'):
                converter = OCRService(progress_callback)
            else:
                converter = DocumentConverter(progress_callback)
        else:
            raise UnsupportedFormatError(file_type)

        job['_worker'] = converter
        if job.get('cancel_requested'):
            converter.cancel()

        result_path = converter.convert(input_path, output_path, output_format, options)

        if job.get('cancel_requested') or not result_path:
            job['status'] = 'cancelled'
            job['error_code'] = 'err_cancelled'
            emit_error(job['job_id'], 'Cancelled')
            return

        job['output_path'] = result_path
        try:
            job['input_size'] = os.path.getsize(input_path)
            job['output_size'] = os.path.getsize(result_path)
        except OSError:
            pass
        info = getattr(converter, 'info', None)
        if info:
            job['ocr_info'] = info
        if result_path.lower().endswith('.pdf'):
            job['result_file_id'] = register_result_file(result_path)
        job['progress'] = 100
        job['status'] = 'completed'

        emit_complete(job['job_id'], os.path.basename(result_path))

    except UnsupportedFormatError as e:
        job['status'] = 'failed'
        job['error'] = f"Unsupported format: {str(e)}"
        job['error_code'] = 'err_conversion_failed'
        emit_error(job['job_id'], job['error'])
    except Exception as e:
        error_msg = str(e).lower()
        error_type = 'ConversionError'
        if 'ffmpeg' in error_msg:
            error_type = 'DependencyError'
        elif 'not found' in error_msg or 'no such file' in error_msg:
            error_type = 'FileNotFoundError'
        elif 'space' in error_msg:
            error_type = 'DiskFullError'

        job['status'] = 'failed'
        job['error'] = f"[{error_type}] {str(e)}"
        job['error_code'] = getattr(e, 'code', None) or 'err_conversion_failed'
        emit_error(job['job_id'], job['error'])
    finally:
        job.pop('_worker', None)

@convert_bp.route('/cancel/<job_id>', methods=['POST'])
def cancel_job(job_id):
    job = conversion_jobs.get(job_id)
    if not job:
        return api_response(error={'type': 'NotFoundError', 'message': 'Job not found'}, success=False), 404
    if job.get('status') in ('completed', 'failed', 'cancelled'):
        return api_response(data={'job_id': job_id, 'status': job['status']})
    job['cancel_requested'] = True
    worker = job.get('_worker')
    if worker is not None and hasattr(worker, 'cancel'):
        worker.cancel()
    return api_response(data={'job_id': job_id, 'status': 'cancelling'})

@convert_bp.route('/ocr/engines', methods=['GET'])
def ocr_engines():
    return api_response(data=OCRService.engine_status())

@convert_bp.route('/files/<file_id>/touch', methods=['POST'])
def touch_uploaded_file(file_id):
    if file_id not in conversion_jobs or not os.path.exists(conversion_jobs[file_id].get('input_path', '')):
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404
    touch_file(file_id)
    return api_response(data=file_expiry(file_id))

@convert_bp.route('/smart-rename', methods=['POST'])
def smart_rename():
    data = request.get_json()
    if not data or 'filename' not in data:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'filename required'}, success=False), 400
    
    filename = data['filename']
    try:
        from ..services.llm import LLMService
        service = LLMService()
        prompt = f"You are a file renamer. Extract a clean, highly readable, and professional title from this raw filename: '{filename}'. Remove generic phrases like 'official music video', random alphanumeric strings, hashes, IDs, 'hd', '1080p', underscores, and extensions. Keep author/artist names if present. Return ONLY the clean name, nothing else."
        payload = {
            "model": "ministral-3-8b-instruct-2512",
            "system_prompt": "You are a smart filename cleaner.",
            "input": prompt,
            "temperature": 0.1,
            "stream": False
        }
        import os
        payload["model"] = os.environ.get("LLM_FORMATTING_MODEL", "ministral-3-8b-instruct-2512")
        result = service._send_request(payload)
        clean_name = filename
        if 'output' in result and len(result['output']) > 0:
            for item in result['output']:
                if item.get('type') == 'message':
                    clean_name = item['content'].strip()
                    break
        return api_response(data={'clean_name': clean_name})
    except Exception as e:
        return api_response(error={'type': 'RenameError', 'message': str(e)}, success=False), 500

@convert_bp.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    if job_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'Job not found'}, success=False), 404
    
    job = conversion_jobs[job_id]
    
    response_data = {'job_id': job_id, 'status': job['status'], 'progress': job.get('progress', 0)}
    if job.get('error_code'):
        response_data['error_code'] = job['error_code']
    
    if job['status'] == 'completed':
        response_data['download_ready'] = True
        response_data['filename'] = os.path.basename(job['output_path'])
        for key in ('input_size', 'output_size', 'compression_info', 'result_file_id', 'tool', 'ocr_info'):
            if key in job:
                response_data[key] = job[key]
    elif job['status'] == 'failed':
        response_data['error'] = job.get('error', 'Unknown error')
    
    return api_response(data=response_data)

@convert_bp.route('/download/<job_id>', methods=['GET'])
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

@convert_bp.route('/download-archive/<filename>', methods=['GET'])
def download_archive_file(filename):
    if not re.match(r'^[\w\-. ]+$', filename):
        return api_response(error={'type': 'InvalidFilenameError', 'message': 'Invalid filename'}, success=False), 400
    
    output_folder = current_app.config['OUTPUT_FOLDER']
    file_path = os.path.join(output_folder, filename)
    
    if not os.path.exists(file_path):
        return api_response(error={'type': 'FileNotFoundError', 'message': 'File not found in archive'}, success=False), 404
    
    if not os.path.abspath(file_path).startswith(os.path.abspath(output_folder)):
        return api_response(error={'type': 'SecurityError', 'message': 'Access denied'}, success=False), 403
    
    return send_file(file_path, as_attachment=True, download_name=filename)

@convert_bp.route('/delete-archive/<filename>', methods=['DELETE'])
def delete_archive_file(filename):
    if not re.match(r'^[\w\-. ]+$', filename):
        return api_response(error={'type': 'InvalidFilenameError', 'message': 'Invalid filename'}, success=False), 400
    
    output_folder = current_app.config['OUTPUT_FOLDER']
    upload_folder = current_app.config['UPLOAD_FOLDER']
    
    deleted_files = []
    
    output_path = os.path.join(output_folder, filename)
    if os.path.exists(output_path) and os.path.abspath(output_path).startswith(os.path.abspath(output_folder)):
        try:
            os.remove(output_path)
            deleted_files.append('output')
        except Exception:
            pass
    
    upload_root = os.path.abspath(upload_folder)
    input_paths = {
        job.get('input_path') for job in list(conversion_jobs.values())
        if job.get('output_path') and os.path.basename(job['output_path']) == filename
    }

    for upload_path in filter(None, input_paths):
        if os.path.abspath(upload_path).startswith(upload_root) and os.path.exists(upload_path):
            try:
                os.remove(upload_path)
                deleted_files.append('upload')
            except Exception:
                pass

    return api_response(data={'deleted': deleted_files, 'filename': filename})
