import os
import shutil
import tempfile
import unittest
import warnings
from unittest import mock

import fitz

from app.services import font_match as fm
from app.services import pdf_ai, pdf_translate
from app.services import pdf_editor as pe
from app.services.editor_tasks import TASKS
from app.services.pdf_tools import PdfToolError, PdfTools
from tests.fixtures.build_fixtures import build
from tests.test_pdf_editor import FORM_PAGE, TEXT_PAGE, self_signed_p12

WHITEOUT = {'type': 'whiteout', 'page': TEXT_PAGE, 'rect': [60, 420, 300, 450]}


class ProgressCallbacksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = build(os.path.join(cls.tmp, 'pe_test.pdf'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_search_document_reports_every_page_in_order(self):
        calls = []
        matches, truncated = pe.search_document(self.path, [], 'a', [], progress=lambda done, total: calls.append((done, total)))
        self.assertTrue(matches)
        self.assertFalse(truncated)
        self.assertEqual(calls, [(n, 5) for n in range(6)])

    def test_search_document_follows_page_order_and_inserted_pages(self):
        ops = [{'type': 'page', 'action': 'delete', 'page': 1}, {'type': 'page', 'action': 'insert', 'page': 5, 'to': 0}]
        calls = []
        pe.search_document(self.path, ops, 'a', [], progress=lambda done, total: calls.append((done, total)))
        self.assertEqual(calls, [(n, 5) for n in range(6)])

    def test_search_document_without_callback_is_unchanged(self):
        self.assertEqual(pe.search_document(self.path, [], 'a', []), pe.search_document(self.path, [], 'a', [], progress=lambda *_: None))

    def test_apply_ops_reports_each_edited_page(self):
        calls = []
        ops = [WHITEOUT, dict(WHITEOUT, page=3), dict(WHITEOUT, page=3, rect=[60, 500, 300, 520])]
        with fitz.open(self.path) as doc:
            pe.apply_ops(doc, ops, lambda done, total: calls.append((done, total)))
        self.assertEqual(calls, [(1, 2), (2, 2)])

    def run_edit(self, ops, **options):
        seen = []
        folder = tempfile.mkdtemp(dir=self.tmp)
        out = PdfTools(seen.append).run('edit', [self.path], os.path.join(folder, 'out'), {'ops': ops, **options})
        return seen, out

    def test_tool_edit_progress_sequence(self):
        seen, out = self.run_edit([WHITEOUT, dict(WHITEOUT, page=3)])
        self.assertEqual(seen, [5, 20, 45, 70, 70, 85, 95, 100])
        self.assertTrue(os.path.exists(out))

    def test_tool_edit_progress_sequence_with_signature(self):
        ops = [WHITEOUT, {'type': 'digital_sign', 'page': FORM_PAGE, 'rect': [300, 700, 520, 760]}]
        seen, out = self.run_edit(ops, certificate=(self_signed_p12(), 'tajne'))
        self.assertEqual(seen, [5, 20, 70, 70, 85, 90, 97, 100])
        self.assertFalse(os.path.exists(out[:-4] + '_unsigned.pdf'))

    def test_tool_edit_output_matches_plain_apply_ops(self):
        ops = [WHITEOUT]
        _seen, out = self.run_edit(ops)
        with fitz.open(self.path) as doc:
            pe.apply_ops(doc, ops)
            expected = doc[TEXT_PAGE].get_text()
        with fitz.open(out) as doc:
            self.assertEqual(doc[TEXT_PAGE].get_text(), expected)

    def test_tool_edit_cancel_stops_between_pages(self):
        tools = PdfTools(lambda progress: progress == 45 and tools.cancel())
        with self.assertRaises(PdfToolError) as caught:
            tools.run('edit', [self.path], os.path.join(self.tmp, 'cancelled'), {'ops': [WHITEOUT, dict(WHITEOUT, page=3)]})
        self.assertEqual(caught.exception.code, 'err_cancelled')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'cancelled.pdf')))


