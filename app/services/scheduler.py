import os
import shutil
import time
import threading

from .job_registry import registry


def cleanup_job_store(store, max_age_hours):
    keys_to_delete = []
    now = time.time()
    for job_id, job in store.items():
        created_at = job.get('created_at')
        if created_at is None:
            job['created_at'] = now
            continue

        if now - created_at > max_age_hours * 3600:
            keys_to_delete.append(job_id)

    for key in keys_to_delete:
        del store[key]


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
    sweep_folder(app.config.get('UPLOAD_FOLDER'), max_age)
    sweep_folder(app.config.get('OUTPUT_FOLDER'), max_age, registry.protected_paths())


def start_cleanup_scheduler(app):
    def cleanup_task():
        with app.app_context():
            while True:
                time.sleep(600)
                hours = app.config.get('CLEANUP_AFTER_HOURS', 1)

                try:
                    from ..routes.api_common import conversion_jobs
                    cleanup_job_store(conversion_jobs, hours)
                except Exception:
                    pass

                try:
                    from ..routes.youtube import JOBS
                    cleanup_job_store(JOBS, hours)
                except Exception:
                    pass

                try:
                    run_cleanup(app)
                except Exception:
                    pass

    thread = threading.Thread(target=cleanup_task, daemon=True)
    thread.start()
