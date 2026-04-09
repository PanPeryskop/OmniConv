import os
import threading
from flask import Blueprint, request, jsonify, send_file, current_app, Response, stream_with_context
from werkzeug.exceptions import RequestEntityTooLarge
import json

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
    ImageCompressor,
    AudioDesignService,
    SubtitleGenService
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
            
        try:
            os.remove(saved_path)
            os.rmdir(extract_dir)
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
        return sorted(['docx', 'html', 'md', 'ocr-docx', 'ocr-html', 'ocr-md', 'ocr-pdf', 'ocr-txt', 'pdf', 'txt', 'images', 'csv', 'xlsx'])
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
    
    print(f"DEBUG: Starting conversion thread for job {job_id}")
    thread = threading.Thread(target=run_conversion, args=(job, output_format, options, progress_callback))
    thread.start()
    
    return api_response(data={'job_id': job_id, 'status': 'converting'})


def run_conversion(job, output_format, options, progress_callback):
    print(f"DEBUG: run_conversion started for job {job['job_id']}")
    print(f"DEBUG: Output format: {output_format}, Options: {options}")
    file_type = job['file_type']
    
    if output_format.startswith('ocr-'):
        options['force_ocr'] = True
        output_format = output_format[4:]
    
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
        
        result_path = converter.convert(input_path, output_path, output_format, options)
        
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
    
    output_path = os.path.join(output_folder, filename)
    if os.path.exists(output_path) and os.path.abspath(output_path).startswith(os.path.abspath(output_folder)):
        try:
            os.remove(output_path)
            deleted_files.append('output')
        except Exception as e:
            pass
    
    base_name = os.path.splitext(filename)[0]
    for suffix in ['_compressed', '_converted']:
        if base_name.endswith(suffix):
            base_name = base_name[:-len(suffix)]
            break
    
    if os.path.exists(upload_folder):
        for upload_file in os.listdir(upload_folder):
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
@api_bp.route('/studio/tts', methods=['POST'])
def studio_tts():
    data = request.get_json()
    text = data.get('text')
    voice_description = data.get('voice_description')
    
    if not text or not voice_description:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'text and voice_description required'}, success=False), 400
        
    try:
        service = AudioDesignService()
        output_folder = current_app.config['OUTPUT_FOLDER']
        filename = f"tts_{generate_file_id()}.wav"
        output_path = os.path.join(output_folder, filename)
        
        service.generate_voice_design(text, voice_description, output_path)
        
        return api_response(data={'filename': filename, 'url': f"/api/download-archive/{filename}"})
    except Exception as e:
        return api_response(error={'type': 'TTSError', 'message': str(e)}, success=False), 500

@api_bp.route('/studio/describe', methods=['POST'])
def studio_describe():
    data = request.get_json()
    file_id = data.get('file_id')
    
    if not file_id:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'file_id required'}, success=False), 400
        
    if file_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404
        
    job = conversion_jobs[file_id]
    
    try:
        service = SubtitleGenService()
        description = service.describe_audio(job['input_path'])
        return api_response(data={'description': description})
    except Exception as e:
        return api_response(error={'type': 'AnalysisError', 'message': str(e)}, success=False), 500

@api_bp.route('/studio/transcribe', methods=['POST'])
def studio_transcribe():
    data = request.get_json()
    file_id = data.get('file_id')
    output_format = data.get('format', 'srt')
    
    if not file_id:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'file_id required'}, success=False), 400
        
    if file_id not in conversion_jobs:
        return api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404
        
    job = conversion_jobs[file_id]
    
    try:
        service = SubtitleGenService()
        result = service.generate_subtitle(job['input_path'], output_format)
        
        # Save result to file
        output_folder = current_app.config['OUTPUT_FOLDER']
        filename = f"{os.path.splitext(job['original_filename'])[0]}_subs.{output_format}"
        output_path = os.path.join(output_folder, filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result)
            
        return api_response(data={'filename': filename, 'url': f"/api/download-archive/{filename}", 'content': result})
    except Exception as e:
        return api_response(error={'type': 'SubtitleError', 'message': str(e)}, success=False), 500

