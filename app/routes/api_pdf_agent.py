import json
import queue
import threading

from flask import Blueprint, Response, copy_current_request_context, g, request, stream_with_context

from ..services import pdf_editor
from ..services.agent_providers import provider_from_env
from ..services.pdf_agent import SESSIONS, as_int, run_turn
from ..services.pdf_agent_tools import ToolContext, block_id
from ..utils.client import client_id
from .api_common import api_response, touch_file
from .api_pdf import get_pdf_job, resolve_edit_ops

pdf_agent_bp = Blueprint('pdf_agent', __name__)

HEARTBEAT = 15
MAX_TEXT = 4000
MAX_BLOCKS = 200
SCOPE_KINDS = ('page', 'pages', 'document', 'selection')
DECISIONS = ('accepted', 'rejected')


def invalid(message):
    return api_response(error={'type': 'InvalidRequestError', 'message': message}, success=False), 400


def owned_session(session_id):
    session = SESSIONS.get(client_id(), session_id)
    if not session:
        return None, (api_response(error={'type': 'NotFoundError', 'message': 'Session not found'}, success=False), 404)
    return session, None


def int_list(values, limit=MAX_BLOCKS):
    values = values if isinstance(values, list) else []
    return [v for v in (as_int(x) for x in values[:limit]) if v is not None]


def resolve_selection(path, ops, raw):
    if not isinstance(raw, dict) or as_int(raw.get('page')) is None:
        return None
    page = as_int(raw['page'])
    ids = [b for b in (raw.get('block_ids') or [])[:MAX_BLOCKS] if isinstance(b, str)] if isinstance(raw.get('block_ids'), list) else []
    indexes = int_list(raw.get('block_indexes'))
    if indexes:
        try:
            layout = pdf_editor.render_preview(path, page, ops, 100)
        except Exception:
            layout = None
        blocks = (layout or {}).get('blocks') or []
        ids += [block_id(page, i, blocks[i]) for i in indexes if 0 <= i < len(blocks)]
    return {'page': page, 'block_ids': list(dict.fromkeys(ids)), 'text': str(raw.get('text') or '')[:MAX_TEXT]}


def resolve_scope(raw, selection):
    raw = raw if isinstance(raw, dict) else {}
    kind = raw.get('kind') if raw.get('kind') in SCOPE_KINDS else 'page'
    pages = int_list(raw.get('pages'))
    block_ids = [b for b in raw.get('block_ids') or [] if isinstance(b, str)][:MAX_BLOCKS] if isinstance(raw.get('block_ids'), list) else []
    if kind == 'selection' and selection:
        pages = pages or [selection['page']]
        block_ids = block_ids or selection['block_ids']
    return {'kind': kind, 'pages': pages, 'block_ids': block_ids}


def sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n'


@pdf_agent_bp.route('/pdf/edit/agent/status', methods=['GET'])
def agent_status():
    provider = provider_from_env()
    return api_response(data={'status': provider.status(), 'provider': provider.name, 'model': provider.model()})


@pdf_agent_bp.route('/pdf/edit/agent/sessions', methods=['POST'])
def create_session():
    data = request.get_json(silent=True) or {}
    _job, error = get_pdf_job(data.get('file_id'))
    if error:
        return error
    touch_file(data['file_id'])
    session = SESSIONS.create(client_id(), data['file_id'])
    return api_response(data={'session_id': session.id})


@pdf_agent_bp.route('/pdf/edit/agent/sessions/<session_id>/messages', methods=['POST'])
def send_message(session_id):
    session, error = owned_session(session_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    text = str(data.get('text') or '').strip()[:MAX_TEXT]
    if not text:
        return invalid('text is required')
    job, error = get_pdf_job(session.file_id)
    if error:
        return error
    ops, error = resolve_edit_ops(data.get('ops') or [])
    if error:
        return error
    selection = resolve_selection(job['input_path'], ops, data.get('selection'))
    scope = resolve_scope(data.get('scope'), selection)
    if not SESSIONS.begin(session):
        return api_response(error={'type': 'AgentError', 'code': 'err_agent_failed', 'message': 'The agent is still answering'}, success=False), 409
    touch_file(session.file_id)
    events = queue.Queue()
    ctx = ToolContext(path=job['input_path'], file_id=session.file_id, ops=ops, working_ops=list(ops), scope=scope)
    provider = provider_from_env()
    owner = client_id()

    @copy_current_request_context
    def work():
        g.client_id = owner
        g.edit_file_id = session.file_id
        try:
            run_turn(session, text, ctx, provider, lambda event, payload: events.put((event, payload)), selection=selection)
        except Exception as e:
            events.put(('error', {'code': 'err_agent_failed', 'message': str(e) or type(e).__name__}))
        finally:
            SESSIONS.end(session)
            events.put(None)

    worker = threading.Thread(target=work, name=f'agent-{session.id}', daemon=True)
    worker.start()

    def generate():
        try:
            while True:
                try:
                    item = events.get(timeout=HEARTBEAT)
                except queue.Empty:
                    yield ': ping\n\n'
                    continue
                if item is None:
                    return
                yield sse(*item)
        finally:
            if worker.is_alive():
                session.stopped = True

    headers = {'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    return Response(stream_with_context(generate()), mimetype='text/event-stream', headers=headers)


@pdf_agent_bp.route('/pdf/edit/agent/sessions/<session_id>/stop', methods=['POST'])
def stop_session(session_id):
    session, error = owned_session(session_id)
    if error:
        return error
    running = session.busy
    if running:
        session.stopped = True
    return api_response(data={'stopped': running})


@pdf_agent_bp.route('/pdf/edit/agent/sessions/<session_id>/feedback', methods=['POST'])
def session_feedback(session_id):
    session, error = owned_session(session_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    decision = data.get('decision')
    proposal = session.proposals.get(str(data.get('proposal_id') or ''))
    if decision not in DECISIONS or not proposal:
        return invalid('Unknown proposal or decision')
    title = f' "{proposal["title"]}"' if proposal.get('title') else ''
    page = f' on page {proposal["page"]}' if proposal.get('page') is not None else ''
    session.notes.append(f'Note from the editor: the user {decision} proposal {data["proposal_id"]}{title}{page}.')
    return api_response(data={})
