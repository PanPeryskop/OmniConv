from flask_socketio import SocketIO, emit

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
