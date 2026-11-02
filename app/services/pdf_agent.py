import secrets
import threading
import time
from dataclasses import dataclass, field

SESSION_TTL = 2 * 3600
MAX_SESSIONS = 3
MAX_STEPS = 12
MAX_TOOL_CALLS = 40
MAX_PROPOSALS = 60


@dataclass
class AgentSession:
    id: str
    owner: str
    file_id: str
    messages: list = field(default_factory=list)
    stopped: bool = False
    created_at: float = field(default_factory=time.time)
    used_at: float = field(default_factory=time.time)


class AgentSessionStore:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()

    def prune(self):
        now = time.time()
        for key in [k for k, v in self.sessions.items() if now - v.used_at > SESSION_TTL]:
            del self.sessions[key]

    def create(self, owner, file_id):
        with self.lock:
            self.prune()
            mine = sorted((s for s in self.sessions.values() if s.owner == owner), key=lambda s: s.used_at)
            for old in mine[:max(0, len(mine) - MAX_SESSIONS + 1)]:
                del self.sessions[old.id]
            session = AgentSession(id='ses_' + secrets.token_urlsafe(10), owner=owner, file_id=file_id)
            self.sessions[session.id] = session
            return session

    def get(self, owner, session_id):
        with self.lock:
            session = self.sessions.get(session_id)
            if not session or session.owner != owner:
                return None
            session.used_at = time.time()
            return session


SESSIONS = AgentSessionStore()


def run_turn(session, text, ctx, provider, emit):
    raise NotImplementedError