@api_bp.route('/studio/generate', methods=['POST'])
def studio_generate():
    data = request.get_json()
    prompt = data.get('prompt')
    mode = data.get('mode', 'dialogue')
    character_count = data.get('character_count', 2)
    
    if not prompt:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'prompt required'}, success=False), 400
        
    def generate():
        try:
            from ..services.llm import LLMService
            service = LLMService()
            for chunk in service.generate_dialogue_stream(prompt, mode=mode, character_count=character_count):
                 yield chunk
        except Exception as e:
            yield f"Error: {str(e)}"

    return Response(stream_with_context(generate()), content_type='text/plain')

@api_bp.route('/studio/audiobook', methods=['POST'])
def studio_audiobook():
    if request.content_type.startswith('multipart/form-data'):
        file_storage = request.files.get('file')
        text_input = request.form.get('text')
        target_lang = request.form.get('target_language')
    else:
        data = request.get_json() or {}
        file_storage = None
        text_input = data.get('text')
        target_lang = data.get('target_language')

    saved_input_path = None
    if file_storage:
        ext = get_file_extension(file_storage.filename)
        file_id = generate_file_id()
        saved_input_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"{file_id}{ext}")
        file_storage.save(saved_input_path)

    def generate():
        try:
            from ..services.llm import LLMService

            full_text = ""
            if saved_input_path:
                yield json.dumps({"status": "extracting", "message": "Extracting text..."}) + "\n"
                try:
                    converter = DocumentConverter()
                    full_text = converter.extract_text(saved_input_path)
                except Exception as e:
                    full_text = f"Error extracting text: {str(e)}"
            elif text_input:
                full_text = text_input
            
            if not full_text:
                yield json.dumps({"error": "No text found"}) + "\n"
                return

            paragraphs = full_text.split('\n')
            chunks = []
            current_chunk = ""
            
            for p in paragraphs:
                if len(current_chunk) + len(p) > 1500:
                    chunks.append(current_chunk)
                    current_chunk = p
                else:
                    current_chunk += "\n" + p
            if current_chunk: chunks.append(current_chunk)
            
            yield json.dumps({"status": "processing", "message": f"Processing {len(chunks)} text chunks..."}) + "\n"
            
            llm = LLMService()
            audio_service = AudioDesignService()
            audio_service._ensure_loaded() # Preload model
            
            audio_files = []
            
            for i, chunk in enumerate(chunks):
                if not chunk.strip(): continue
                
                # Translation Step
                if target_lang:
                    yield json.dumps({"status": "translating", "progress": int((i/len(chunks))*30), "message": f"Translating chunk {i+1}/{len(chunks)} to {target_lang}..."}) + "\n"
                    chunk = llm.translate_text(chunk, target_lang)

                yield json.dumps({"status": "cleaning", "progress": 30 + int((i/len(chunks))*20), "message": f"Polishing chunk {i+1}/{len(chunks)}..."}) + "\n"
                clean_text = llm.prep_text_for_audio(chunk)
                
                yield json.dumps({"status": "generating", "progress": 50 + int((i/len(chunks))*40), "message": f"Speaking chunk {i+1}/{len(chunks)}..."}) + "\n"
                narrator_desc = "A clear, professional, warm narrator voice, neutral accent, storytelling tone."
                
                chunk_filename = f"chunk_{generate_file_id()}.wav"
                chunk_path = os.path.join(current_app.config['OUTPUT_FOLDER'], chunk_filename)
                
                outfile = audio_service.generate_voice_design(clean_text, narrator_desc, chunk_path)
                if outfile:
                   audio_files.append(outfile)

            yield json.dumps({"status": "merging", "message": "Merging audio files..."}) + "\n"
            
            output_folder = current_app.config['OUTPUT_FOLDER']
            merged_filename = f"audiobook_{generate_file_id()}.wav"
            merged_path = os.path.join(output_folder, merged_filename)
            
            if len(audio_files) == 1:
                import shutil
                shutil.copy(audio_files[0], merged_path)
            elif len(audio_files) > 1:
                import imageio_ffmpeg
                import subprocess
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                list_path = os.path.join(output_folder, f"_concat_{generate_file_id()}.txt")
                with open(list_path, 'w') as f:
                    for af in audio_files:
                        f.write(f"file '{af}'\n")
                
                subprocess.run([
                    ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0',
                    '-i', list_path, '-c:a', 'pcm_s16le', merged_path
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try: os.remove(list_path) 
                except: pass
            
            yield json.dumps({
                "status": "complete", 
                "progress": 100,
                "url": f"/api/download-archive/{merged_filename}", 
                "filename": merged_filename
            }) + "\n"

        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"

    return Response(stream_with_context(generate()), content_type='application/json')

@api_bp.route('/studio/trim', methods=['POST'])
def studio_trim():
    data = request.get_json()
    source_url = data.get('url')
    start = data.get('start', 0)
    end = data.get('end')
    
    if not source_url:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'url required'}, success=False), 400
    
    filename = source_url.split('/')[-1]
    output_folder = current_app.config['OUTPUT_FOLDER']
    source_path = os.path.join(output_folder, filename)
    
    if not os.path.exists(source_path):
        return api_response(error={'type': 'NotFoundError', 'message': 'Source file not found'}, success=False), 404
    
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        out_filename = f"trimmed_{generate_file_id()}.wav"
        out_path = os.path.join(output_folder, out_filename)
        
        cmd = [ffmpeg_exe, '-y', '-i', source_path, '-ss', str(start)]
        if end:
            cmd.extend(['-to', str(end)])
        cmd.extend(['-c:a', 'pcm_s16le', out_path])
        
        import subprocess
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        return api_response(data={'filename': out_filename, 'url': f"/api/download-archive/{out_filename}"})
    except Exception as e:
        return api_response(error={'type': 'TrimError', 'message': str(e)}, success=False), 500

