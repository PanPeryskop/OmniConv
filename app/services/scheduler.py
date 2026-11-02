import os
import shutil
import time
import threading

from .job_registry import registry


def cleanup_job_store(store, idle_hours, result_hours):
    now = time.time()
    for job_id, job in list(store.items()):
        created_at = job.get('created_at')
        if created_at is None:
            job['created_at'] = now
            continue
        hours = idle_hours if job.get('status') == 'uploaded' else result_hours
        if now - created_at > hours * 3600:
            store.pop(job_id, None)


def active_input_paths():
    from ..routes.api_common import conversion_jobs, IDLE_STATUSES
    return {
        os.path.normcase(os.path.abspath(job['input_path']))
        for job in list(conversion_jobs.values())
        if job.get('status') not in IDLE_STATUSES and job.get('input_path')
    }


def fail_orphaned_jobs():
    from ..routes.api_common import conversion_jobs
    from ..routes.youtube import JOBS
    running = registry.running_ids()
    active = set(conversion_jobs) | set(JOBS)
    registry.fail_orphans(running - active)


def sweep_folder(folder, max_age_seconds, protected=frozenset()):
    if not folder or not os.path.exists(folder):
        return
    now = time.time()
    for filename in os.listdir(folder):
        path = os.path.join(folder, filename)
        if os.path.normcase(os.path.abspath(path)) in protected:
            continue
        try:
            if now - os.path.getmtime(path) <= max_age_seconds:
                continue
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
        except Exception:
            pass


def run_cleanup(app):
    max_age = app.config.get('CLEANUP_AFTER_HOURS', 1) * 3600
    registry.cleanup_expired()
    sweep_folder(app.config.get('UPLOAD_FOLDER'), max_age, active_input_paths())
    sweep_folder(app.config.get('OUTPUT_FOLDER'), max_age, registry.protected_paths())


def start_cleanup_scheduler(app):
    def cleanup_task():
        with app.app_context():
            while True:
                time.sleep(600)
                hours = app.config.get('CLEANUP_AFTER_HOURS', 1)
                result_hours = max(hours, app.config.get('RESULT_RETENTION_HOURS', hours))

                try:
                    from ..routes.api_common import conversion_jobs
                    cleanup_job_store(conversion_jobs, hours, result_hours)
                except Exception:
                    pass

                try:
                    from ..routes.youtube import JOBS
                    cleanup_job_store(JOBS, hours, result_hours)
                except Exception:
                    pass

                try:
                    fail_orphaned_jobs()
                except Exception:
                    pass

                try:
                    run_cleanup(app)
                except Exception:
                    pass

    thread = threading.Thread(target=cleanup_task, daemon=True)
    thread.start()
