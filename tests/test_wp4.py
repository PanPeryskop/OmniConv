import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from app.services import agent_providers as ap
from app.services import pdf_agent
from app.services import pdf_agent_tools as tools
from app.services.editor_tasks import TASKS
from app.services.llm import LLMService
from tests.fixtures.build_fixtures import build

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE_LM_PORT = int(os.environ.get('FAKE_LM_PORT', 1304))
OWNER_A, OWNER_B = 'a' * 32, 'b' * 32
READ_SCHEMA = {'type': 'object', 'properties': {'page': {'type': 'integer'}, 'max_chars': {'type': 'integer'}}, 'required': ['page']}
PAGE_SCHEMA = {'type': 'object', 'properties': {'page': {'type': 'integer'}}, 'required': ['page']}
EMPTY_SCHEMA = {'type': 'object', 'properties': {}}


def reset_llm_cache():
    LLMService._models_cache.update({'at': 0.0, 'keys': None, 'checked': False})


def parse_sse(body):
    events = []
    for chunk in body.split('\n\n'):
        if not chunk.strip() or chunk.startswith(':'):
            continue
        fields = dict(line.split(': ', 1) for line in chunk.split('\n'))
        events.append((fields['event'], json.loads(fields['data'])))
    return events


def wait_port(port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError(f'port {port} did not open')


class DummyTools:
    def setUp(self):
        self.saved = dict(tools.TOOLS)
        tools.TOOLS.clear()
        self.seen = []
        tools.register(tools.ToolSpec('read_page', 'Read a page.', READ_SCHEMA, self.read_page))
        tools.register(tools.ToolSpec('fix', 'Propose a fix.', PAGE_SCHEMA, self.fix))
        tools.register(tools.ToolSpec('boom', 'Always fails.', EMPTY_SCHEMA, self.boom))
        tools.register(tools.ToolSpec('big', 'Large result.', EMPTY_SCHEMA, self.big))
        tools.register(tools.ToolSpec('many', 'Many proposals.', EMPTY_SCHEMA, self.many))
        tools.register(tools.ToolSpec('halt', 'Stops the session.', EMPTY_SCHEMA, self.halt))
        tools.register(tools.ToolSpec('slowfix', 'Reports progress.', PAGE_SCHEMA, self.slowfix))
        tools.register(tools.ToolSpec('partial', 'Fails after one proposal.', EMPTY_SCHEMA, self.partial))

    def tearDown(self):
        tools.TOOLS.clear()
        tools.TOOLS.update(self.saved)

    def read_page(self, ctx, args):
        self.seen.append(('read', args['page'], len(ctx.working_ops)))
        return tools.ToolResult({'blocks': [{'id': f'p{args["page"]}b0-abcdef', 'text': 'Tekst'}], 'summary': 'read'})

    def fix(self, ctx, args):
        page = args['page']
        self.seen.append(('fix', page, len(ctx.working_ops)))
        op = {'type': 'text', 'page': page, 'n': len(ctx.working_ops)}
        return tools.ToolResult({'ok': True}, [tools.make_proposal('text', page, 'Fix', [op], tools.page_base(ctx.ops, page))])

    def slowfix(self, ctx, args):
        for done in range(3):
            ctx.emit('tool_progress', {'name': 'slowfix', 'done': done, 'total': 2})
        ctx.emit('unknown_event', None)
        return self.fix(ctx, args)

    def partial(self, ctx, args):
        proposal = tools.make_proposal('text', 1, 'Half', [{'type': 'text', 'page': 1}], {})
        return tools.ToolResult({'error': 'err_ai_failed', 'message': 'LLM failed', 'proposals': [proposal['id']]}, [proposal])

    def boom(self, ctx, args):
        raise ValueError('kaput')

    def big(self, ctx, args):
        return tools.ToolResult({'data': 'x' * 20000, 'summary': 'big result'})

    def many(self, ctx, args):
        return tools.ToolResult({'ok': True}, [tools.make_proposal('annot', 0, f'N{i}', [{'type': 'annot', 'page': 0}], {}) for i in range(70)])

    def halt(self, ctx, args):
        self.session.stopped = True
        return tools.ToolResult({'ok': True})


class RecordingProvider(ap.FakeProvider):
    def __init__(self, steps, status='ok'):
        super().__init__(steps)
        self.state = status
        self.seen = []

    def status(self):
        return self.state

    def step(self, messages, tool_list, on_delta, should_stop=None):
        self.seen.append([dict(m) for m in messages])
        return super().step(messages, tool_list, on_delta, should_stop)


def call(name, **args):
    return {'name': name, 'args': args}


class RunTurnTest(DummyTools, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.session = pdf_agent.AgentSession(id='ses_test', owner='owner-test', file_id='file-test')
        self.events = []

    def turn(self, steps, scope=None, ops=None, provider=None, selection=None):
        provider = provider or RecordingProvider(steps)
        ops = ops or []
        ctx = tools.ToolContext(path='/nonexistent.pdf', file_id='file-test', ops=ops, working_ops=list(ops), scope=scope or {'kind': 'document'})
        turn = pdf_agent.run_turn(self.session, 'Popraw literówki', ctx, provider, lambda e, d: self.events.append((e, d)), selection=selection)
        return turn, provider

    def kinds(self):
        return [e for e, _ in self.events]

    def test_multi_step_turn_emits_events_in_order(self):
        steps = [
            {'text': 'Czytam. ', 'tool_calls': [call('read_page', page=0)]},
            {'tool_calls': [call('fix', page=0)]},
            {'tool_calls': [call('fix', page=0), call('fix', page=1)]},
            {'tool_calls': [call('finish', summary='Gotowe: 3 poprawki.')]},
        ]
        turn, provider = self.turn(steps, ops=[{'type': 'text', 'page': 0, 'g': 4}])
        kinds = self.kinds()
        self.assertEqual(kinds[0], 'task')
        self.assertEqual(kinds[1], 'delta')
        self.assertEqual(kinds[-2:], ['message', 'done'])
        self.assertEqual(self.events[-2][1], {'role': 'assistant', 'text': 'Gotowe: 3 poprawki.'})
        self.assertEqual(self.events[-1][1], {'usage': {'steps': 4, 'tool_calls': 5}, 'stopped': False})
        proposals = [d for e, d in self.events if e == 'proposal']
        self.assertEqual(len(proposals), 3)
        self.assertEqual(proposals[0]['depends_on'], [])
        self.assertEqual(proposals[1]['depends_on'], [proposals[0]['id']])
        self.assertEqual(proposals[2]['depends_on'], [])
        self.assertEqual(proposals[0]['base'], {'count': 1, 'last_g': 4})
        self.assertEqual([s[2] for s in self.seen], [1, 1, 2, 3])
        self.assertEqual(len(turn.working_ops), 4)
        tool_events = [d for e, d in self.events if e == 'tool']
        self.assertEqual([d['status'] for d in tool_events[:2]], ['start', 'done'])
        self.assertEqual(tool_events[1]['summary'], 'read')
        start = kinds.index('proposal')
        self.assertEqual(self.events[start - 1][1]['status'], 'start')
        self.assertEqual(self.events[start + 1][1]['status'], 'done')
        task = TASKS.get(turn.task.id)
        self.assertEqual((task.kind, task.status, task.owner, task.file_id), ('agent', 'done', 'owner-test', 'file-test'))
        self.assertEqual(task.detail, {'done': 4, 'total': pdf_agent.MAX_STEPS})
        self.assertEqual(self.events[0][1], {'task_id': task.id})
        roles = [m['role'] for m in self.session.messages]
        self.assertEqual(roles, ['user', 'assistant', 'tool', 'assistant', 'tool', 'assistant', 'tool', 'tool', 'assistant', 'tool'])
        self.assertEqual(provider.seen[0][0]['content'], pdf_agent.SYSTEM_PROMPT)
        self.assertIn('[Editor context]', self.session.messages[0]['content'])
        self.assertEqual(set(self.session.proposals), {p['id'] for p in proposals})

    def test_text_answer_ends_turn(self):
        self.turn([{'text': 'Dokument ma 5 stron.'}])
        self.assertEqual(self.kinds(), ['task', 'delta', 'message', 'done'])
        self.assertEqual(self.session.messages[-1]['content'], 'Dokument ma 5 stron.')

    def test_step_limit(self):
        self.turn([{'tool_calls': [call('read_page', page=0)]}])
        self.assertEqual(self.kinds()[-1], 'error')
        self.assertEqual(self.events[-1][1]['code'], 'err_agent_steps')
        self.assertNotIn('done', self.kinds())
        self.assertEqual(len([s for s in self.seen if s[0] == 'read']), pdf_agent.MAX_STEPS)
        self.assertEqual(self.session.messages[-1]['role'], 'assistant')

    def test_tool_call_limit(self):
        self.turn([{'tool_calls': [call('read_page', page=0)] * (pdf_agent.MAX_TOOL_CALLS + 1)}])
        self.assertEqual(self.events[-1][1]['code'], 'err_agent_steps')
        self.assertEqual(len(self.seen), pdf_agent.MAX_TOOL_CALLS)
        self.assertIn('tool_call_limit', self.session.messages[-2]['content'])

    def test_proposal_limit(self):
        self.turn([{'tool_calls': [call('many')]}, {'text': 'OK'}])
        proposals = [d for e, d in self.events if e == 'proposal']
        self.assertEqual(len(proposals), pdf_agent.MAX_PROPOSALS)
        self.assertEqual(proposals[-1]['depends_on'], [p['id'] for p in proposals[:-1]])
        result = json.loads(next(m for m in self.session.messages if m['role'] == 'tool')['content'])
        self.assertIn('proposal_limit', result)
        self.assertEqual(result['proposals'], [p['id'] for p in proposals])

    def test_tool_error_returns_to_model(self):
        turn, provider = self.turn([{'tool_calls': [call('boom'), call('read_page', page='x'), call('nope'), call('read_page', page='3')]}, {'text': 'Nie udało się.'}])
        statuses = [(d['name'], d['status']) for e, d in self.events if e == 'tool' and d['status'] != 'start']
        self.assertEqual(statuses, [('boom', 'error'), ('read_page', 'error'), ('nope', 'error'), ('read_page', 'done')])
        results = [m for m in provider.seen[1] if m['role'] == 'tool']
        self.assertEqual(json.loads(results[0]['content']), {'error': 'tool_failed', 'message': 'kaput'})
        self.assertTrue(results[0]['error'])
        self.assertEqual(json.loads(results[1]['content'])['error'], 'invalid_args')
        self.assertEqual(json.loads(results[2]['content'])['error'], 'unknown_tool')
        self.assertEqual(self.seen[-1], ('read', 3, 0))
        self.assertEqual(self.kinds()[-1], 'done')

    def test_scope_limits_pages(self):
        self.turn([{'tool_calls': [call('read_page', page=0), call('read_page', page=2)]}, {'text': 'OK'}], scope={'kind': 'pages', 'pages': [2]})
        results = [json.loads(m['content']) for m in self.session.messages if m['role'] == 'tool']
        self.assertEqual(results[0], {'error': 'out_of_scope', 'message': 'Work only on the pages in scope: 2.', 'pages': [0], 'allowed_pages': [2]})
        self.assertNotIn('error', results[1])
        self.assertIn('Scope: pages 2.', self.session.messages[0]['content'])

    def test_selection_is_described(self):
        self.turn([{'text': 'OK'}], scope={'kind': 'selection', 'pages': [1], 'block_ids': ['p1b2-abcdef']}, selection={'page': 1, 'block_ids': ['p1b2-abcdef'], 'text': 'Zaznaczony tekst'})
        content = self.session.messages[0]['content']
        self.assertIn('Blocks in scope: p1b2-abcdef', content)
        self.assertIn('Selected text: "Zaznaczony tekst"', content)

    def test_tool_results_are_trimmed(self):
        self.turn([{'tool_calls': [call('big')]}, {'text': 'OK'}])
        result = next(m for m in self.session.messages if m['role'] == 'tool')
        self.assertEqual(len(result['content']), pdf_agent.TOOL_RESULT_CHARS)
        self.assertTrue(result['content'].endswith('[truncated]'))

    def test_old_tool_results_are_omitted_when_context_grows(self):
        steps = [{'tool_calls': [call('big')]}] * 3 + [{'text': 'OK'}]
        with mock.patch.object(pdf_agent, 'CONTEXT_BUDGET', 3000), mock.patch.object(pdf_agent, 'CONTEXT_LIMIT', 100000):
            turn, provider = self.turn(steps)
        last = [m for m in provider.seen[-1] if m['role'] == 'tool']
        self.assertEqual(json.loads(last[0]['content']), {'omitted': True, 'summary': 'big result'})
        self.assertEqual(json.loads(last[1]['content']), {'omitted': True, 'summary': 'big result'})
        self.assertFalse(last[2].get('omitted'))
        self.assertLessEqual(turn.tokens(provider.seen[-1][1:]), 3000)
        self.assertEqual(self.kinds()[-1], 'done')

    def test_context_error_when_turn_does_not_fit(self):
        with mock.patch.object(pdf_agent, 'CONTEXT_BUDGET', 10), mock.patch.object(pdf_agent, 'CONTEXT_LIMIT', 20):
            self.turn([{'text': 'OK'}])
        self.assertEqual(self.events[-1], ('error', {'code': 'err_agent_context', 'message': 'The conversation is too long for the model context'}))

    def test_older_turns_are_dropped_before_failing(self):
        self.session.messages.extend([{'role': 'user', 'content': 'u' * 20000}, {'role': 'assistant', 'content': 'a', 'tool_calls': []}])
        with mock.patch.object(pdf_agent, 'CONTEXT_BUDGET', 2000):
            self.turn([{'text': 'OK'}])
        self.assertEqual(self.kinds()[-1], 'done')
        self.assertEqual(self.session.messages[0]['content'][:16], 'Popraw literówki')

    def test_stop_between_steps(self):
        self.turn([{'tool_calls': [call('halt')]}, {'text': 'never'}])
        self.assertEqual(self.events[-1][1], {'usage': {'steps': 1, 'tool_calls': 1}, 'stopped': True})
        self.assertEqual(self.session.messages[-1], {'role': 'assistant', 'content': pdf_agent.STOPPED_TEXT, 'tool_calls': []})

    def test_stop_during_streaming(self):
        provider = RecordingProvider([{'text': 'raz dwa trzy cztery pięć sześć siedem osiem', 'delay': 0.05}])
        timer = threading.Timer(0.12, lambda: setattr(self.session, 'stopped', True))
        timer.start()
        turn, _ = self.turn(None, provider=provider)
        timer.join()
        deltas = [d['text'] for e, d in self.events if e == 'delta']
        self.assertTrue(0 < len(deltas) < 8)
        self.assertEqual(self.events[-1][1]['stopped'], True)
        self.assertEqual(self.events[-2], ('message', {'role': 'assistant', 'text': ''.join(deltas).strip()}))
        self.assertEqual(TASKS.get(turn.task.id).status, 'cancelled')

    def test_task_cancel_stops_turn(self):
        provider = RecordingProvider([{'tool_calls': [call('read_page', page=0)]}])
        original = provider.step

        def step(*args):
            TASKS.cancel('owner-test', self.events[0][1]['task_id'])
            return original(*args)

        provider.step = step
        self.turn(None, provider=provider)
        self.assertEqual(self.events[-1][1], {'usage': {'steps': 1, 'tool_calls': 0}, 'stopped': True})
        self.assertEqual(self.session.messages[-1]['content'], pdf_agent.STOPPED_TEXT)

    def test_offline_provider_reports_error_and_rolls_back(self):
        self.turn([{'text': 'OK'}], provider=RecordingProvider([], status='llm_offline'))
        self.assertEqual(self.kinds(), ['task', 'error'])
        self.assertEqual(self.events[-1][1]['code'], 'err_ai_llm_offline')
        self.assertEqual(self.session.messages, [])

    def test_provider_error_is_mapped(self):
        self.turn([{'tool_calls': [call('read_page', page=0)]}, {'error': 'err_ai_llm_model_missing'}])
        self.assertEqual(self.events[-1][1]['code'], 'err_ai_llm_model_missing')
        self.assertEqual(self.session.messages[-1]['role'], 'assistant')

    def test_feedback_notes_enter_history(self):
        self.session.notes.append('Note from the editor: the user accepted proposal prp_1.')
        turn, provider = self.turn([{'text': 'OK'}])
        self.assertEqual(self.session.messages[0]['role'], 'system')
        self.assertEqual(self.session.notes, [])
        system, history = ap.fold_messages(provider.seen[0])
        self.assertEqual(system, pdf_agent.SYSTEM_PROMPT)
        self.assertEqual(history[0]['role'], 'user')
        self.assertTrue(history[0]['content'].startswith('Note from the editor'))

    def test_registered_finish_is_used(self):
        tools.register(tools.ToolSpec('finish', 'x', pdf_agent.FINISH.parameters, lambda ctx, args: tools.ToolResult({'done': True, 'summary': args['summary']})))
        turn, provider = self.turn([{'tool_calls': [call('finish', summary='Koniec')]}])
        self.assertEqual(self.events[-2][1]['text'], 'Koniec')
        self.assertEqual([t.description for t in turn.tools if t.name == 'finish'], ['x'])
        self.assertEqual(json.loads(self.session.messages[-1]['content']), {'done': True, 'summary': 'Koniec'})

    def test_progress_and_partial_results(self):
        ops = [{'type': 'text', 'page': 0}]
        turn, _ = self.turn([{'tool_calls': [call('slowfix', page=0), call('partial')]}, {'text': 'OK'}], ops=ops)
        progress = [d for e, d in self.events if e == 'tool' and d['status'] == 'progress']
        self.assertEqual([(d['done'], d['total'], d['summary']) for d in progress], [(0, 2, '0/2'), (1, 2, '1/2'), (2, 2, '2/2')])
        proposals = [d for e, d in self.events if e == 'proposal']
        self.assertEqual([p['title'] for p in proposals], ['Fix', 'Half'])
        partial = [d for e, d in self.events if e == 'tool' and d['name'] == 'partial' and d['status'] != 'start']
        self.assertEqual((partial[0]['status'], partial[0]['summary']), ('error', 'LLM failed'))
        self.assertIs(turn.working_ops, turn.ctx.working_ops)
        self.assertEqual(len(turn.ctx.working_ops), 3)
        self.assertEqual(ops, [{'type': 'text', 'page': 0}])


class SessionStoreTest(unittest.TestCase):
    def test_limit_and_ttl(self):
        store = pdf_agent.AgentSessionStore()
        first = store.create('me', 'f')
        others = [store.create('me', 'f') for _ in range(pdf_agent.MAX_SESSIONS)]
        self.assertIsNone(store.get('me', first.id))
        self.assertTrue(first.stopped)
        self.assertEqual(len([s for s in store.sessions.values() if s.owner == 'me']), pdf_agent.MAX_SESSIONS)
        self.assertIsNone(store.get('you', others[0].id))
        store.create('you', 'f')
        self.assertIsNotNone(store.get('me', others[0].id))
        others[1].used_at -= pdf_agent.SESSION_TTL + 1
        self.assertIsNone(store.get('me', others[1].id))

    def test_begin_is_exclusive(self):
        store = pdf_agent.AgentSessionStore()
        session = store.create('me', 'f')
        session.stopped = True
        self.assertTrue(store.begin(session))
        self.assertFalse(session.stopped)
        self.assertFalse(store.begin(session))
        session.used_at -= pdf_agent.SESSION_TTL + 1
        store.prune()
        self.assertIn(session.id, store.sessions)
        store.end(session)
        self.assertTrue(store.begin(session))


class SchemaTest(unittest.TestCase):
    def test_validate_and_coerce(self):
        schema = {'type': 'object', 'properties': {
            'page': {'type': 'integer', 'minimum': 0}, 'pages': {'type': 'array', 'items': {'type': 'integer'}},
            'mode': {'type': 'string', 'enum': ['a', 'b']}, 'bold': {'type': 'boolean'}, 'language': {'type': 'string'},
        }, 'required': ['page'], 'additionalProperties': False}
        args, errors = ap.validate_args(schema, {'page': '2', 'pages': 3, 'bold': 'true', 'language': None})
        self.assertEqual((args, errors), ({'page': 2, 'pages': [3], 'bold': True}, []))
        _, errors = ap.validate_args(schema, {'page': -1, 'mode': 'c', 'extra': 1})
        self.assertEqual(sorted(errors), ['args.extra: unexpected', 'args.mode: must be one of a, b', 'args.page: must be >= 0'])
        _, errors = ap.validate_args(schema, {'pages': ['x']})
        self.assertEqual(sorted(errors), ['args.page: required', 'args.pages[0]: expected integer'])


class StubResponse:
    def __init__(self, lines, status=200, text=''):
        self.lines = lines
        self.status_code = status
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self, chunk_size=None):
        for line in self.lines:
            yield line.encode() if isinstance(line, str) else line


def chunk(delta, finish=None):
    return 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]})


