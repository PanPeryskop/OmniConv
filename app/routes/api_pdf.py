import hashlib
import io
import os
import re
import threading
from flask import Blueprint, request, current_app, send_file, g

from .api_common import conversion_jobs, api_response, unique_output_base, touch_file, file_expiry, register_result_file
from ..utils.file_handler import generate_file_id
from ..services.pdf_tools import PdfTools, PdfToolError
from ..services import pdf_ai, pdf_editor, pdf_translate
from ..services.editor_tasks import TASKS
from ..services.font_match import FontLibrary
from ..services.pdf_sign import CERTIFICATES, MAX_CERT_BYTES, SignError
from .websocket import emit_progress, emit_complete, emit_error
from ..services.job_registry import registry
from ..utils.client import client_id

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
    'edit': 'edited',
}

SUFFIX_RE = re.compile(r'(?:_(?:' + '|'.join(sorted(set(TOOL_SUFFIXES.values()))) + r')(?:_\d+)?)+$')
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')

ERROR_STATUS = {
    'err_pdf_password': 423,
    'err_pdf_wrong_password': 403,
}


def get_pdf_job(file_id):
    job = conversion_jobs.owned(file_id)
    if not job or not os.path.exists(job.get('input_path', '')):
        return None, (api_response(error={'type': 'NotFoundError', 'message': 'File not found'}, success=False), 404)
    if not job['original_filename'].lower().endswith('.pdf'):
        return None, (api_response(error={'type': 'UnsupportedError', 'message': 'Not a PDF file'}, success=False), 400)
    return job, None


def file_digest(job):
    if not job.get('digest'):
        sha = hashlib.sha256()
        with open(job['input_path'], 'rb') as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b''):
                sha.update(chunk)
        job['digest'] = sha.hexdigest()
    return job['digest']


def resolve_edit_ops(ops):
    if not isinstance(ops, list):
        return None, (api_response(error={'type': 'InvalidRequestError', 'message': 'ops must be a list'}, success=False), 400)
    resolved = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        op = dict(op)
        op.pop('path', None)
        if op.get('type') == 'image' and op.get('file_id'):
            image_job = conversion_jobs.owned(op['file_id'])
            path = image_job.get('input_path') if image_job else None
            if not path or not os.path.exists(path) or not path.lower().endswith(IMAGE_EXTENSIONS):
                return None, (api_response(error={'type': 'PdfToolError', 'code': 'err_pdf_edit_image_missing', 'message': 'An inserted image is no longer available'}, success=False), 400)
            touch_file(op['file_id'])
            op['path'] = path
        resolved.append(op)
    return resolved, None


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


@pdf_bp.route('/pdf/edit/pages', methods=['POST'])
def pdf_edit_pages():
    data = request.get_json(silent=True) or {}
    job, error = get_pdf_job(data.get('file_id'))
    if error:
        return error
    try:
        sizes = pdf_editor.page_sizes(job['input_path'])
    except Exception:
        return api_response(error={'type': 'PdfToolError', 'code': 'err_pdf_damaged', 'message': 'The PDF could not be opened'}, success=False), 400
    touch_file(data.get('file_id'))
    return api_response(data={'pages': sizes, 'digest': file_digest(job)})


@pdf_bp.route('/pdf/edit/keepalive', methods=['POST'])
def pdf_edit_keepalive():
    data = request.get_json(silent=True) or {}
    job, error = get_pdf_job(data.get('file_id'))
    if error:
        return error
    touch_file(data.get('file_id'))
    images = data.get('images') if isinstance(data.get('images'), list) else []
    alive = [image_id for image_id in images if conversion_jobs.owned(image_id)]
    for image_id in alive:
        touch_file(image_id)
    return api_response(data={'images': alive})


@pdf_bp.route('/pdf/edit/font/<file_id>/<int:xref>', methods=['GET'])
def pdf_edit_font(file_id, xref):
    job, error = get_pdf_job(file_id)
    if error:
        return error
    font = pdf_editor.web_font(job['input_path'], xref)
    if not font:
        return api_response(error={'type': 'NotFoundError', 'message': 'Font not available'}, success=False), 404
    response = send_file(io.BytesIO(font[1]), mimetype=f'font/{font[0]}')
    response.headers['Cache-Control'] = 'private, max-age=3600'
    return response


