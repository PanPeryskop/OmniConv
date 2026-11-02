from flask import Blueprint

from .api_common import api_response

pdf_agent_bp = Blueprint('pdf_agent', __name__)


def not_ready():
    return api_response(error={'type': 'NotImplementedError', 'code': 'err_agent_failed', 'message': 'Agent is not available yet'}, success=False), 501


@pdf_agent_bp.route('/pdf/edit/agent/status', methods=['GET'])
def agent_status():
    return not_ready()


@pdf_agent_bp.route('/pdf/edit/agent/sessions', methods=['POST'])
def create_session():
    return not_ready()


@pdf_agent_bp.route('/pdf/edit/agent/sessions/<session_id>/messages', methods=['POST'])
def send_message(session_id):
    return not_ready()


@pdf_agent_bp.route('/pdf/edit/agent/sessions/<session_id>/stop', methods=['POST'])
def stop_session(session_id):
    return not_ready()


@pdf_agent_bp.route('/pdf/edit/agent/sessions/<session_id>/feedback', methods=['POST'])
def session_feedback(session_id):
    return not_ready()