def spec(name, schema=READ_SCHEMA):
    return tools.ToolSpec(name, f'{name} tool', schema, lambda ctx, args: None)


class FakeLmTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.rules = os.path.join(cls.tmp, 'rules.json')
        cls.write_rules([])
        cls.env = mock.patch.dict(os.environ, {'LMSTUDIO_API_URL': f'http://127.0.0.1:{FAKE_LM_PORT}/api/v1/chat', 'FAKE_LM_RULES': cls.rules})
        cls.env.start()
        os.environ.pop('LLM_AGENT_MODEL', None)
        cls.server = subprocess.Popen([sys.executable, '-c', f'from tests.fakes.fake_lm import main; main({FAKE_LM_PORT})'], cwd=ROOT, env=dict(os.environ))
        wait_port(FAKE_LM_PORT)

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(5)
        cls.env.stop()
        reset_llm_cache()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def write_rules(cls, rules):
        with open(cls.rules, 'w', encoding='utf-8') as handle:
            json.dump(rules, handle, ensure_ascii=False)

    def setUp(self):
        reset_llm_cache()
        ap.LmStudioProvider.json_models.clear()

    def test_status(self):
        provider = ap.LmStudioProvider()
        self.assertEqual(provider.status(), 'ok')
        self.assertEqual(provider.model(), LLMService.text_model())
        with mock.patch.dict(os.environ, {'LLM_AGENT_MODEL': 'missing-model'}):
            self.assertEqual(provider.model(), 'missing-model')
            self.assertEqual(provider.status(), 'llm_model_missing')
        with mock.patch.dict(os.environ, {'LMSTUDIO_API_URL': 'http://127.0.0.1:1/api/v1/chat'}):
            reset_llm_cache()
            self.assertEqual(provider.status(), 'llm_offline')
            with self.assertRaises(ap.ProviderError) as caught:
                provider.step([{'role': 'user', 'content': 'x'}], [], lambda piece: None)
            self.assertEqual(caught.exception.code, 'err_ai_llm_offline')

    def test_streamed_tool_calls_are_assembled(self):
        long_text = 'Zażółć gęślą jaźń ' * 5
        self.write_rules([{'match': 'popraw', 'steps': [
            {'text': 'Czytam stronę teraz.', 'tool_calls': [call('read_page', page=0, max_chars=3000), call('note', text=long_text)]},
            {'text': 'Gotowe.'},
        ]}])
        provider = ap.LmStudioProvider()
        deltas = []
        messages = [{'role': 'system', 'content': 'sys'}, {'role': 'user', 'content': 'Popraw literówki'}]
        step = provider.step(messages, [spec('read_page'), spec('note', {'type': 'object'})], deltas.append)
        self.assertEqual(''.join(deltas), 'Czytam stronę teraz.')
        self.assertGreater(len(deltas), 1)
        self.assertEqual(step.text, 'Czytam stronę teraz.')
        self.assertEqual(step.finish_reason, 'tool_calls')
        self.assertEqual([(c.name, c.args, c.error) for c in step.tool_calls], [('read_page', {'page': 0, 'max_chars': 3000}, ''), ('note', {'text': long_text}, '')])
        self.assertTrue(all(c.id.startswith('call_') for c in step.tool_calls))
        history = messages + [
            {'role': 'assistant', 'content': step.text, 'tool_calls': [{'id': c.id, 'name': c.name, 'args': c.args} for c in step.tool_calls]},
            {'role': 'tool', 'tool_call_id': step.tool_calls[0].id, 'name': 'read_page', 'content': '{"blocks": []}'},
            {'role': 'tool', 'tool_call_id': step.tool_calls[1].id, 'name': 'note', 'content': '{"ok": true}'},
        ]
        second = provider.step(history, [spec('read_page')], deltas.append)
        self.assertEqual((second.text, second.tool_calls, second.finish_reason), ('Gotowe.', [], 'stop'))

    def test_json_in_content_fallback(self):
        self.write_rules([
            {'match': 'fenced', 'steps': [{'text': 'Sprawdzam.\n```json\n{"tool": "read_page", "args": {"page": "2"}}\n```'}]},
            {'match': 'invalid', 'steps': [{'text': '{"tool": "read_page", "args": {"page": "x"}}'}]},
            {'match': 'plain', 'steps': [{'text': '{"a": 1} to nie narzędzie'}]},
        ])
        provider = ap.LmStudioProvider()
        deltas = []
        step = provider.step([{'role': 'user', 'content': 'fenced'}], [spec('read_page')], deltas.append)
        self.assertEqual([(c.name, c.args, c.error) for c in step.tool_calls], [('read_page', {'page': 2}, '')])
        self.assertEqual(step.text, 'Sprawdzam.')
        deltas.clear()
        step = provider.step([{'role': 'user', 'content': 'invalid'}], [spec('read_page')], deltas.append)
        self.assertEqual(step.tool_calls[0].name, 'read_page')
        self.assertIn('expected integer', step.tool_calls[0].error)
        self.assertEqual(deltas, [])
        step = provider.step([{'role': 'user', 'content': 'plain'}], [spec('read_page')], deltas.append)
        self.assertEqual(step.tool_calls, [])
        self.assertEqual(''.join(deltas), '{"a": 1} to nie narzędzie')

    def test_json_mode_after_tools_are_rejected(self):
        payloads = []
        responses = [StubResponse([], 400, 'This model does not support tools'), StubResponse([chunk({'content': '{"tool": "read_page", "args": {"page": 1}}'}), 'data: [DONE]'])]

        def post(url, json=None, **kwargs):
            payloads.append(json)
            return responses.pop(0)

        history = [
            {'role': 'user', 'content': 'czytaj'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'name': 'read_page', 'args': {'page': 0}}]},
            {'role': 'tool', 'tool_call_id': 'c1', 'name': 'read_page', 'content': '{"blocks": []}'},
        ]
        with mock.patch.object(ap.requests, 'post', side_effect=post):
            step = ap.LmStudioProvider().step([{'role': 'system', 'content': 'sys'}] + history, [spec('read_page')], lambda piece: None)
        self.assertIn('tools', payloads[0])
        self.assertNotIn('tools', payloads[1])
        wire = payloads[1]['messages']
        self.assertIn('"tool": "<name>"', wire[0]['content'])
        self.assertEqual(wire[2], {'role': 'assistant', 'content': '{"tool": "read_page", "args": {"page": 0}}'})
        self.assertEqual(wire[3], {'role': 'user', 'content': 'Result of read_page: {"blocks": []}'})
        self.assertEqual(step.tool_calls[0].args, {'page': 1})
        self.assertIn(LLMService().resolve_model(LLMService.text_model()), ap.LmStudioProvider.json_models)

    def test_parser_handles_split_names_and_truncation(self):
        lines = [
            chunk({'role': 'assistant'}),
            chunk({'tool_calls': [{'index': 0, 'id': 'a', 'function': {'name': 'read_', 'arguments': ''}}]}),
            chunk({'tool_calls': [{'index': 0, 'function': {'name': 'page', 'arguments': '{"pa'}}]}),
            chunk({'tool_calls': [{'index': 1, 'id': 'b', 'function': {'name': 'fix', 'arguments': '{"page": 1'}}]}),
            chunk({'tool_calls': [{'index': 0, 'function': {'arguments': 'ge": 4}'}}]}),
            chunk({}, 'length'),
            'data: [DONE]',
        ]
        step = ap.LmStudioProvider().read(StubResponse(lines), [], lambda piece: None, None)
        self.assertEqual([(c.id, c.name, c.args) for c in step.tool_calls], [('a', 'read_page', {'page': 4}), ('b', 'fix', {})])
        self.assertEqual(step.tool_calls[1].error, 'tool arguments were cut off')
        stop = ap.LmStudioProvider().read
        with self.assertRaises(ap.StepStopped):
            stop(StubResponse(lines), [], lambda piece: None, lambda: True)

    def test_agent_route_with_lmstudio(self):
        self.write_rules([{'match': 'popraw', 'steps': [
            {'text': 'Czytam.', 'tool_calls': [call('read_page', page=0)]},
            {'tool_calls': [call('fix', page=0)]},
            {'text': 'Zrobione.', 'tool_calls': [call('finish', summary='Jedna poprawka.')]},
        ]}])
        routes = RouteTest('test_status')
        RouteTest.setUpClass()
        try:
            routes.setUp()
            try:
                with mock.patch.dict(os.environ, {'AGENT_PROVIDER': 'lmstudio'}):
                    status = routes.client_a.get('/api/pdf/edit/agent/status').get_json()['data']
                    self.assertEqual(status, {'status': 'ok', 'provider': 'lmstudio', 'model': LLMService.text_model()})
                    events = routes.send(routes.session_id(), {'text': 'Popraw literówki', 'scope': {'kind': 'page', 'pages': [0]}})
            finally:
                routes.tearDown()
        finally:
            RouteTest.tearDownClass()
        kinds = [e for e, _ in events]
        self.assertEqual(kinds[0], 'task')
        self.assertEqual(kinds[-2:], ['message', 'done'])
        self.assertEqual(kinds.count('proposal'), 1)
        self.assertEqual(events[-2][1]['text'], 'Jedna poprawka.')


class AnthropicHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    script = []
    bodies = []

    def do_GET(self):
        self.reply(200 if self.path.endswith('/claude-sonnet-5-5') else 404, b'{}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
        self.bodies.append((dict(self.headers), body))
        kind, payload = self.script.pop(0)
        if kind == 'error':
            return self.reply(400, json.dumps({'type': 'error', 'error': {'message': payload}}).encode())
        data = ''.join(f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n' for e in payload).encode()
        self.reply(200, data, 'text/event-stream')

    def reply(self, status, data, kind='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def anthropic_stream():
    return [
        {'type': 'message_start', 'message': {'id': 'msg_1', 'content': []}},
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': 'sig'}},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': ''}},
        {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': 'Czytam '}},
        {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': 'stronę.'}},
        {'type': 'content_block_stop', 'index': 1},
        {'type': 'content_block_start', 'index': 2, 'content_block': {'type': 'tool_use', 'id': 'toolu_1', 'name': 'read_page', 'input': {}}},
        {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': '{"pa'}},
        {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': 'ge": 3}'}},
        {'type': 'content_block_stop', 'index': 2},
        {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}},
        {'type': 'message_stop'},
    ]


class AnthropicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), AnthropicHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.env = mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key', 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{cls.server.server_port}', 'AGENT_PROVIDER': 'anthropic'})
        cls.env.start()
        os.environ.pop('AGENT_ANTHROPIC_MODEL', None)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.env.stop()

    def setUp(self):
        AnthropicHandler.bodies.clear()
        ap.AnthropicProvider.statuses.clear()

    def test_status_and_model(self):
        provider = ap.provider_from_env()
        self.assertIsInstance(provider, ap.AnthropicProvider)
        self.assertEqual((provider.model(), provider.status()), ('claude-sonnet-5-5', 'ok'))
        with mock.patch.dict(os.environ, {'AGENT_ANTHROPIC_MODEL': 'claude-unknown'}):
            self.assertEqual(provider.status(), 'llm_model_missing')
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            self.assertEqual(ap.AnthropicProvider().status(), 'llm_offline')

    def test_step_maps_tool_use_and_tool_result(self):
        AnthropicHandler.script[:] = [('stream', anthropic_stream()), ('error', 'messages.1.content.0: Invalid `signature` in `thinking` block.'), ('stream', anthropic_stream())]
        provider = ap.AnthropicProvider()
        deltas = []
        messages = [{'role': 'system', 'content': 'sys'}, {'role': 'user', 'content': 'Czytaj'}]
        step = provider.step(messages, [spec('read_page')], deltas.append)
        self.assertEqual(deltas, ['Czytam ', 'stronę.'])
        self.assertEqual((step.text, step.finish_reason), ('Czytam stronę.', 'tool_use'))
        self.assertEqual([(c.id, c.name, c.args) for c in step.tool_calls], [('toolu_1', 'read_page', {'page': 3})])
        self.assertEqual(step.raw['anthropic'][0], {'type': 'thinking', 'thinking': '', 'signature': 'sig'})
        headers, body = AnthropicHandler.bodies[0]
        self.assertEqual(headers['x-api-key'], 'test-key')
        self.assertEqual(headers['anthropic-version'], ap.ANTHROPIC_VERSION)
        self.assertEqual(body['system'], 'sys')
        self.assertEqual(body['tools'][0], {'name': 'read_page', 'description': 'read_page tool', 'input_schema': READ_SCHEMA})
        self.assertEqual(body['messages'], [{'role': 'user', 'content': [{'type': 'text', 'text': 'Czytaj'}]}])
        history = messages + [
            {'role': 'assistant', 'content': step.text, 'raw': step.raw, 'tool_calls': [{'id': 'toolu_1', 'name': 'read_page', 'args': {'page': 3}}]},
            {'role': 'tool', 'tool_call_id': 'toolu_1', 'name': 'read_page', 'content': '{"error": "stale_block"}', 'error': True},
            {'role': 'system', 'content': 'Note: accepted'},
            {'role': 'user', 'content': 'Dalej'},
        ]
        provider.step(history, [spec('read_page')], deltas.append)
        first, retry = AnthropicHandler.bodies[1][1]['messages'], AnthropicHandler.bodies[2][1]['messages']
        self.assertEqual(first[1]['content'][0]['type'], 'thinking')
        self.assertEqual([b['type'] for b in retry[1]['content']], ['text', 'tool_use'])
        self.assertEqual(retry[2], {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': '{"error": "stale_block"}', 'is_error': True},
            {'type': 'text', 'text': 'Note: accepted\nDalej'},
        ]})


class RouteTest(DummyTools, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings('ignore')
        from app import create_app
        from app.routes.api_common import conversion_jobs
        cls.tmp = tempfile.mkdtemp()
        cls.path = build(os.path.join(cls.tmp, 'doc.pdf'))
        cls.app = create_app()
        cls.jobs = conversion_jobs
        cls.file_id = 'wp4file' + os.urandom(4).hex()
        conversion_jobs[cls.file_id] = {'status': 'uploaded', 'input_path': cls.path, 'original_filename': 'doc.pdf', 'owner': OWNER_A}

    @classmethod
    def tearDownClass(cls):
        cls.jobs.pop(cls.file_id, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.client_a = self.app.test_client()
        self.client_a.set_cookie('oc_client', OWNER_A)
        self.client_b = self.app.test_client()
        self.client_b.set_cookie('oc_client', OWNER_B)

    def session_id(self, client=None):
        response = (client or self.client_a).post('/api/pdf/edit/agent/sessions', json={'file_id': self.file_id})
        return response.get_json()['data']['session_id'] if response.status_code == 200 else response

    def send(self, sid, body, client=None):
        response = (client or self.client_a).post(f'/api/pdf/edit/agent/sessions/{sid}/messages', json=body)
        self.assertEqual(response.mimetype, 'text/event-stream')
        return parse_sse(response.get_data(as_text=True))

    def fake(self, steps):
        return mock.patch.dict(os.environ, {'AGENT_PROVIDER': 'fake', 'AGENT_FAKE_STEPS': json.dumps(steps)})

    def test_status(self):
        with self.fake([]):
            data = self.client_a.get('/api/pdf/edit/agent/status').get_json()['data']
        self.assertEqual(data, {'status': 'ok', 'provider': 'fake', 'model': 'fake'})

    def test_sse_event_order(self):
        sid = self.session_id()
        steps = [{'text': 'Czytam.', 'tool_calls': [call('read_page', page=0)]}, {'tool_calls': [call('fix', page=0)]}, {'tool_calls': [call('finish', summary='Gotowe.')]}]
        with self.fake(steps):
            events = self.send(sid, {'text': 'Popraw', 'ops': [{'type': 'text', 'page': 0, 'g': 2}], 'scope': {'kind': 'page', 'pages': [0]}})
        kinds = [e for e, _ in events]
        self.assertEqual(kinds, ['task', 'delta', 'tool', 'tool', 'tool', 'proposal', 'tool', 'tool', 'tool', 'message', 'done'])
        self.assertEqual(events[5][1]['base'], {'count': 1, 'last_g': 2})
        self.assertEqual(events[-1][1], {'usage': {'steps': 3, 'tool_calls': 3}, 'stopped': False})
        task = TASKS.get(events[0][1]['task_id'])
        self.assertEqual((task.owner, task.kind, task.file_id), (OWNER_A, 'agent', self.file_id))
        self.assertEqual(self.seen[1], ('fix', 0, 1))

    def test_owner_isolation(self):
        sid = self.session_id()
        self.assertEqual(self.session_id(self.client_b).status_code, 404)
        for path in ('messages', 'stop', 'feedback'):
            response = self.client_b.post(f'/api/pdf/edit/agent/sessions/{sid}/{path}', json={'text': 'x', 'proposal_id': 'p', 'decision': 'accepted'})
            self.assertEqual(response.status_code, 404, path)
        self.assertEqual(self.client_a.post(f'/api/pdf/edit/agent/sessions/{sid}/stop').get_json()['data'], {'stopped': False})

    def test_request_validation(self):
        sid = self.session_id()
        self.assertEqual(self.client_a.post(f'/api/pdf/edit/agent/sessions/{sid}/messages', json={'text': ' '}).status_code, 400)
        self.assertEqual(self.client_a.post(f'/api/pdf/edit/agent/sessions/{sid}/messages', json={'text': 'x', 'ops': 'bad'}).status_code, 400)
        self.assertEqual(self.client_a.post('/api/pdf/edit/agent/sessions', json={'file_id': 'missing'}).status_code, 404)

    def test_selection_indexes_become_block_ids(self):
        from app.services import pdf_editor
        sid = self.session_id()
        blocks = pdf_editor.render_preview(self.path, 0, [], 100)['blocks']
        expected = tools.block_id(0, 1, blocks[1])
        with self.fake([{'text': 'OK'}]):
            self.send(sid, {'text': 'Skróć', 'scope': {'kind': 'selection'}, 'selection': {'page': 0, 'block_indexes': [1, 999], 'text': 'abc'}})
        content = pdf_agent.SESSIONS.sessions[sid].messages[0]['content']
        self.assertIn(f'Blocks in scope: {expected}.', content)
        self.assertIn(f'Selection on page 0: blocks {expected}.', content)

    def test_feedback_goes_to_history(self):
        sid = self.session_id()
        with self.fake([{'tool_calls': [call('fix', page=0)]}, {'text': 'OK'}]):
            events = self.send(sid, {'text': 'Popraw'})
        proposal = next(d for e, d in events if e == 'proposal')
        url = f'/api/pdf/edit/agent/sessions/{sid}/feedback'
        self.assertEqual(self.client_a.post(url, json={'proposal_id': 'prp_x', 'decision': 'accepted'}).status_code, 400)
        self.assertEqual(self.client_a.post(url, json={'proposal_id': proposal['id'], 'decision': 'maybe'}).status_code, 400)
        self.assertEqual(self.client_a.post(url, json={'proposal_id': proposal['id'], 'decision': 'rejected'}).get_json()['data'], {})
        with self.fake([{'text': 'OK'}]):
            self.send(sid, {'text': 'Dalej'})
        notes = [m for m in pdf_agent.SESSIONS.sessions[sid].messages if m['role'] == 'system']
        self.assertEqual(notes[0]['content'], f'Note from the editor: the user rejected proposal {proposal["id"]} "Fix" on page 0.')

    def test_stop_busy_and_heartbeat(self):
        sid = self.session_id()
        url = f'/api/pdf/edit/agent/sessions/{sid}/messages'
        with self.fake([{'text': 'jeden dwa trzy cztery pięć sześć siedem osiem dziewięć dziesięć', 'delay': 0.1}]), mock.patch('app.routes.api_pdf_agent.HEARTBEAT', 0.05):
            response = self.client_a.post(url, json={'text': 'Pisz'}, buffered=False)
            iterator = iter(response.response)
            parts = []
            while sum(part.count(b'event: delta') for part in parts) < 2:
                part = next(iterator)
                parts.append(part if isinstance(part, bytes) else part.encode())
            self.assertTrue(parts[0].startswith(b'event: task'))
            busy = self.client_a.post(url, json={'text': 'Znowu'})
            self.assertEqual(busy.status_code, 409)
            self.assertEqual(self.client_a.post(f'/api/pdf/edit/agent/sessions/{sid}/stop').get_json()['data'], {'stopped': True})
            parts += [part if isinstance(part, bytes) else part.encode() for part in iterator]
            response.close()
            rest = b''.join(parts).decode()
        self.assertIn(': ping', rest)
        events = parse_sse(rest)
        self.assertEqual(events[-1][0], 'done')
        self.assertTrue(events[-1][1]['stopped'])
        deadline = time.time() + 2
        while pdf_agent.SESSIONS.sessions[sid].busy and time.time() < deadline:
            time.sleep(0.01)
        self.assertFalse(pdf_agent.SESSIONS.sessions[sid].busy)

    def test_offline_error_event(self):
        sid = self.session_id()
        with mock.patch.dict(os.environ, {'AGENT_PROVIDER': 'lmstudio', 'LMSTUDIO_API_URL': 'http://127.0.0.1:1/api/v1/chat'}):
            reset_llm_cache()
            events = self.send(sid, {'text': 'Popraw'})
        reset_llm_cache()
        self.assertEqual([e for e, _ in events], ['task', 'error'])
        self.assertEqual(events[-1][1]['code'], 'err_ai_llm_offline')


if __name__ == '__main__':
    unittest.main()