@pdf_bp.route('/pdf/edit/certificate', methods=['POST'])
def pdf_edit_certificate():
    upload = request.files.get('file')
    if not upload:
        return api_response(error={'type': 'InvalidRequestError', 'code': 'err_cert_invalid', 'message': 'Certificate file required'}, success=False), 400
    data = upload.read(MAX_CERT_BYTES + 1)
    try:
        cert_id, info = CERTIFICATES.put(client_id(), data, request.form.get('password', ''))
    except SignError as e:
        return api_response(error={'type': 'SignError', 'code': e.code, 'message': str(e)}, success=False), 400
    return api_response(data={'cert_id': cert_id, **info})


def ai_error_response(e):
    return api_response(error={'type': 'AiError', 'code': e.code, 'message': str(e)}, success=False), 400


@pdf_bp.route('/pdf/edit/ai/status', methods=['GET'])
def pdf_edit_ai_status():
    return api_response(data={'status': pdf_ai.status()})


def task_failed(task, code, message):
    TASKS.finish(task.id, 'cancelled' if code == 'err_cancelled' else 'failed', {'code': code, 'message': message})


def cancel_point(task):
    if task.cancelled:
        raise PdfToolError('err_cancelled', 'Cancelled')


@pdf_bp.route('/pdf/edit/fonts/status', methods=['GET'])
def pdf_edit_fonts_status():
    library = FontLibrary.shared()
    done, total = library.progress
    return api_response(data={'ready': library.ready.is_set(), 'done': done, 'total': total})


@pdf_bp.route('/pdf/edit/ai', methods=['POST'])
def pdf_edit_ai():
    data = request.get_json(silent=True) or {}
    file_id = data.get('file_id') if isinstance(data.get('file_id'), str) else None
    task = TASKS.create(client_id(), 'ai', file_id)
    TASKS.update(task.id, status='running')
    try:
        text = pdf_ai.rewrite(str(data.get('text') or ''), data.get('mode'), str(data.get('language') or '')[:40])
    except pdf_ai.AiError as e:
        task_failed(task, e.code, str(e))
        return ai_error_response(e)
    except Exception as e:
        task_failed(task, 'err_ai_failed', str(e))
        raise
    TASKS.finish(task.id)
    return api_response(data={'text': text})


@pdf_bp.route('/pdf/edit/translate', methods=['POST'])
def pdf_edit_translate():
    data = request.get_json(silent=True) or {}
    job, error = get_pdf_job(data.get('file_id'))
    if error:
        return error
    ops, error = resolve_edit_ops(data.get('ops') or [])
    if error:
        return error
    language = str(data.get('language') or '')[:40]
    try:
        page = int(data.get('page', 0))
    except (TypeError, ValueError):
        return api_response(error={'type': 'InvalidRequestError', 'message': 'Invalid page'}, success=False), 400
    task = TASKS.create(client_id(), 'translate', data.get('file_id'), page)
    try:
        TASKS.update(task.id, status='running', stage='layout', progress=0.0)
        layout = pdf_editor.render_preview(job['input_path'], page, ops, 100)
        if layout is None:
            task_failed(task, 'err_pdf_ranges', 'Page out of range')
            return api_response(error={'type': 'PdfToolError', 'code': 'err_pdf_ranges', 'message': 'Page out of range'}, success=False), 400
        if layout.get('ocr_pending'):
            task_failed(task, 'err_ocr_pending', 'Text recognition is still running')
            return api_response(error={'type': 'PdfToolError', 'code': 'err_ocr_pending', 'message': 'Text recognition is still running'}, success=False), 409
        cancel_point(task)
        if not pdf_translate.has_glossary(job['input_path'], language):
            TASKS.update(task.id, stage='glossary', progress=0.1)
        context = pdf_translate.page_context(job['input_path'], page, language)
        cancel_point(task)
        TASKS.update(task.id, stage='translate', progress=0.2, detail={'blocks': len(layout.get('blocks') or []), 'terms': len(context.glossary)})
        result = pdf_ai.translate_page(layout, page, language, context=context)
        cancel_point(task)
        TASKS.update(task.id, stage='ops', progress=0.9, detail={'blocks': len(layout.get('blocks') or []), 'ops': len(result)})
    except (TypeError, ValueError):
        task_failed(task, 'err_pdf_edit', 'Invalid page')
        return api_response(error={'type': 'InvalidRequestError', 'message': 'Invalid page'}, success=False), 400
    except PdfToolError as e:
        task_failed(task, e.code, str(e))
        return tool_error_response(e)
    except pdf_ai.AiError as e:
        task_failed(task, e.code, str(e))
        return ai_error_response(e)
    except Exception as e:
        task_failed(task, 'err_ai_failed', str(e))
        raise
    touch_file(data.get('file_id'))
    TASKS.finish(task.id)
    return api_response(data={'ops': result})


