import os

from flask import Blueprint, request

from ..services.editor_tasks import TASKS
from ..utils.client import client_id
from .api_common import api_response

pdf_tasks_bp = Blueprint('pdf_tasks', __name__)

TEST_FIELDS = ('status', 'stage', 'progress', 'detail')


def not_found():
    return api_response(error={'code': 'err_not_found', 'message': 'Not found'}, success=False), 404


@pdf_tasks_bp.route('/pdf/edit/tasks', methods=['GET'])
def list_tasks():
    file_id = request.args.get('file_id') or None
    tasks = [t for t in TASKS.list(client_id()) if file_id is None or t.file_id in (None, file_id)]
    return api_response(data={'tasks': [t.public() for t in tasks]})


@pdf_tasks_bp.route('/pdf/edit/tasks/<task_id>/cancel', methods=['POST'])
def cancel_task(task_id):
    return api_response(data={'cancelled': TASKS.cancel(client_id(), task_id)})


@pdf_tasks_bp.route('/pdf/edit/tasks/test', methods=['POST'])
def drive_task():
    if os.environ.get('OMNICONV_TEST_ROUTES') != '1':
        return not_found()
    body = request.get_json(silent=True) or {}
    if body.get('task_id'):
        task = TASKS.get(body['task_id'])
        if not task or task.owner != client_id():
            return not_found()
    else:
        task = TASKS.create(client_id(), body.get('kind', 'ocr'), body.get('file_id'), body.get('page'))
    if body.get('finish'):
        TASKS.finish(task.id, body['finish'], body.get('error'))
    else:
        TASKS.update(task.id, **{key: body[key] for key in TEST_FIELDS if key in body})
    return api_response(data={'task': task.public(), 'cancelled': task.cancelled})
