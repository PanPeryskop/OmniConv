import dataclasses
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

from .agent_providers import ProviderError, StepStopped, validate_args
from .editor_tasks import TASKS
from .pdf_agent_tools import ToolResult, ToolSpec, tool_specs

SESSION_TTL = 2 * 3600
MAX_SESSIONS = 3
MAX_STEPS = 12
MAX_TOOL_CALLS = 40
MAX_PROPOSALS = 60
TOOL_RESULT_CHARS = 6000
CONTEXT_BUDGET = int(os.environ.get('AGENT_CONTEXT_TOKENS', 24000))
CONTEXT_LIMIT = int(CONTEXT_BUDGET * 1.5)
CHARS_PER_TOKEN = 3.5
SUMMARY_CHARS = 200
SELECTION_CHARS = 1500
BLOCK_PAGE_RE = re.compile(r'^p(\d+)b\d+-')
STOPPED_TEXT = 'The user stopped this answer.'

SYSTEM_PROMPT = (
    'You are the editing assistant built into a PDF editor. The user has a PDF document open and asks you to change '
    'or check it. You work only through the tools.\n'
    'Rules:\n'
    '1. Read before you change: call list_pages or read_page for every page you work on, and use only block ids '
    'returned by the latest read_page.\n'
    '2. You never edit the file yourself. Tools only create proposals that the user reviews and applies, so do not '
    'ask for confirmation before proposing.\n'
    '3. Stay inside the scope given in the [Editor context] part of the user message.\n'
    '4. Prefer the macro tools: proofread for typos, translate for translations, redact with patterns for personal '
    'data, search to find text.\n'
    '5. When a tool returns an error, fix the call. After "stale_block" call read_page again.\n'
    '6. Answer briefly, in the language the user writes in, and do not repeat the document text.\n'
    '7. When the work is done, call finish with a one-sentence summary.\n'
    'Example: "fix the typos on this page" (scope page 0): read_page {"page": 0}, proofread {"pages": [0]}, '
    'finish {"summary": "Proposed 3 typo fixes on page 1."}.'
)

FINISH = ToolSpec(
    name='finish',
    description='End the turn when the work is done. Give a one-sentence summary for the user.',
    parameters={'type': 'object', 'properties': {'summary': {'type': 'string'}}, 'required': ['summary']},
    handler=lambda ctx, args: ToolResult(content={'ok': True}),
)


@dataclass
class AgentSession:
    id: str
    owner: str
    file_id: str
    messages: list = field(default_factory=list)
    stopped: bool = False
    busy: bool = False
    notes: list = field(default_factory=list)
    proposals: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    used_at: float = field(default_factory=time.time)


class AgentSessionStore:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()

    def prune(self):
        now = time.time()
        for key in [k for k, v in self.sessions.items() if now - v.used_at > SESSION_TTL and not v.busy]:
            del self.sessions[key]

    def create(self, owner, file_id):
        with self.lock:
            self.prune()
            mine = sorted((s for s in self.sessions.values() if s.owner == owner), key=lambda s: s.used_at)
            for old in mine[:max(0, len(mine) - MAX_SESSIONS + 1)]:
                old.stopped = True
                del self.sessions[old.id]
            session = AgentSession(id='ses_' + secrets.token_urlsafe(10), owner=owner, file_id=file_id)
            self.sessions[session.id] = session
            return session

    def get(self, owner, session_id):
        with self.lock:
            self.prune()
            session = self.sessions.get(session_id)
            if not session or session.owner != owner:
                return None
            session.used_at = time.time()
            return session

    def begin(self, session):
        with self.lock:
            if session.busy:
                return False
            session.busy = True
            session.stopped = False
            return True

    def end(self, session):
        with self.lock:
            session.busy = False
            session.used_at = time.time()


SESSIONS = AgentSessionStore()


def trim(text, limit=TOOL_RESULT_CHARS):
    if len(text) <= limit:
        return text
    tail = '... [truncated]'
    return text[:limit - len(tail)] + tail