class FontIndexProgressTest(unittest.TestCase):
    def test_load_reports_scanned_files(self):
        folder = tempfile.mkdtemp()
        try:
            for name in ('a.ttf', 'b.otf', 'c.ttf', 'notes.txt'):
                with open(os.path.join(folder, name), 'wb') as handle:
                    handle.write(b'x')
            library = fm.FontLibrary(dirs=[folder])
            self.assertEqual(library.progress, (0, 0))
            seen = []
            with mock.patch.object(fm, 'scan_file', side_effect=lambda path: seen.append(library.progress) or []):
                library.load()
            self.assertEqual(seen, [(0, 3), (1, 3), (2, 3)])
            self.assertEqual(library.progress, (3, 3))
            self.assertTrue(library.ready.is_set())
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class Recorder:
    def __init__(self, kind, react=None):
        self.kind = kind
        self.react = react
        self.events = []

    def __call__(self, task):
        if task.kind != self.kind:
            return
        self.events.append((task.id, task.status, task.stage, task.progress, dict(task.detail), task.error))
        if self.react:
            self.react(task)

    def __enter__(self):
        self.interval, TASKS.interval = TASKS.interval, 0
        TASKS.subscribe(self)
        return self

    def __exit__(self, *_):
        TASKS.listeners.remove(self)
        TASKS.interval = self.interval

    def statuses(self):
        return [e[1] for e in self.events]


class TaskRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings('ignore')
        from app import create_app
        from app.routes.api_common import conversion_jobs
        cls.tmp = tempfile.mkdtemp()
        cls.path = build(os.path.join(cls.tmp, 'pe_test.pdf'))
        cls.file_id = 'wp3_' + os.urandom(6).hex()
        conversion_jobs[cls.file_id] = {'input_path': cls.path, 'original_filename': 'pe_test.pdf', 'owner': None}
        cls.app = create_app()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.client = self.app.test_client()
        self.client.get('/api/pdf/edit/tasks')

    def listed(self, kind):
        tasks = self.client.get(f'/api/pdf/edit/tasks?file_id={self.file_id}').get_json()['data']['tasks']
        return [t for t in tasks if t['kind'] == kind]

    def test_search_route_reports_pages(self):
        with Recorder('search') as rec:
            body = self.client.post('/api/pdf/edit/search', json={'file_id': self.file_id, 'query': 'a', 'ops': []}).get_json()
        self.assertTrue(body['success'])
        self.assertEqual(rec.statuses()[0], 'queued')
        self.assertEqual(rec.statuses()[-1], 'done')
        pages = [e[4]['done'] for e in rec.events if 'done' in e[4]]
        self.assertEqual(pages[:6], [0, 1, 2, 3, 4, 5])
        progress = [e[3] for e in rec.events if e[3] is not None]
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 1.0)
        listed = self.listed('search')
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['detail']['matches'], len(body['data']['matches']))
        self.assertNotIn('owner', listed[0])

    def test_search_route_can_be_cancelled(self):
        cancelled = []

        def react(task):
            if task.detail.get('done') == 2 and not cancelled:
                cancelled.append(None)
                cancelled[0] = TASKS.cancel(TASKS.get(task.id).owner, task.id)

        with Recorder('search', react) as rec:
            res = self.client.post('/api/pdf/edit/search', json={'file_id': self.file_id, 'query': 'a', 'ops': []})
        self.assertEqual(cancelled, [True])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['code'], 'err_cancelled')
        self.assertEqual(rec.statuses()[-1], 'cancelled')
        self.assertLessEqual(max(e[4].get('done', 0) for e in rec.events), 2)

    def test_empty_search_creates_no_task(self):
        with Recorder('search') as rec:
            self.client.post('/api/pdf/edit/search', json={'file_id': self.file_id, 'query': ' ', 'ops': []})
        self.assertEqual(rec.events, [])

    def test_search_tasks_are_owned(self):
        self.client.post('/api/pdf/edit/search', json={'file_id': self.file_id, 'query': 'a', 'ops': []})
        other = self.app.test_client()
        tasks = other.get(f'/api/pdf/edit/tasks?file_id={self.file_id}').get_json()['data']['tasks']
        self.assertEqual(tasks, [])

    def test_translate_route_reports_stages(self):
        pdf_translate.GLOSSARIES.items.clear()
        with Recorder('translate') as rec, mock.patch.object(pdf_ai, 'translate_page', return_value=[{'type': 'text', 'page': 1}]), \
                mock.patch.object(pdf_ai, 'build_glossary', return_value=[]):
            body = self.client.post('/api/pdf/edit/translate', json={'file_id': self.file_id, 'page': 1, 'language': 'English', 'ops': []}).get_json()
        self.assertTrue(body['success'])
        stages = [e[2] for e in rec.events]
        self.assertEqual([s for i, s in enumerate(stages) if s and (i == 0 or stages[i - 1] != s)], ['layout', 'glossary', 'translate', 'ops'])
        self.assertEqual(rec.statuses()[-1], 'done')
        self.assertEqual(rec.events[-1][4]['ops'], 1)
        self.assertEqual(self.listed('translate')[-1]['page'], 1)

    def test_translate_route_fails_task_on_ai_error(self):
        error = pdf_ai.AiError('err_ai_llm_offline', 'offline')
        with Recorder('translate') as rec, mock.patch.object(pdf_ai, 'translate_page', side_effect=error):
            res = self.client.post('/api/pdf/edit/translate', json={'file_id': self.file_id, 'page': 0, 'language': 'English', 'ops': []})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(rec.statuses()[-1], 'failed')
        self.assertEqual(rec.events[-1][5]['code'], 'err_ai_llm_offline')

    def test_translate_route_never_leaves_a_running_task(self):
        self.app.config['PROPAGATE_EXCEPTIONS'] = False
        try:
            with Recorder('translate') as rec, mock.patch.object(pdf_ai, 'translate_page', side_effect=RuntimeError('boom')):
                res = self.client.post('/api/pdf/edit/translate', json={'file_id': self.file_id, 'page': 0, 'language': 'English', 'ops': []})
        finally:
            self.app.config['PROPAGATE_EXCEPTIONS'] = None
        self.assertEqual(res.status_code, 500)
        self.assertEqual(rec.statuses()[-1], 'failed')

    def test_translate_route_out_of_range_page(self):
        with Recorder('translate') as rec:
            res = self.client.post('/api/pdf/edit/translate', json={'file_id': self.file_id, 'page': 40, 'language': 'English', 'ops': []})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(rec.events[-1][5]['code'], 'err_pdf_ranges')

    def test_ai_route_is_indeterminate_task(self):
        with Recorder('ai') as rec, mock.patch.object(pdf_ai, 'rewrite', return_value='Krócej.'):
            body = self.client.post('/api/pdf/edit/ai', json={'mode': 'shorter', 'text': 'Długi tekst'}).get_json()
        self.assertEqual(body['data']['text'], 'Krócej.')
        self.assertEqual(rec.statuses(), ['queued', 'running', 'done'])
        self.assertIsNone(rec.events[1][3])
        with Recorder('ai') as rec, mock.patch.object(pdf_ai, 'rewrite', side_effect=pdf_ai.AiError('err_ai_failed', 'x')):
            self.client.post('/api/pdf/edit/ai', json={'mode': 'shorter', 'text': 'x'})
        self.assertEqual(rec.statuses()[-1], 'failed')

    def test_font_status_route(self):
        library = fm.FontLibrary(dirs=[])
        library.progress = (120, 480)
        with mock.patch.object(fm.FontLibrary, 'shared', return_value=library):
            data = self.client.get('/api/pdf/edit/fonts/status').get_json()['data']
            self.assertEqual(data, {'ready': False, 'done': 120, 'total': 480})
            library.load()
            data = self.client.get('/api/pdf/edit/fonts/status').get_json()['data']
        self.assertTrue(data['ready'])


if __name__ == '__main__':
    unittest.main()
