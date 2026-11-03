import os
import shutil
import tempfile
import unittest
from unittest import mock

import fitz

from app.services import pdf_agent_tools as tools
from app.services import pdf_ai, pdf_translate
from app.services.editor_tasks import TASKS
from tests.fixtures.build_fixtures import build

GLOSSARY_REPLY = '1. Edytor PDF => PDF editor\n- "Zażółć" => Zażółć\nnot a pair\nedytor pdf => duplicate\n'


def fake_ask(log):
    def ask(system, text):
        log.append((system, text))
        if 'prepare a glossary' in system:
            return GLOSSARY_REPLY
        body = text.split('<translate>', 1)[-1].split('</translate>', 1)[0]
        return '\n\n'.join(f'<<{n}>> T:{segment.strip()}' for n, segment in pdf_ai.SEGMENT_RE.findall(body)) + '\n</translate>'
    return ask


def block(text, y=0):
    return {
        'lines': [{'spans': [{'t': text, 'font': 'Helvetica', 'size': 11, 'color': '#000000'}], 'brk': False, 'rects': [[0, y, 100, y + 12]]}],
        'bbox': [0, y, 100, y + 12], 'baseline': y + 10, 'lh': 1.2, 'align': 'left',
    }


class PromptTest(unittest.TestCase):
    def test_without_context_the_request_is_unchanged(self):
        self.assertEqual(pdf_ai.segments_input(['a', 'b'], None), '<<1>> a\n\n<<2>> b')
        self.assertNotIn('<context>', pdf_ai.segments_prompt('English', None))
        self.assertEqual(pdf_ai.segments_prompt('English', pdf_ai.TranslationContext()), pdf_ai.segments_prompt('English', None))

    def test_context_carries_page_neighbours_and_glossary(self):
        context = pdf_ai.TranslationContext(page=['Tytuł', 'Akapit drugi'], before='Koniec poprzedniej.', after='Początek następnej.',
                                            glossary=[('Edytor', 'Editor')])
        text = pdf_ai.segments_input(['Akapit drugi'], context, 1, 1)
        head, tail = text.split('<translate>')
        for part in ('Edytor => Editor', 'Koniec poprzedniej.', 'Tytuł', 'Akapit drugi', 'Początek następnej.'):
            self.assertIn(part, head)
        self.assertEqual(tail.strip(), '<<1>> Akapit drugi\n</translate>')
        self.assertLess(head.index('Glossary'), head.index('previous page'))
        self.assertIn('never translate', pdf_ai.segments_prompt('English', context))

    def test_long_page_keeps_a_window_around_the_chunk(self):
        texts = [f'Blok {i} ' + 'x' * 90 for i in range(100)]
        window = pdf_ai.page_window(texts, 50, 51, 1200)
        self.assertIn('Blok 50 ', window)
        self.assertIn('Blok 51 ', window)
        self.assertNotIn('Blok 0 ', window)
        self.assertTrue(window.startswith('…') and window.endswith('…'))
        self.assertLessEqual(len(window), 1200 + 10)
        self.assertEqual(pdf_ai.page_window(texts[:3], 0, 0, 5000), '\n\n'.join(texts[:3]))

    def test_context_stays_within_budget(self):
        context = pdf_ai.TranslationContext(page=['y' * 500] * 40, before='b' * 400, after='a' * 400, glossary=[('t', 'u')] * 40)
        self.assertLess(len(pdf_ai.context_text(context, 20, 21)), pdf_ai.MAX_CONTEXT + 600)


class TranslateTest(unittest.TestCase):
    def test_segments_are_parsed_without_closing_tag(self):
        log = []
        context = pdf_ai.TranslationContext(page=['a', 'b'])
        with mock.patch.object(pdf_ai, 'ask', side_effect=fake_ask(log)):
            self.assertEqual(pdf_ai.translate_many(['a', 'b'], 'English', context, 0, 1), ['T:a', 'T:b'])
        self.assertEqual(len(log), 1)
        self.assertIn('<context>', log[0][1])

    def test_missing_segment_falls_back_one_by_one_then_plain(self):
        replies = iter(['<<1>> T:a', '<<1>> T:a', 'no markers here', 'plain b'])
        with mock.patch.object(pdf_ai, 'ask', side_effect=lambda system, text: next(replies)) as ask:
            result = pdf_ai.translate_many(['a', 'b'], 'English', pdf_ai.TranslationContext(page=['a', 'b']))
        self.assertEqual(result, ['T:a', 'plain b'])
        self.assertNotIn('<context>', ask.call_args_list[-1].args[1])

    def test_translate_page_uses_whole_page_for_a_selection(self):
        layout = {'blocks': [block('Pierwszy akapit', 0), block('Drugi akapit', 20), block('Trzeci akapit', 40)]}
        log = []
        context = pdf_ai.TranslationContext()
        with mock.patch.object(pdf_ai, 'ask', side_effect=fake_ask(log)):
            ops = pdf_ai.translate_page(layout, 2, 'English', context=context, blocks=[layout['blocks'][1]])
        self.assertEqual([op['runs'][0]['t'] for op in ops], ['T:Drugi akapit'])
        self.assertEqual(context.page, ['Pierwszy akapit', 'Drugi akapit', 'Trzeci akapit'])
        self.assertIn('Trzeci akapit', log[0][1].split('<translate>')[0])

    def test_translate_page_without_context_matches_old_behaviour(self):
        layout = {'blocks': [block('Pierwszy akapit'), block('12')]}
        with mock.patch.object(pdf_ai, 'ask', side_effect=fake_ask([])) as ask:
            ops = pdf_ai.translate_page(layout, 0, 'English')
        self.assertEqual(len(ops), 1)
        self.assertEqual(ask.call_args.args[1], '<<1>> Pierwszy akapit')


