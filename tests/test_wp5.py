import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from app.services import pdf_agent_tools as tools
from app.services import pdf_ai
from app.services import pdf_editor as pe
from tests.fixtures.build_fixtures import build

TEXT_PAGE, IMAGE_PAGE, ANNOT_PAGE = 0, 1, 2
NAMES = {
    'list_pages', 'read_page', 'search', 'replace_text', 'proofread', 'set_style', 'insert_text',
    'delete_text', 'highlight', 'add_note', 'redact', 'translate', 'page_action', 'finish',
}


def text_op(page, block, text):
    return dict(pdf_ai.block_op(page, block, text), fit=False)


def fake_fix(prompt, text):
    return text.replace('wykladu', 'wykładu')


def fake_translate(prompt, text):
    return text.replace('Highlighted', 'Lighted')


class Wp5Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = build(os.path.join(cls.tmp, 'pe_test.pdf'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ctx(self, ops=(), working=None, scope=None):
        self.events = []
        working = list(ops) if working is None else list(working)
        return tools.ToolContext(self.path, 'file', list(ops), working, scope or {'kind': 'document'}, lambda e, d: self.events.append((e, d)))

    def call(self, ctx, name, **args):
        result = tools.run_tool(ctx, name, args)
        json.dumps(result.content)
        json.dumps(result.proposals)
        return result

    def layout(self, page, ops=()):
        return pe.render_preview(self.path, page, tools.ops_for_page(list(ops), page, 5), 200)

    def texts(self, page, ops=()):
        return [pdf_ai.block_text(b) for b in self.layout(page, ops)['blocks']]

    def block(self, ctx, page, needle):
        blocks = self.call(ctx, 'read_page', page=page).content['blocks']
        return next(b for b in blocks if needle in b['text'])

    def applied(self, ctx, proposal):
        return ctx.working_ops + proposal['ops']

    def test_all_tools_registered_with_schemas(self):
        specs = {spec.name: spec for spec in tools.tool_specs()}
        self.assertEqual(set(specs), NAMES)
        for spec in specs.values():
            self.assertEqual(spec.parameters['type'], 'object')
            self.assertTrue(set(spec.parameters['required']) <= set(spec.parameters['properties']))
            self.assertIn('Example', spec.description)
            json.dumps(spec.parameters)

    def test_list_pages_follows_page_structure(self):
        ctx = self.ctx()
        pages = self.call(ctx, 'list_pages').content['pages']
        self.assertEqual([p['page'] for p in pages], [0, 1, 2, 3, 4])
        self.assertEqual(pages[0]['blocks'], 12)
        self.assertFalse(pages[0]['edited'])
        ops = [{'type': 'page', 'action': 'delete', 'page': 1}, {'type': 'page', 'action': 'insert', 'page': 5, 'to': 0, 'size': [300, 400]}]
        pages = self.call(self.ctx(ops), 'list_pages').content['pages']
        self.assertEqual([p['page'] for p in pages], [5, 0, 2, 3, 4])
        self.assertEqual((pages[0]['width'], pages[0]['height'], pages[0]['blocks'], pages[0]['edited']), (300, 400, 0, True))

    def test_read_page_is_compact_and_truncates(self):
        ctx = self.ctx()
        content = self.call(ctx, 'read_page', page=TEXT_PAGE).content
        layout = self.layout(TEXT_PAGE)
        self.assertFalse(content['truncated'])
        self.assertEqual([b['id'] for b in content['blocks']], [tools.block_id(TEXT_PAGE, i, b) for i, b in enumerate(layout['blocks'])])
        title = content['blocks'][0]
        self.assertEqual(set(title), {'id', 'text', 'bbox', 'size', 'bold', 'italic', 'color', 'align'})
        self.assertEqual((title['text'], title['size'], title['bold'], title['align']), ('Synthetic editor test', 24.0, True, 'center'))
        short = self.call(ctx, 'read_page', page=TEXT_PAGE, max_chars=500).content
        self.assertTrue(short['truncated'])
        start = int(re.search(r'start=(\d+)', short['message']).group(1))
        self.assertEqual(start, len(short['blocks']))
        rest = self.call(ctx, 'read_page', page=TEXT_PAGE, start=start).content
        self.assertEqual(rest['blocks'][0]['id'], content['blocks'][start]['id'])
        annots = self.call(ctx, 'read_page', page=ANNOT_PAGE).content['annots']
        self.assertIn({'kind': 'Text', 'rect': [500.0, 60.0, 516.0, 76.0], 'text': 'Existing note'}, annots)
        deleted = self.ctx([{'type': 'page', 'action': 'delete', 'page': 1}])
        self.assertEqual(self.call(deleted, 'read_page', page=1).content['error'], 'no_page')

    def test_search_returns_matches_with_block_ids(self):
        ctx = self.ctx()
        content = self.call(ctx, 'search', query='PESEL').content
        self.assertEqual([m['page'] for m in content['matches']], [ANNOT_PAGE])
        self.assertEqual(content['matches'][0]['block_id'], self.block(ctx, ANNOT_PAGE, 'Sensitive')['id'])
        found = self.call(ctx, 'search', patterns=['pesel', 'iban'], pages=[ANNOT_PAGE]).content['matches']
        self.assertEqual({m['kind']: m['text'] for m in found}, {'pesel': '44051401359', 'iban': 'PL61109010140000071219812874'})
        self.assertEqual(self.call(ctx, 'search', patterns=['nope']).content['error'], 'bad_args')

    def test_replace_text(self):
        ops = [{'type': 'annot', 'page': TEXT_PAGE, 'kind': 'note', 'rect': [10, 10, 30, 30], 'text': 'x', 'g': 7}]
        ctx = self.ctx(ops)
        block = self.block(ctx, TEXT_PAGE, 'Drugi punkt')
        result = self.call(ctx, 'replace_text', block_id=block['id'], text='Drugi punkt zmieniony', reason='test')
        proposal = result.proposals[0]
        self.assertEqual(result.content['proposals'], [proposal['id']])
        self.assertEqual((proposal['kind'], proposal['page'], proposal['before'], proposal['after'], proposal['reason']), ('text', TEXT_PAGE, 'Drugi punkt listy', 'Drugi punkt zmieniony', 'test'))
        self.assertEqual(proposal['rects'], [self.layout(TEXT_PAGE)['blocks'][6]['bbox']])
        self.assertEqual(proposal['base'], {'count': 1, 'last_g': 7})
        self.assertEqual(proposal['depends_on'], [])
        self.assertTrue(proposal['ops'][0]['fit'])
        texts = self.texts(TEXT_PAGE, self.applied(ctx, proposal))
        self.assertIn('Drugi punkt zmieniony', texts)
        self.assertNotIn('Drugi punkt listy', texts)
        self.assertEqual(self.call(ctx, 'replace_text', block_id=block['id'], text='Drugi  punkt listy').content['error'], 'no_change')

    def test_stale_block_after_page_changed(self):
        ctx = self.ctx()
        block = self.block(ctx, TEXT_PAGE, 'Trzeci punkt')
        original = self.layout(TEXT_PAGE)['blocks'][8]
        changed = self.ctx([text_op(TEXT_PAGE, original, 'Trzeci punkt inny')])
        for name, args in (('replace_text', {'text': 'Nowy'}), ('delete_text', {}), ('set_style', {'bold': True}), ('highlight', {})):
            self.assertEqual(self.call(changed, name, block_id=block['id'], **args).content['error'], 'stale_block')
        self.assertEqual(self.call(ctx, 'replace_text', block_id='p0b99-abcdef', text='x').content['error'], 'stale_block')
        self.assertEqual(self.call(ctx, 'replace_text', block_id='garbage', text='x').content['error'], 'stale_block')
        fresh = self.block(changed, TEXT_PAGE, 'Trzeci punkt inny')
        self.assertNotIn('error', self.call(changed, 'replace_text', block_id=fresh['id'], text='Trzeci').content)

    def test_out_of_scope(self):
        full = self.ctx()
        other = self.block(full, ANNOT_PAGE, 'Sensitive')
        ctx = self.ctx(scope={'kind': 'page', 'pages': [TEXT_PAGE]})
        self.assertEqual(self.call(ctx, 'read_page', page=ANNOT_PAGE).content['error'], 'out_of_scope')
        self.assertEqual(self.call(ctx, 'replace_text', block_id=other['id'], text='x').content['error'], 'out_of_scope')
        self.assertEqual(self.call(ctx, 'search', query='PESEL', pages=[ANNOT_PAGE]).content['error'], 'out_of_scope')
        self.assertEqual(self.call(ctx, 'search', query='PESEL').content['matches'], [])
        self.assertEqual(self.call(ctx, 'page_action', action='delete', page=ANNOT_PAGE).content['error'], 'out_of_scope')
        self.assertEqual(self.call(ctx, 'add_note', page=ANNOT_PAGE, x=10, y=10, text='x').content['error'], 'out_of_scope')
        self.assertEqual(self.call(ctx, 'redact', patterns=['pesel']).content['matches'], 0)
        pages = self.call(ctx, 'list_pages').content['pages']
        self.assertEqual([p['page'] for p in pages if p['in_scope']], [TEXT_PAGE])
        selection = self.ctx(scope={'kind': 'selection', 'block_ids': [other['id']]})
        self.assertNotIn('error', self.call(selection, 'read_page', page=ANNOT_PAGE).content)
        self.assertEqual(self.call(selection, 'read_page', page=TEXT_PAGE).content['error'], 'out_of_scope')

    def test_proofread_skips_unchanged_blocks_and_bullets(self):
        original = self.layout(TEXT_PAGE)['blocks'][4]
        ops = [text_op(TEXT_PAGE, original, 'Pierwszy punkt wykladu')]
        ctx = self.ctx(ops)
        with mock.patch.object(pdf_ai, 'ask', side_effect=fake_fix) as ask:
            result = self.call(ctx, 'proofread', pages=[TEXT_PAGE], language='Polish')
        sent = [call.args[1] for call in ask.call_args_list]
        self.assertEqual(len(sent), 9)
        self.assertNotIn('•', sent)
        self.assertIn('Polish', ask.call_args_list[0].args[0])
        self.assertEqual(len(result.proposals), 1)
        proposal = result.proposals[0]
        self.assertEqual((proposal['kind'], proposal['before'], proposal['after'], proposal['reason']), ('text', 'Pierwszy punkt wykladu', 'Pierwszy punkt wykładu', 'wykladu → wykładu'))
        self.assertEqual(proposal['base'], {'count': 1, 'last_g': None})
        self.assertEqual(result.content['checked'], 9)
        self.assertFalse(result.content['truncated'])
        self.assertEqual(result.content['changes'][0]['changes'], 'wykladu → wykładu')
        self.assertIn('Pierwszy punkt wykładu', self.texts(TEXT_PAGE, self.applied(ctx, proposal)))
        self.assertTrue(any(e == 'tool_progress' for e, _d in self.events))

    def test_proofread_truncates_and_continues(self):
        ctx = self.ctx()
        with mock.patch.object(tools, 'MAX_PROOFREAD_BLOCKS', 3), mock.patch.object(pdf_ai, 'ask', side_effect=fake_fix) as ask:
            first = self.call(ctx, 'proofread', pages=[TEXT_PAGE]).content
            start = int(re.search(r'start=(\d+)', first['message']).group(1))
            second = self.call(ctx, 'proofread', pages=[TEXT_PAGE], start=start).content
        self.assertTrue(first['truncated'])
        self.assertEqual(first['checked'], 3)
        self.assertEqual(start, 4)
        self.assertEqual(second['checked'], 3)
        self.assertEqual(ask.call_count, 6)
        self.assertEqual(ask.call_args_list[3].args[1], 'Pierwszy punkt listy')

    def test_proofread_rejects_implausible_rewrites_and_respects_selection(self):
        ctx = self.ctx()
        target = self.block(ctx, TEXT_PAGE, 'Drugi punkt')
        selection = self.ctx(scope={'kind': 'selection', 'pages': [TEXT_PAGE], 'block_ids': [target['id']]})
        with mock.patch.object(pdf_ai, 'ask', return_value='Completely different answer from a chatty model') as ask:
            result = self.call(selection, 'proofread')
        self.assertEqual([c.args[1] for c in ask.call_args_list], ['Drugi punkt listy'])
        self.assertEqual(result.proposals, [])

    def test_set_style(self):
        ctx = self.ctx()
        block = self.block(ctx, TEXT_PAGE, 'Drugi punkt')
        proposal = self.call(ctx, 'set_style', block_id=block['id'], size=16, bold=True, color='#FF0000').proposals[0]
        self.assertEqual((proposal['kind'], proposal['before'], proposal['after']), ('style', 'Drugi punkt listy', 'Drugi punkt listy'))
        self.assertEqual(proposal['reason'], 'size 16, color #ff0000, bold')
        run = proposal['ops'][0]['runs'][0]
        self.assertEqual((run['t'], run['s'], run['b'], run['c']), ('Drugi punkt listy', 16.0, True, '#ff0000'))
        title = self.block(ctx, TEXT_PAGE, 'Synthetic')
        bigger = self.call(ctx, 'set_style', block_id=title['id'], size=30, color='#ff0000').proposals[0]
        after = next(b for b in self.layout(TEXT_PAGE, self.applied(ctx, bigger))['blocks'] if pdf_ai.block_text(b) == 'Synthetic editor test')
        span = after['lines'][0]['spans'][0]
        self.assertEqual((span['s'], span['b'], span['c']), (30.0, True, '#ff0000'))
        paragraph = self.block(ctx, TEXT_PAGE, 'Edytor PDF')
        runs = self.call(ctx, 'set_style', block_id=paragraph['id'], italic=True).proposals[0]['ops'][0]['runs']
        self.assertEqual(''.join(r['t'] for r in runs).split(), paragraph['text'].split())
        self.assertTrue(all(r['i'] for r in runs))
        self.assertEqual(self.call(ctx, 'set_style', block_id=block['id'], bold=False).content['error'], 'no_change')

    def test_insert_text(self):
        ctx = self.ctx()
        like = self.block(ctx, TEXT_PAGE, 'ROZSTRZELONY')
        proposal = self.call(ctx, 'insert_text', page=TEXT_PAGE, x=60, y=700, text='STARY ZEGAR', like_block_id=like['id']).proposals[0]
        op = proposal['ops'][0]
        self.assertEqual((proposal['kind'], proposal['after'], op['remove'], op['baseline'], op['family']), ('insert', 'STARY ZEGAR', [], 700.0, 'original'))
        layout = self.layout(TEXT_PAGE, self.applied(ctx, proposal))
        added = next(b for b in layout['blocks'] if pdf_ai.block_text(b) == 'STARY ZEGAR')
        source = self.layout(TEXT_PAGE)['blocks'][10]['lines'][0]['spans'][0]
        self.assertEqual((added['lines'][0]['spans'][0]['b'], added['lines'][0]['spans'][0]['s']), (True, source['s']))
        self.assertLess(abs(added['baseline'] - 700), 1)
        plain = self.call(ctx, 'insert_text', page=TEXT_PAGE, x=60, y=720, text='Zwykly').proposals[0]
        self.assertEqual((plain['ops'][0]['family'], plain['ops'][0]['runs'][0]['s']), ('sans', 12))
        self.assertIn('Zwykly', self.texts(TEXT_PAGE, self.applied(ctx, plain)))
        self.assertEqual(self.call(ctx, 'insert_text', page=TEXT_PAGE, x=900, y=10, text='x').content['error'], 'bad_args')

    def test_delete_text(self):
        ctx = self.ctx()
        block = self.block(ctx, TEXT_PAGE, 'Right aligned')
        proposal = self.call(ctx, 'delete_text', block_id=block['id']).proposals[0]
        self.assertEqual((proposal['kind'], proposal['before'], proposal['ops'][0]['runs']), ('delete', 'Right aligned footer line', []))
        self.assertTrue(proposal['ops'][0]['remove'])
        self.assertNotIn('Right aligned footer line', self.texts(TEXT_PAGE, self.applied(ctx, proposal)))

    def test_highlight(self):
        ctx = self.ctx()
        proposal = self.call(ctx, 'highlight', page=TEXT_PAGE, query='punkt listy').proposals[0]
        op = proposal['ops'][0]
        self.assertEqual((proposal['kind'], op['type'], op['kind'], op['color'], len(op['rects'])), ('annot', 'annot', 'highlight', '#ffd400', 3))
        self.assertEqual(proposal['rects'], op['rects'])
        annots = self.layout(TEXT_PAGE, self.applied(ctx, proposal))['annots']
        self.assertEqual([a['kind'] for a in annots], ['Highlight'])
        block = self.block(ctx, TEXT_PAGE, 'Synthetic')
        by_block = self.call(ctx, 'highlight', block_id=block['id'], color='#86efac').proposals[0]
        self.assertEqual((by_block['page'], by_block['ops'][0]['color'], len(by_block['ops'][0]['rects'])), (TEXT_PAGE, '#86efac', 1))
        self.assertEqual(self.call(ctx, 'highlight', page=TEXT_PAGE, query='missing words').content['matches'], 0)

    def test_add_note(self):
        ctx = self.ctx()
        proposal = self.call(ctx, 'add_note', page=TEXT_PAGE, x=400, y=100, text='Sprawdź datę').proposals[0]
        self.assertEqual(proposal['ops'], [{'type': 'annot', 'page': TEXT_PAGE, 'kind': 'note', 'rect': [400.0, 100.0, 420.0, 120.0], 'text': 'Sprawdź datę', 'color': '#f59e0b'}])
        annots = self.layout(TEXT_PAGE, self.applied(ctx, proposal))['annots']
        self.assertEqual([(a['kind'], a['text']) for a in annots], [('Text', 'Sprawdź datę')])

    def test_redact(self):
        ctx = self.ctx()
        result = self.call(ctx, 'redact', patterns=['pesel', 'iban'])
        self.assertEqual(len(result.proposals), 1)
        proposal = result.proposals[0]
        op = proposal['ops'][0]
        self.assertEqual((proposal['kind'], proposal['page'], op['type'], op['page'], len(op['rects'])), ('redact', ANNOT_PAGE, 'redact', ANNOT_PAGE, 2))
        self.assertEqual(proposal['reason'], '1 × pesel, 1 × iban')
        self.assertIn('44051401359', proposal['before'])
        text = ' '.join(self.texts(ANNOT_PAGE, self.applied(ctx, proposal)))
        self.assertIn('Sensitive: PESEL', text)
        self.assertNotIn('44051401359', text)
        self.assertNotIn('PL61109010140000071219812874', text)
        self.assertEqual(self.call(ctx, 'redact', query='nothing like this').content['matches'], 0)

    def test_translate(self):
        ctx = self.ctx()
        with mock.patch.object(pdf_ai, 'ask', side_effect=fake_translate):
            result = self.call(ctx, 'translate', pages=[ANNOT_PAGE], language='English')
        proposal = result.proposals[0]
        self.assertEqual((proposal['kind'], proposal['page'], len(proposal['ops']), len(proposal['rects'])), ('text', ANNOT_PAGE, 3, 3))
        self.assertTrue(proposal['after'].startswith('Lighted sentence'))
        self.assertTrue(all(op['fit'] for op in proposal['ops']))
        self.assertIn('Lighted sentence for markup tests.', self.texts(ANNOT_PAGE, self.applied(ctx, proposal)))
        self.assertEqual(result.content['translated'], [ANNOT_PAGE])
        with mock.patch.object(tools, 'MAX_TRANSLATE_PAGES', 1), mock.patch.object(pdf_ai, 'ask', side_effect=fake_translate):
            many = self.call(ctx, 'translate', pages=[ANNOT_PAGE, TEXT_PAGE], language='English').content
        self.assertTrue(many['truncated'])
        self.assertIn('pages=[0]', many['message'])
        self.assertEqual(self.call(ctx, 'translate', pages=[0]).content['error'], 'bad_args')

    def test_page_action(self):
        ops = [{'type': 'page', 'action': 'rotate', 'page': 3, 'angle': 90, 'g': 2}]
        ctx = self.ctx(ops)
        rotate = self.call(ctx, 'page_action', action='rotate', page=3, angle=-90).proposals[0]
        self.assertEqual(rotate['ops'], [{'type': 'page', 'action': 'rotate', 'page': 3, 'angle': 270}])
        self.assertEqual((rotate['kind'], rotate['base']), ('page', {'count': 1, 'last_g': 2}))
        delete = self.call(ctx, 'page_action', action='delete', page=1).proposals[0]
        move = self.call(ctx, 'page_action', action='move', page=4, to=0).proposals[0]
        insert = self.call(ctx, 'page_action', action='insert_blank', page=0)
        blank = insert.proposals[0]
        self.assertEqual(insert.content['new_page'], 5)
        self.assertEqual(blank['ops'], [{'type': 'page', 'action': 'insert', 'page': 5, 'to': 1, 'size': [595.0, 842.0]}])
        self.assertEqual((blank['page'], blank['base']), (5, {'count': 0, 'last_g': None}))
        everything = ops + delete['ops'] + move['ops'] + blank['ops']
        order, rotation, _blanks = pe.page_structure(everything, 5)
        self.assertEqual(order, [4, 5, 0, 2, 3])
        self.assertEqual(rotation, {3: 90})
        self.assertEqual(self.call(ctx, 'page_action', action='move', page=0, to=0).content['error'], 'no_change')
        self.assertEqual(self.call(ctx, 'page_action', action='flip', page=0).content['error'], 'bad_args')
        self.assertEqual([p['page'] for p in self.call(self.ctx(everything), 'list_pages').content['pages']], [4, 5, 0, 2, 3])

    def test_finish_and_unknown_tool(self):
        ctx = self.ctx()
        self.assertEqual(self.call(ctx, 'finish', summary='Gotowe').content, {'done': True, 'summary': 'Gotowe'})
        self.assertEqual(tools.run_tool(ctx, 'nope', {}).content['error'], 'unknown_tool')

    def test_base_uses_request_ops_not_working_ops(self):
        client = [{'type': 'annot', 'page': ANNOT_PAGE, 'kind': 'note', 'rect': [10, 10, 30, 30], 'text': 'a', 'g': 4},
                  {'type': 'annot', 'page': TEXT_PAGE, 'kind': 'note', 'rect': [10, 10, 30, 30], 'text': 'b', 'g': 9}]
        earlier = {'type': 'annot', 'page': ANNOT_PAGE, 'kind': 'note', 'rect': [40, 40, 60, 60], 'text': 'c'}
        ctx = self.ctx(client, client + [earlier])
        proposal = self.call(ctx, 'add_note', page=ANNOT_PAGE, x=100, y=100, text='d').proposals[0]
        self.assertEqual(proposal['base'], {'count': 1, 'last_g': 4})
        self.assertEqual(len(self.call(ctx, 'read_page', page=ANNOT_PAGE).content['annots']), 7)


if __name__ == '__main__':
    unittest.main()
