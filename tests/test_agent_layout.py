import os
import shutil
import tempfile
import unittest

import fitz

from app.services import pdf_agent_tools as tools
from app.services import pdf_ai
from app.services import pdf_editor as pe
from tests.fixtures.build_fixtures import build


def span(t, s=11, b=False, rise=0.0, c='#000000'):
    return {'t': t, 's': s, 'c': c, 'b': b, 'i': False, 'f': 0, 'k': 'serif', 'n': [], 'lib': '', 'cs': 0.0, 'rise': rise}


def line(spans, brk=False, y=0):
    return {'spans': spans, 'brk': brk, 'bbox': [0, y, 100, y + 12], 'rects': [[0, y, 100, y + 12]]}


def block(lines):
    return {'lines': lines, 'bbox': [0, 0, 100, 12 * len(lines)], 'baseline': 10, 'lh': 1.2, 'align': 'left'}


class BlockTextTest(unittest.TestCase):
    def test_lines_join_like_the_editor(self):
        b = block([line([span('Pierwszy wy-')]), line([span('kład trwa')], brk=True, y=12), line([span('  Nowa linia')], y=24)])
        self.assertEqual(pdf_ai.block_text(b), 'Pierwszy wykład trwa\nNowa linia')

    def test_soft_hyphen_and_spaces(self):
        b = block([line([span('roz­')]), line([span('dział ')], y=12)])
        self.assertEqual(pdf_ai.block_text(b), 'rozdział')

    def test_single_letter_words_are_translated(self):
        self.assertTrue(pdf_ai.translatable('w'))
        self.assertTrue(pdf_ai.translatable('Badanie'))
        self.assertFalse(pdf_ai.translatable('•'))
        self.assertFalse(pdf_ai.translatable('12'))
        self.assertFalse(pdf_ai.translatable('a)'))


class RestyleTest(unittest.TestCase):
    def test_typo_fix_keeps_bold_and_size_of_each_part(self):
        b = block([line([span('Uwaga:', b=True), span(' tekst ma błendy i inne słowa')])])
        runs = pdf_ai.restyle(b, 'Uwaga: tekst ma błędy i inne słowa')
        self.assertEqual(''.join(r['t'] for r in runs), 'Uwaga: tekst ma błędy i inne słowa')
        self.assertEqual(runs[0]['t'], 'Uwaga:')
        self.assertTrue(runs[0]['b'])
        self.assertTrue(all(not r['b'] for r in runs[1:]))

    def test_superscript_survives_an_edit_next_to_it(self):
        b = block([line([span('Energia E = mc', s=12), span('2', s=8, rise=5.0), span(' oraz wzór', s=12)])])
        runs = pdf_ai.restyle(b, 'Energia E = mc2 i wzór wody')
        texts = [(r['t'], r['rise']) for r in runs]
        self.assertIn(('2', 5.0), texts)
        self.assertTrue(all(r['rise'] == 0 for r in runs if r['t'] != '2'))

    def test_translation_takes_the_dominant_style(self):
        b = block([line([span('w', s=14)]), line([span('pediatrii i wielu innych dziedzinach', s=40)], y=12)])
        runs = pdf_ai.restyle(b, 'in pediatrics and many other fields')
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['s'], 40)

    def test_line_breaks_are_kept(self):
        b = block([line([span('Pierwsza')], brk=True), line([span('Druga')], y=12)])
        runs = pdf_ai.restyle(b, 'Pierwsza\nDruga linia')
        self.assertEqual(''.join(r['t'] for r in runs), 'Pierwsza\nDruga linia')

    def test_empty_text_has_no_runs(self):
        self.assertEqual(pdf_ai.restyle(block([line([span('x')])]), ''), [])


class FixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = build(os.path.join(cls.tmp, 'pe_test.pdf'))
        cls.layout = pe.render_preview(cls.path, 0, [], 100)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def find(self, text):
        return next(b for b in self.layout['blocks'] if pdf_ai.block_text(b).startswith(text))

    def words_in(self, ops, rect):
        with fitz.open(self.path) as doc:
            page = pe.apply_page_ops(pe.EditContext(doc), doc[0], ops)
            return [w[4] for w in page.get_text('words') if fitz.Rect(w[:4]).intersects(fitz.Rect(rect))]

    def test_agent_edit_of_the_formula_keeps_sub_and_superscripts(self):
        formula = self.find('Energia')
        op = pdf_ai.block_op(0, formula, pdf_ai.block_text(formula).replace('oraz', 'i'))
        self.assertEqual([r['rise'] for r in op['runs'] if r['rise']], [5.0, -3.0])
        layout = pe.render_preview(self.path, 0, [dict(op, g=1)], 100)
        edited = next(b for b in layout['blocks'] if pdf_ai.block_text(b).startswith('Energia'))
        self.assertEqual(pdf_ai.block_text(edited), 'Energia E = mc2 i wzór wody H2O.')
        self.assertEqual(sorted({s['rise'] for l in edited['lines'] for s in l['spans']} - {0.0}), [-3.0, 5.0])

    def test_grouped_text_ops_do_not_erase_each_other(self):
        title, paragraph = self.find('Synthetic'), self.find('Edytor PDF')
        long = dict(pdf_ai.block_op(0, title, 'A much longer translated title that wraps onto several lines below the old one'), grow=False, fit=False)
        gone = dict(pdf_ai.block_op(0, paragraph, ''), runs=[])
        area = paragraph['bbox']
        sequential = self.words_in([dict(long, g=1), dict(gone, g=2)], area)
        grouped = self.words_in([dict(long, g=1), dict(gone, g=1)], area)
        self.assertNotIn('several', sequential)
        self.assertIn('several', grouped)

    def test_batches_split_by_group_and_type(self):
        ops = [{'type': 'text', 'g': 1}, {'type': 'text', 'g': 1}, {'type': 'annot', 'g': 1}, {'type': 'text', 'g': 2}, {'type': 'text'}, {'type': 'text'}]
        self.assertEqual([[i for i, _op in batch] for batch in pe.text_batches(list(enumerate(ops)))], [[0, 1], [2], [3], [4], [5]])


class BlockIdTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = build(os.path.join(cls.tmp, 'pe_test.pdf'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ctx(self):
        return tools.ToolContext(self.path, 'file', [], [], {'kind': 'document'})

    def test_id_without_hash_resolves_to_the_current_block(self):
        page, index, found, _layout = tools.find_block(self.ctx(), 'p0b4')
        self.assertEqual((page, index, pdf_ai.block_text(found)), (0, 4, 'Pierwszy punkt listy'))

    def test_wrong_hash_is_still_stale(self):
        with self.assertRaises(tools.ToolError):
            tools.find_block(self.ctx(), 'p0b4-000000')


if __name__ == '__main__':
    unittest.main()