class GlossaryTest(unittest.TestCase):
    def test_parses_dedupes_and_limits(self):
        with mock.patch.object(pdf_ai, 'ask', return_value=GLOSSARY_REPLY):
            terms = pdf_ai.build_glossary('Edytor PDF ' * 20, 'English')
        self.assertEqual(terms, [('Edytor PDF', 'PDF editor'), ('Zażółć', 'Zażółć')])
        with mock.patch.object(pdf_ai, 'ask', return_value='\n'.join(f't{i} => u{i}' for i in range(90))):
            self.assertEqual(len(pdf_ai.build_glossary('słowo ' * 30, 'English')), pdf_ai.MAX_GLOSSARY_TERMS)

    def test_short_text_skips_the_model_and_failures_return_none(self):
        with mock.patch.object(pdf_ai, 'ask') as ask:
            self.assertEqual(pdf_ai.build_glossary('abc', 'English'), [])
        ask.assert_not_called()
        with mock.patch.object(pdf_ai, 'ask', side_effect=pdf_ai.AiError('err_ai_llm_offline', 'x')):
            self.assertIsNone(pdf_ai.build_glossary('słowo ' * 30, 'English'))


class DocumentContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmp, 'pe_test.pdf')
        build(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        pdf_translate.GLOSSARIES.items.clear()

    def test_neighbours_come_from_adjacent_pages(self):
        with fitz.open(self.path) as doc:
            before, after = pdf_translate.neighbours(doc, 1)
            first = pdf_translate.neighbours(doc, 0)
            last = pdf_translate.neighbours(doc, doc.page_count - 1)
            beyond = pdf_translate.neighbours(doc, doc.page_count + 3)
        self.assertTrue(before and after)
        self.assertLessEqual(len(before), pdf_translate.NEIGHBOUR_CHARS)
        self.assertEqual(first[0], '')
        self.assertEqual(last[1], '')
        self.assertEqual(beyond, ('', ''))

    def test_glossary_is_built_once_per_document_and_language(self):
        log = []
        with mock.patch.object(pdf_ai, 'ask', side_effect=fake_ask(log)):
            self.assertFalse(pdf_translate.has_glossary(self.path, 'English'))
            first = pdf_translate.page_context(self.path, 0, 'English')
            second = pdf_translate.page_context(self.path, 2, 'english')
            pdf_translate.page_context(self.path, 0, 'German')
        self.assertEqual(first.glossary, second.glossary)
        self.assertTrue(pdf_translate.has_glossary(self.path, 'English'))
        self.assertEqual(sum('prepare a glossary' in system for system, _ in log), 2)

    def test_failed_glossary_is_retried_later(self):
        with mock.patch.object(pdf_ai, 'ask', side_effect=pdf_ai.AiError('err_ai_llm_offline', 'x')):
            self.assertEqual(pdf_translate.page_context(self.path, 0, 'English').glossary, [])
        self.assertFalse(pdf_translate.has_glossary(self.path, 'English'))


class AgentToolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmp, 'pe_test.pdf')
        build(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_translate_tool_shares_context_and_reports_terms(self):
        pdf_translate.GLOSSARIES.items.clear()
        log = []
        ctx = tools.ToolContext(self.path, 'file', [], [], {'kind': 'document'})
        with mock.patch.object(pdf_ai, 'ask', side_effect=fake_ask(log)):
            result = tools.run_tool(ctx, 'translate', {'pages': [3], 'language': 'English'})
        self.assertEqual(result.content['glossary'], ['Edytor PDF => PDF editor', 'Zażółć => Zażółć'])
        self.assertEqual(len(result.proposals), 1)
        self.assertEqual(result.proposals[0]['terms'], [['Edytor PDF', 'PDF editor'], ['Zażółć', 'Zażółć']])
        translations = [text for system, text in log if '<translate>' in text]
        self.assertTrue(translations and all('<context>' in text for text in translations))


class RouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import create_app
        from app.routes.api_common import conversion_jobs
        cls.tmp = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmp, 'pe_test.pdf')
        build(cls.path)
        cls.file_id = 'translate-context-test'
        conversion_jobs[cls.file_id] = {'input_path': cls.path, 'original_filename': 'pe_test.pdf', 'owner': None}
        cls.app = create_app()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        pdf_translate.GLOSSARIES.items.clear()
        self.client = self.app.test_client()
        self.stages = []
        self.interval, TASKS.interval = TASKS.interval, 0
        self.listener = lambda task: task.kind == 'translate' and self.stages.append(task.stage)
        TASKS.subscribe(self.listener)

    def tearDown(self):
        TASKS.listeners.remove(self.listener)
        TASKS.interval = self.interval

    def translate(self, page):
        return self.client.post('/api/pdf/edit/translate', json={'file_id': self.file_id, 'ops': [], 'page': page, 'language': 'English'}).get_json()

    def test_route_builds_glossary_once_and_sends_context(self):
        log = []
        with mock.patch.object(pdf_ai, 'ask', side_effect=fake_ask(log)), mock.patch.object(pdf_ai, 'status', return_value='ok'):
            first = self.translate(0)
            stages_first, self.stages = self.stages, []
            second = self.translate(2)
        self.assertTrue(first['success'] and second['success'])
        self.assertIn('glossary', stages_first)
        self.assertLess(stages_first.index('glossary'), stages_first.index('translate'))
        self.assertNotIn('glossary', self.stages)
        translations = [text for system, text in log if '<translate>' in text]
        self.assertTrue(translations)
        self.assertTrue(all('Edytor PDF => PDF editor' in text for text in translations))
        self.assertTrue(all(op['runs'][0]['t'].startswith('T:') for op in first['data']['ops']))


if __name__ == '__main__':
    unittest.main()
