import os
import time
import threading

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

def start_cleanup_scheduler(app):
    def cleanup_task():
        with app.app_context():
            while True:
                time.sleep(1800)
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
                
                now = time.time()
                folders = [app.config.get('UPLOAD_FOLDER'), app.config.get('OUTPUT_FOLDER')]
                for folder in folders:
                    if not folder or not os.path.exists(folder):
                        continue
                    for filename in os.listdir(folder):
                        file_path = os.path.join(folder, filename)
                        try:
                            if os.path.isfile(file_path):
                                mtime = os.path.getmtime(file_path)
                                if now - mtime > hours * 3600:
                                    os.remove(file_path)
                            elif os.path.isdir(file_path):
                                mtime = os.path.getmtime(file_path)
                                if now - mtime > hours * 3600:
                                    import shutil
                                    shutil.rmtree(file_path)
                        except Exception:
                            pass

    thread = threading.Thread(target=cleanup_task, daemon=True)
    thread.start()