@api_bp.route('/studio/merge', methods=['POST'])
def studio_merge():
    data = request.get_json()
    urls = data.get('urls', [])
    gap_ms = data.get('gap_ms', 500)
    
    if len(urls) < 2:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'at least 2 urls required'}, success=False), 400
    
    output_folder = current_app.config['OUTPUT_FOLDER']
    
    try:
        import imageio_ffmpeg
        import subprocess
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        list_path = os.path.join(output_folder, f"_concat_{generate_file_id()}.txt")
        gap_path = None
        
        if gap_ms > 0:
            gap_path = os.path.join(output_folder, f"_silence_{generate_file_id()}.wav")
            subprocess.run([
                ffmpeg_exe, '-y', '-f', 'lavfi', '-i',
                f'anullsrc=r=24000:cl=mono:d={gap_ms/1000}',
                '-c:a', 'pcm_s16le', gap_path
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        with open(list_path, 'w') as f:
            for i, url in enumerate(urls):
                fname = url.split('/')[-1]
                fpath = os.path.join(output_folder, fname)
                if not os.path.exists(fpath):
                    continue
                f.write(f"file '{fpath}'\n")
                if gap_path and i < len(urls) - 1:
                    f.write(f"file '{gap_path}'\n")
        
        out_filename = f"merged_{generate_file_id()}.wav"
        out_path = os.path.join(output_folder, out_filename)
        
        subprocess.run([
            ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0',
            '-i', list_path, '-c:a', 'pcm_s16le', out_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        try:
            os.remove(list_path)
            if gap_path:
                os.remove(gap_path)
        except:
            pass
        
        return api_response(data={'filename': out_filename, 'url': f"/api/download-archive/{out_filename}"})
    except Exception as e:
        return api_response(error={'type': 'MergeError', 'message': str(e)}, success=False), 500
