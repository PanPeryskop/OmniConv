from flask import request
from flask_socketio import SocketIO, join_room

from ..services.editor_tasks import TASKS
from ..utils.client import COOKIE_NAME, VALID_ID

socketio = SocketIO()

def init_socketio(app):
    socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')
    return socketio

def emit_progress(job_id, progress, status='converting'):
    socketio.emit('conversion_progress', {
        'job_id': job_id,
        'progress': progress,
        'status': status
    })

def emit_complete(job_id, filename):
    socketio.emit('conversion_complete', {
        'job_id': job_id,
        'filename': filename,
        'status': 'completed'
    })

def emit_error(job_id, error_message):
    socketio.emit('conversion_error', {
        'job_id': job_id,
        'error': error_message,
        'status': 'failed'
    })


def client_room(owner):
    return f'client:{owner}'


@socketio.on('editor_join')
def editor_join(*_):
    value = request.cookies.get(COOKIE_NAME, '')
    if not VALID_ID.match(value):
        return {'joined': False}
    join_room(client_room(value))
    return {'joined': True}


def emit_task(task):
    socketio.emit('editor_task', task.public(), to=client_room(task.owner))


TASKS.subscribe(emit_task)
