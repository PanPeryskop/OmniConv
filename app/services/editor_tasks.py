import secrets
import threading
import time
from dataclasses import asdict, dataclass, field

KINDS = ('ocr', 'translate', 'search', 'save', 'sign', 'ai', 'agent', 'fonts')
FINAL = ('done', 'failed', 'cancelled')
KEEP_FINISHED = 60
MIN_INTERVAL = 0.1


@dataclass
class EditorTask:
    id: str
    owner: str
    kind: str
    file_id: str | None = None
    page: int | None = None
    status: str = 'queued'
    stage: str | None = None
    progress: float | None = None
    detail: dict = field(default_factory=dict)
    error: dict | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancelled: bool = False

    def public(self):
        data = asdict(self)
        del data['owner']
        del data['cancelled']
        return data


class TaskRegistry:
    def __init__(self, interval=MIN_INTERVAL):
        self.tasks = {}
        self.lock = threading.Lock()
        self.listeners = []
        self.interval = interval
        self.sent = {}
        self.timers = {}

    def subscribe(self, listener):
        self.listeners.append(listener)

    def notify(self, task):
        for listener in list(self.listeners):
            try:
                listener(task)
            except Exception:
                pass

    def prune(self):
        now = time.time()
        for key in [k for k, t in self.tasks.items() if t.status in FINAL and now - t.updated_at > KEEP_FINISHED]:
            del self.tasks[key]
            self.mark_sent(key)
            del self.sent[key]

    def create(self, owner, kind, file_id=None, page=None):
        task = EditorTask(id='tsk_' + secrets.token_urlsafe(10), owner=owner, kind=kind, file_id=file_id, page=page)
        with self.lock:
            self.prune()
            self.tasks[task.id] = task
            self.mark_sent(task.id)
        self.notify(task)
        return task

    def get(self, task_id):
        with self.lock:
            return self.tasks.get(task_id)

    def update(self, task_id, **fields):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            if task.status in FINAL:
                return task
            before = (task.status, task.stage)
            for key, value in fields.items():
                setattr(task, key, value)
            if task.status == 'queued' and 'status' not in fields:
                task.status = 'running'
            task.updated_at = time.time()
            urgent = before != (task.status, task.stage)
            delay = 0 if urgent else self.sent.get(task_id, 0) + self.interval - time.monotonic()
            if delay > 0:
                self.defer(task_id, delay)
                return task
            self.mark_sent(task_id)
        self.notify(task)
        return task

    def defer(self, task_id, delay):
        if task_id in self.timers:
            return
        timer = threading.Timer(delay, self.flush, (task_id,))
        timer.daemon = True
        self.timers[task_id] = timer
        timer.start()

    def mark_sent(self, task_id):
        self.sent[task_id] = time.monotonic()
        timer = self.timers.pop(task_id, None)
        if timer:
            timer.cancel()

    def flush(self, task_id):
        with self.lock:
            if task_id not in self.timers:
                return
            self.mark_sent(task_id)
            task = self.tasks.get(task_id)
        if task:
            self.notify(task)

    def finish(self, task_id, status='done', error=None):
        fields = {'status': status, 'error': error}
        if status == 'done':
            fields['progress'] = 1.0
        return self.update(task_id, **fields)

    def list(self, owner, file_id=None):
        with self.lock:
            self.prune()
            return [t for t in self.tasks.values() if t.owner == owner and (file_id is None or t.file_id == file_id)]

    def cancel(self, owner, task_id):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task or task.owner != owner or task.status in FINAL:
                return False
            task.cancelled = True
        self.update(task_id, status='cancelled')
        return True


TASKS = TaskRegistry()
