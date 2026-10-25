import io
import os
import re
import threading
from flask import Blueprint, request, current_app, send_file

from .api_common import conversion_jobs, api_response, unique_output_base, touch_file, file_expiry, register_result_file
from ..utils.file_handler import generate_file_id
from ..services.pdf_tools import PdfTools, PdfToolError
from .websocket import emit_progress, emit_complete, emit_error

pdf_bp = Blueprint('pdf', __name__)

TOOL_SUFFIXES = {
    'compress': 'compressed',
    'organize': 'edited',
    'split': 'split',
    'merge': 'merged',
    'protect': 'protected',
    'unlock': 'unlocked',
    'watermark': 'watermark',
    'page_numbers': 'numbered',
    'metadata': 'metadata',
    'extract_images': 'images',
    'to_images': 'pages',
}

SUFFIX_RE = re.compile(r'(?:_(?:' + '|'.join(sorted(set(TOOL_SUFFIXES.values()))) + r')(?:_\d+)?)+$')
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')

ERROR_STATUS = {
    'err_pdf_password': 423,
    'err_pdf_wrong_password': 403,
}


def get_pdf_job(file_id):
    job = conversion_jobs.get(file_id)
    if not job or not os.path.exists(job.get('input_path', '')):
        return None, (api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404)
    if not job['original_filename'].lower().endswith('.pdf'):
        return None, (api_response(error={'type': 'UnsupportedError', 'message': 'Not a PDF file'}, success=False), 400)
    return job, None


def tool_error_response(e: PdfToolError):
    return api_response(error={'type': 'PdfToolError', 'code': e.code, 'message': str(e)}, success=False), ERROR_STATUS.get(e.code, 400)


@pdf_bp.route('/pdf/info', methods=['POST'])
def pdf_info():
    data = request.get_json(silent=True) or {}
    file_id = data.get('file_id')
    job, error = get_pdf_job(file_id)
    if error:
        return error
    try:
        info = PdfTools.info(job['input_path'])
    except PdfToolError as e:
        return tool_error_response(e)
    touch_file(file_id)
    info.update(file_expiry(file_id))
    info['filename'] = job['original_filename']
    return api_response(data=info)


@pdf_bp.route('/pdf/page/<file_id>/<int:page>', methods=['GET'])
def pdf_page_image(file_id, page):
    job, error = get_pdf_job(file_id)
    if error:
        return error
    width = min(1200, max(60, request.args.get('w', 200, type=int)))
    try:
        image = PdfTools.render_page(job['input_path'], page, width)
    except PdfToolError as e:
        return tool_error_response(e)
    response = send_file(io.BytesIO(image), mimetype='image/jpeg')
    response.headers['Cache-Control'] = 'private, max-age=3600'
    return response


@pdf_bp.route('/pdf/process', methods=['POST'])
def pdf_process():
    data = request.get_json(silent=True) or {}
    tool = data.get('tool')
    if tool not in TOOL_SUFFIXES:
        return api_response(error={'type': 'InvalidRequestError', 'message': f"tool must be one of: {', '.join(sorted(TOOL_SUFFIXES))}"}, success=False), 400

    file_ids = data.get('file_ids') if tool == 'merge' else [data.get('file_id')]
    if not isinstance(file_ids, list) or not file_ids:
        return api_response(error={'type': 'InvalidRequestError', 'message': 'file_id required'}, success=False), 400
    if tool == 'merge' and len(file_ids) < 2:
        return api_response(error={'type': 'PdfToolError', 'code': 'err_pdf_merge_count', 'message': 'At least two PDFs are needed'}, success=False), 400

    options = data.get('options') or {}
    if not isinstance(options, dict):
        return api_response(error={'type': 'InvalidRequestError', 'message': 'options must be an object'}, success=False), 400

    if tool == 'organize':
        extra = options.get('sources') or []
        if not isinstance(extra, list):
            return api_response(error={'type': 'InvalidRequestError', 'message': 'sources must be a list'}, success=False), 400
        file_ids = file_ids + [f for f in extra if f]

    jobs = []
    for file_id in file_ids:
        job, error = get_pdf_job(file_id)
        if error:
            return error
        jobs.append(job)
        touch_file(file_id)

    if tool == 'merge':
        options['names'] = [j['original_filename'] for j in jobs]

    if tool == 'watermark' and options.get('kind') == 'image':
        image_job = conversion_jobs.get(options.get('image_file_id') or '')
        image_path = image_job.get('input_path') if image_job else None
        if not image_path or not os.path.exists(image_path) or not image_path.lower().endswith(IMAGE_EXTENSIONS):
            return api_response(error={'type': 'PdfToolError', 'code': 'err_pdf_watermark_image', 'message': 'Watermark image not found'}, success=False), 400
        options['image_path'] = image_path
    else:
        options.pop('image_path', None)

    source = jobs[0]
    base_name = SUFFIX_RE.sub('', os.path.splitext(source['original_filename'])[0]) or 'document'
    out_base = unique_output_base(current_app.config['OUTPUT_FOLDER'], base_name, TOOL_SUFFIXES[tool])

    job_id = generate_file_id()
    job = {
        'status': 'processing',
        'job_id': job_id,
        'tool': tool,
        'source_file_id': file_ids[0],
        'input_path': source['input_path'],
        'original_filename': source['original_filename'],
        'file_type': 'document',
        'progress': 0,
    }
    conversion_jobs[job_id] = job

    def progress_callback(progress):
        job['progress'] = progress
        emit_progress(job_id, progress, status='processing')

    input_paths = [j['input_path'] for j in jobs]
    tools = PdfTools(progress_callback)
    job['_worker'] = tools
    thread = threading.Thread(target=run_pdf_tool, args=(job, tools, tool, input_paths, out_base, options), daemon=True)
    thread.start()

    return api_response(data={'job_id': job_id, 'status': 'processing'})


def run_pdf_tool(job, tools, tool, input_paths, out_base, options):
    try:
        if job.get('cancel_requested'):
            tools.cancel()
        result_path = tools.run(tool, input_paths, out_base, options)

        job['output_path'] = result_path
        job['input_size'] = sum(os.path.getsize(p) for p in input_paths[:1 if tool != 'merge' else None])
        job['output_size'] = os.path.getsize(result_path)
        if tools.info_result:
            job['compression_info'] = tools.info_result
        if result_path.lower().endswith('.pdf'):
            job['result_file_id'] = register_result_file(result_path)

        job['progress'] = 100
        job['status'] = 'completed'
        emit_complete(job['job_id'], os.path.basename(result_path))
    except Exception as e:
        code = getattr(e, 'code', 'err_pdf_failed')
        job['status'] = 'cancelled' if code == 'err_cancelled' else 'failed'
        job['error'] = str(e)
        job['error_code'] = code
        emit_error(job['job_id'], str(e))
    finally:
        job.pop('_worker', None)
