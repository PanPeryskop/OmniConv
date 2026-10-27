import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    src TEXT NOT NULL DEFAULT '',
    dst TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error TEXT,
    error_code TEXT,
    output_path TEXT,
    output_name TEXT,
    input_size INTEGER,
    output_size INTEGER,
    created_at REAL NOT NULL,
    finished_at REAL,
    expires_at REAL
);
CREATE INDEX IF NOT EXISTS jobs_owner_created ON jobs (owner, created_at DESC);
"""

FINISHED = ('completed', 'failed', 'cancelled')


class JobRegistry:
    def __init__(self):
        self.path = None
        self.retention_seconds = 24 * 3600
        self._lock = threading.Lock()
        self._progress = {}

    def init_app(self, app):
        folder = str(app.config['DATA_FOLDER'])
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, 'omniconv.db')
        self.retention_seconds = float(app.config['RESULT_RETENTION_HOURS']) * 3600
        with self._lock, self._connect() as db:
            db.executescript(SCHEMA)
            db.execute(
                "UPDATE jobs SET status = 'failed', error_code = 'err_job_interrupted', finished_at = ?, expires_at = ? "
                "WHERE status = 'running'",
                (time.time(), time.time() + self.retention_seconds),
            )

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _write(self, sql, params=()):
        if not self.path:
            return 0
        with self._lock:
            db = self._connect()
            try:
                with db:
                    return db.execute(sql, params).rowcount
            finally:
                db.close()

    def _read(self, sql, params=()):
        if not self.path:
            return []
        db = self._connect()
        try:
            return [dict(row) for row in db.execute(sql, params).fetchall()]
        finally:
            db.close()

    def start(self, job_id, owner, kind, title, src='', dst=''):
        self._write(
            "INSERT OR REPLACE INTO jobs (id, owner, kind, title, src, dst, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
            (job_id, owner or 'anonymous', kind, title or '', src or '', dst or '', time.time()),
        )
        self._progress[job_id] = 0

    def progress(self, job_id, value):
        if job_id in self._progress:
            self._progress[job_id] = float(value or 0)

    def complete(self, job_id, output_path, input_size=None, output_size=None, title=None):
        self._progress.pop(job_id, None)
        if output_size is None and output_path and os.path.isfile(output_path):
            output_size = os.path.getsize(output_path)
        now = time.time()
        self._write(
            "UPDATE jobs SET status = 'completed', output_path = ?, output_name = ?, input_size = ?, output_size = ?, "
            "title = COALESCE(?, title), finished_at = ?, expires_at = ?, error = NULL, error_code = NULL WHERE id = ?",
            (output_path, os.path.basename(output_path or ''), input_size, output_size, title, now,
             now + self.retention_seconds, job_id),
        )

    def fail(self, job_id, error=None, error_code=None, cancelled=False):
        self._progress.pop(job_id, None)
        now = time.time()
        self._write(
            "UPDATE jobs SET status = ?, error = ?, error_code = ?, finished_at = ?, expires_at = ? "
            "WHERE id = ? AND status = 'running'",
            ('cancelled' if cancelled else 'failed', (str(error)[:500] if error else None), error_code, now,
             now + self.retention_seconds, job_id),
        )

    def move_output(self, job_id, output_path):
        self._write(
            "UPDATE jobs SET output_path = ?, output_name = ? WHERE id = ?",
            (output_path, os.path.basename(output_path), job_id),
        )

    def _decorate(self, row):
        row['progress'] = 100 if row['status'] == 'completed' else self._progress.get(row['id'], 0)
        row['file_available'] = bool(
            row['status'] == 'completed' and row['output_path'] and os.path.isfile(row['output_path'])
        )
        row.pop('output_path', None)
        row.pop('owner', None)
        return row

    def list(self, owner, limit=100):
        rows = self._read(
            "SELECT * FROM jobs WHERE owner = ? AND (expires_at IS NULL OR expires_at > ?) "
            "ORDER BY created_at DESC LIMIT ?",
            (owner, time.time(), limit),
        )
        return [self._decorate(row) for row in rows]

    def get(self, job_id, owner):
        rows = self._read(
            "SELECT * FROM jobs WHERE id = ? AND owner = ? AND (expires_at IS NULL OR expires_at > ?)",
            (job_id, owner, time.time()),
        )
        return rows[0] if rows else None

    def find_by_output_name(self, owner, name):
        rows = self._read(
            "SELECT * FROM jobs WHERE owner = ? AND output_name = ? AND status = 'completed' "
            "AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
            (owner, name, time.time()),
        )
        return rows[0] if rows else None

    def _remove_file(self, path):
        if not path or not os.path.isfile(path):
            return
        still_used = self._read(
            "SELECT 1 FROM jobs WHERE output_path = ? AND status = 'completed' AND expires_at > ? LIMIT 1",
            (path, time.time()),
        )
        if not still_used:
            try:
                os.remove(path)
            except OSError:
                pass

    def delete(self, job_id, owner):
        row = self.get(job_id, owner)
        if not row or row['status'] not in FINISHED:
            return False
        self._write("DELETE FROM jobs WHERE id = ?", (job_id,))
        self._remove_file(row['output_path'])
        return True

    def delete_finished(self, owner):
        rows = self._read(
            "SELECT id, output_path FROM jobs WHERE owner = ? AND status IN ('completed', 'failed', 'cancelled')",
            (owner,),
        )
        for row in rows:
            self._write("DELETE FROM jobs WHERE id = ?", (row['id'],))
            self._remove_file(row['output_path'])
        return len(rows)

    def cleanup_expired(self):
        rows = self._read("SELECT id, output_path FROM jobs WHERE expires_at IS NOT NULL AND expires_at <= ?", (time.time(),))
        for row in rows:
            self._write("DELETE FROM jobs WHERE id = ?", (row['id'],))
            self._remove_file(row['output_path'])
        return len(rows)

    def protected_paths(self):
        rows = self._read(
            "SELECT output_path FROM jobs WHERE status = 'completed' AND output_path IS NOT NULL AND expires_at > ?",
            (time.time(),),
        )
        return {os.path.normcase(os.path.abspath(row['output_path'])) for row in rows}


registry = JobRegistry()
