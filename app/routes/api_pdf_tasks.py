from flask import Blueprint, request

from ..services.editor_tasks import TASKS
from ..utils.client import client_id
from .api_common import api_response

pdf_tasks_bp = Blueprint('pdf_tasks', __name__)


@pdf_tasks_bp.route('/pdf/edit/tasks', methods=['GET'])
def list_tasks():
    tasks = TASKS.list(client_id(), request.args.get('file_id') or None)
    return api_response(data={'tasks': [t.public() for t in tasks]})


@pdf_tasks_bp.route('/pdf/edit/tasks/<task_id>/cancel', methods=['POST'])
def cancel_task(task_id):
    return api_response(data={'cancelled': TASKS.cancel(client_id(), task_id)})