@pdf_bp.route('/pdf/edit/search', methods=['POST'])
def pdf_edit_search():
    data = request.get_json(silent=True) or {}
    job, error = get_pdf_job(data.get('file_id'))
    if error:
        return error
    ops, error = resolve_edit_ops(data.get('ops') or [])
    if error:
        return error
    kinds = data.get('patterns') if isinstance(data.get('patterns'), list) else []
    query = str(data.get('query') or '')[:200]
    if not query.strip() and not kinds:
        return api_response(data={'matches': [], 'truncated': False})
    task = TASKS.create(client_id(), 'search', data.get('file_id'))
    TASKS.update(task.id, status='running')

    def progress(done, total):
        cancel_point(task)
        TASKS.update(task.id, progress=done / total if total else None, detail={'done': done, 'total': total})

    try:
        matches, truncated = pdf_editor.search_document(job['input_path'], ops, query, kinds, bool(data.get('whole_word')), progress)
    except PdfToolError as e:
        task_failed(task, e.code, str(e))
        return tool_error_response(e)
    except Exception as e:
        task_failed(task, 'err_pdf_edit', str(e))
        return api_response(error={'type': 'PdfToolError', 'code': 'err_pdf_edit', 'message': str(e)}, success=False), 400
    touch_file(data.get('file_id'))
    TASKS.update(task.id, detail={**task.detail, 'matches': len(matches)})
    TASKS.finish(task.id)
    return api_response(data={'matches': matches, 'truncated': truncated})


@pdf_bp.route('/pdf/edit/page', methods=['POST'])
def pdf_edit_page():
    data = request.get_json(silent=True) or {}
    job, error = get_pdf_job(data.get('file_id'))
    if error:
        return error
    ops, error = resolve_edit_ops(data.get('ops') or [])
    if error:
        return error
    touch_file(data.get('file_id'))
    g.edit_file_id = data.get('file_id')
    try:
        page = int(data.get('page', 0))
        width = min(3000, max(100, int(data.get('width', 800))))
        layout = pdf_editor.render_preview(job['input_path'], page, ops, width)
    except (TypeError, ValueError):
        return api_response(error={'type': 'InvalidRequestError', 'message': 'Invalid page or width'}, success=False), 400
    except Exception as e:
        return api_response(error={'type': 'PdfToolError', 'code': 'err_pdf_edit', 'message': str(e)}, success=False), 400
    if layout is None:
        return api_response(error={'type': 'PdfToolError', 'code': 'err_pdf_ranges', 'message': 'Page out of range'}, success=False), 400
    return api_response(data=layout)


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

    if tool == 'edit':
        options['ops'], error = resolve_edit_ops(options.get('ops'))
        if error:
            return error
        cert_id = options.pop('cert_id', None)
        options.pop('certificate', None)
        if cert_id:
            options['certificate'] = CERTIFICATES.take(cert_id, client_id())
            if not options['certificate']:
                return api_response(error={'type': 'SignError', 'code': 'err_cert_missing', 'message': 'Load the certificate again'}, success=False), 400
        if not options['ops']:
            return api_response(error={'type': 'PdfToolError', 'code': 'err_pdf_edit_empty', 'message': 'Nothing to save'}, success=False), 400

    if tool == 'watermark' and options.get('kind') == 'image':
        image_job = conversion_jobs.owned(options.get('image_file_id'))
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
    title = source['original_filename'] if len(jobs) == 1 or tool != 'merge' else f"{source['original_filename']} +{len(jobs) - 1}"
    registry.start(job_id, client_id(), 'pdf', title, src='pdf', dst=tool)

    def progress_callback(progress):
        job['progress'] = progress
        registry.progress(job_id, progress)
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
            job['result_file_id'] = register_result_file(result_path, owner=job.get('owner'))

        job['progress'] = 100
        job['status'] = 'completed'
        registry.complete(job['job_id'], result_path, job['input_size'], job['output_size'])
        emit_complete(job['job_id'], os.path.basename(result_path))
    except Exception as e:
        code = getattr(e, 'code', 'err_pdf_failed')
        job['status'] = 'cancelled' if code == 'err_cancelled' else 'failed'
        job['error'] = str(e)
        job['error_code'] = code
        registry.fail(job['job_id'], job['error'], code, cancelled=code == 'err_cancelled')
        emit_error(job['job_id'], str(e))
    finally:
        job.pop('_worker', None)