def as_int(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def scope_pages(scope):
    if not isinstance(scope, dict) or scope.get('kind') == 'document':
        return None
    pages = {p for p in (as_int(v) for v in scope.get('pages') or []) if p is not None}
    return pages or None


def referenced_pages(args):
    if args.get('action') == 'insert_blank':
        return set()
    pages = set()
    if as_int(args.get('page')) is not None:
        pages.add(as_int(args['page']))
    if isinstance(args.get('pages'), list):
        pages.update(p for p in (as_int(v) for v in args['pages']) if p is not None)
    for key in ('block_id', 'like_block_id'):
        match = BLOCK_PAGE_RE.match(str(args.get(key) or ''))
        if match:
            pages.add(int(match.group(1)))
    return pages


def describe_scope(scope):
    scope = scope if isinstance(scope, dict) else {}
    kind = scope.get('kind') or 'document'
    pages = [p for p in (as_int(v) for v in scope.get('pages') or []) if p is not None]
    listed = ', '.join(map(str, pages))
    if kind == 'page' and pages:
        line = f'Scope: page {pages[0]} (the page the user is looking at). Work only on this page.'
    elif kind == 'pages' and pages:
        line = f'Scope: pages {listed}. Work only on these pages.'
    elif kind == 'selection':
        line = f'Scope: only the selected blocks{f" on page {listed}" if listed else ""}.'
    else:
        line = 'Scope: the whole document.'
    if scope.get('block_ids'):
        line += f' Blocks in scope: {", ".join(map(str, scope["block_ids"]))}.'
    return line


def user_message(text, scope, selection):
    lines = [text.strip(), '', '[Editor context]', describe_scope(scope)]
    if selection and (selection.get('block_ids') or selection.get('text')):
        ids = ', '.join(selection.get('block_ids') or []) or 'none'
        lines.append(f'Selection on page {selection.get("page")}: blocks {ids}.')
        if selection.get('text'):
            lines.append(f'Selected text: "{trim(selection["text"], SELECTION_CHARS)}"')
    lines.append('Page numbers are editor page ids; pass them to the tools unchanged.')
    return '\n'.join(lines)


def message_chars(message):
    size = len(message.get('content') or '')
    if message.get('tool_calls'):
        size += len(json.dumps(message['tool_calls'], ensure_ascii=False))
    return size


class AgentTurn:
    def __init__(self, session, ctx, provider, emit):
        self.session = session
        self.ctx = ctx
        self.provider = provider
        self.emit = emit
        self.task = TASKS.create(session.owner, 'agent', session.file_id)
        if ctx.working_ops is None:
            ctx.working_ops = list(ctx.ops or [])
        self.working_ops = ctx.working_ops
        self.proposals = []
        self.steps = 0
        self.calls = 0
        self.limited = False
        self.start = 0
        self.tools = tool_specs()
        if not any(spec.name == 'finish' for spec in self.tools):
            self.tools.append(FINISH)
        self.specs = {spec.name: spec for spec in self.tools}
        self.base_chars = len(SYSTEM_PROMPT) + sum(len(s.description) + len(json.dumps(s.parameters)) for s in self.tools)

    def stopped(self):
        return self.session.stopped or self.task.cancelled

    def tokens(self, messages):
        return (self.base_chars + sum(message_chars(m) for m in messages)) / CHARS_PER_TOKEN

    def fit_context(self, messages):
        if self.tokens(messages) <= CONTEXT_BUDGET:
            return True
        last = max((i for i, m in enumerate(messages) if m['role'] == 'assistant'), default=-1)
        for message in messages[:max(0, last)]:
            if message['role'] == 'tool' and not message.get('omitted'):
                summary = message.get('summary') or trim(message['content'], SUMMARY_CHARS)
                message['content'] = json.dumps({'omitted': True, 'summary': summary}, ensure_ascii=False)
                message['omitted'] = True
                if self.tokens(messages) <= CONTEXT_BUDGET:
                    return True
        while self.tokens(messages) > CONTEXT_BUDGET:
            boundary = next((i for i in range(1, self.start + 1) if messages[i]['role'] == 'user'), None)
            if boundary is None:
                break
            del messages[:boundary]
            self.start -= boundary
        return self.tokens(messages) <= CONTEXT_LIMIT

    def progress(self):
        TASKS.update(self.task.id, progress=min(1.0, self.steps / MAX_STEPS), detail={'done': self.steps, 'total': MAX_STEPS})

    def run(self, text, selection=None):
        self.emit('task', {'task_id': self.task.id})
        try:
            self.loop(text, selection)
        except Exception as e:
            self.fail('err_agent_failed', str(e) or type(e).__name__)

    def loop(self, text, selection):
        messages = self.session.messages
        notes, self.session.notes[:] = list(self.session.notes), []
        messages.extend({'role': 'system', 'content': note} for note in notes)
        self.start = len(messages)
        messages.append({'role': 'user', 'content': user_message(text, self.ctx.scope, selection)})
        status = self.provider.status()
        if status != 'ok':
            return self.fail(f'err_ai_{status}', 'The language model is not available')
        self.progress()
        final, partial = '', []
        while not self.stopped():
            if self.steps >= MAX_STEPS:
                return self.fail('err_agent_steps', f'The agent did not finish within {MAX_STEPS} steps')
            if not self.fit_context(messages):
                return self.fail('err_agent_context', 'The conversation is too long for the model context')
            self.steps += 1
            self.progress()
            partial = []

            def on_delta(piece):
                partial.append(piece)
                self.emit('delta', {'text': piece})

            try:
                step = self.provider.step([{'role': 'system', 'content': SYSTEM_PROMPT}] + messages, self.tools, on_delta, self.stopped)
            except StepStopped:
                break
            except ProviderError as e:
                return self.fail(e.code, str(e))
            partial = []
            messages.append({
                'role': 'assistant', 'content': step.text, 'raw': step.raw,
                'tool_calls': [{'id': c.id, 'name': c.name, 'args': c.args} for c in step.tool_calls],
            })
            if not step.tool_calls:
                final = step.text
                break
            summary = self.run_calls(step.tool_calls)
            if self.limited:
                return self.fail('err_agent_steps', f'The agent used more than {MAX_TOOL_CALLS} tool calls')
            if summary is not None:
                final = summary or step.text
                break
        stopped = self.stopped() and not final
        if stopped:
            final = ''.join(partial).strip()
            self.close(final or STOPPED_TEXT)
        if final:
            self.emit('message', {'role': 'assistant', 'text': final})
        self.emit('done', {'usage': {'steps': self.steps, 'tool_calls': self.calls}, 'stopped': stopped})
        TASKS.finish(self.task.id, 'cancelled' if stopped else 'done')

    def close(self, text):
        messages = self.session.messages
        last = messages[-1] if messages else None
        if last and last['role'] == 'assistant' and not last.get('tool_calls'):
            return
        if len(messages) == self.start + 1 and last and last['role'] == 'user' and not self.steps:
            del messages[self.start:]
            return
        messages.append({'role': 'assistant', 'content': text, 'tool_calls': []})

    def fail(self, code, message):
        self.close(f'(The turn ended with an error: {code}.)')
        self.emit('error', {'code': code, 'message': message})
        TASKS.finish(self.task.id, 'failed', {'code': code, 'message': message})

    def run_calls(self, calls):
        summary = None
        for call in calls:
            self.emit('tool', {'call_id': call.id, 'name': call.name, 'args': call.args, 'status': 'start', 'summary': ''})
            content, accepted = self.execute(call)
            error = isinstance(content, dict) and bool(content.get('error'))
            label = self.summary(content, accepted)
            self.session.messages.append({
                'role': 'tool', 'tool_call_id': call.id, 'name': call.name, 'error': error, 'summary': label,
                'content': trim(json.dumps(content, ensure_ascii=False, default=str)),
            })
            self.emit('tool', {'call_id': call.id, 'name': call.name, 'args': call.args, 'status': 'error' if error else 'done', 'summary': label})
            if call.name == 'finish' and not error:
                summary = str(call.args.get('summary') or '').strip()
        return summary

    def summary(self, content, accepted):
        if isinstance(content, dict):
            if content.get('error'):
                return str(content.get('message') or content['error'])[:SUMMARY_CHARS]
            if content.get('summary'):
                return str(content['summary'])[:SUMMARY_CHARS]
        if accepted:
            return f'{len(accepted)} proposal' + ('' if len(accepted) == 1 else 's')
        return ''

    def execute(self, call):
        if self.stopped():
            return {'error': 'stopped', 'message': 'The user stopped the agent.'}, []
        if self.calls >= MAX_TOOL_CALLS:
            self.limited = True
            return {'error': 'tool_call_limit', 'message': f'At most {MAX_TOOL_CALLS} tool calls per turn.'}, []
        self.calls += 1
        spec = self.specs.get(call.name)
        if not spec:
            return {'error': 'unknown_tool', 'message': 'Use one of: ' + ', '.join(sorted(self.specs))}, []
        if call.error:
            return {'error': 'invalid_args', 'message': call.error}, []
        args, errors = validate_args(spec.parameters, call.args)
        if errors:
            return {'error': 'invalid_args', 'message': '; '.join(errors)}, []
        allowed = scope_pages(self.ctx.scope)
        outside = sorted(referenced_pages(args) - allowed) if allowed else []
        if outside:
            return {'error': 'out_of_scope', 'message': f'Work only on the pages in scope: {", ".join(map(str, sorted(allowed)))}.', 'pages': outside, 'allowed_pages': sorted(allowed)}, []
        tool_ctx = dataclasses.replace(self.ctx, working_ops=list(self.working_ops), emit=self.tool_emitter(call))
        tool_ctx.should_stop = self.stopped
        try:
            result = spec.handler(tool_ctx, args)
        except Exception as e:
            return {'error': getattr(e, 'code', None) or 'tool_failed', 'message': str(e) or type(e).__name__}, []
        content = result.content if isinstance(result, ToolResult) else result
        accepted, dropped = self.accept(result.proposals if isinstance(result, ToolResult) else [])
        if accepted or dropped:
            content = dict(content) if isinstance(content, dict) else {'result': content}
            ids = [p['id'] for p in accepted]
            if isinstance(content.get('proposals'), list):
                content['proposals'] = [i for i in content['proposals'] if i in ids]
            else:
                content['proposals'] = ids
            if dropped:
                content['proposal_limit'] = f'{dropped} proposals were dropped; at most {MAX_PROPOSALS} per turn'
        return content, accepted

    def accept(self, proposals):
        room = max(0, MAX_PROPOSALS - len(self.proposals))
        accepted = []
        for proposal in list(proposals or [])[:room]:
            proposal = dict(proposal)
            earlier = [p['id'] for p in self.proposals if p.get('page') == proposal.get('page')]
            proposal['depends_on'] = earlier + [d for d in proposal.get('depends_on') or [] if d not in earlier]
            self.proposals.append(proposal)
            self.working_ops.extend(proposal.get('ops') or [])
            self.session.proposals[proposal['id']] = {'title': proposal.get('title', ''), 'page': proposal.get('page'), 'kind': proposal.get('kind')}
            self.emit('proposal', proposal)
            accepted.append(proposal)
        return accepted, max(0, len(proposals or []) - len(accepted))

    def tool_emitter(self, call):
        def emit(event, data):
            if event != 'tool_progress' or not isinstance(data, dict):
                return
            done, total = data.get('done'), data.get('total')
            summary = f'{done}/{total}' if total else ''
            self.emit('tool', {'call_id': call.id, 'name': call.name, 'args': call.args, 'status': 'progress', 'summary': summary, 'done': done, 'total': total})
        return emit


def run_turn(session, text, ctx, provider, emit, selection=None):
    turn = AgentTurn(session, ctx, provider, emit)
    turn.run(text, selection)
    return turn
