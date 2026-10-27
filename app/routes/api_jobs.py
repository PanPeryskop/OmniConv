import os
import re
import time

from flask import Blueprint, send_file

from .api_common import api_response, conversion_jobs
from ..services.job_registry import registry
from ..utils.client import client_id

jobs_bp = Blueprint('jobs', __name__)

JOB_SUFFIX = re.compile(r'_[0-9a-f]{8}(?=\.[^.]+$)')


def not_found():
    return api_response(error={'type': 'NotFoundError', 'message': 'Job not found'}, success=False), 404


@jobs_bp.route('/jobs', methods=['GET'])
def list_jobs():
    return api_response(data={
        'jobs': registry.list(client_id()),
        'retention_hours': registry.retention_seconds / 3600,
        'server_time': time.time(),
    })


@jobs_bp.route('/jobs/<job_id>/download', methods=['GET'])
def download_job(job_id):
    job = registry.get(job_id, client_id())
    path = job and job.get('output_path')
    if not job or job['status'] != 'completed' or not path or not os.path.isfile(path):
        return not_found()
    name = job.get('output_name') or os.path.basename(path)
    if job['kind'] == 'convert':
        name = JOB_SUFFIX.sub('', name)
    return send_file(path, as_attachment=True, download_name=name)


@jobs_bp.route('/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    owner = client_id()
    job = registry.get(job_id, owner)
    if not job:
        return not_found()
    if job['status'] == 'running':
        active = conversion_jobs.get(job_id)
        if active is None:
            return api_response(error={'type': 'ConflictError', 'code': 'err_job_not_cancellable', 'message': 'This job cannot be cancelled'}, success=False), 409
        active['cancel_requested'] = True
        worker = active.get('_worker')
        if worker is not None and hasattr(worker, 'cancel'):
            worker.cancel()
        return api_response(data={'job_id': job_id, 'status': 'cancelling'})
    registry.delete(job_id, owner)
    return api_response(data={'job_id': job_id, 'deleted': True})


@jobs_bp.route('/jobs', methods=['DELETE'])
def clear_finished_jobs():
    return api_response(data={'deleted': registry.delete_finished(client_id())})
