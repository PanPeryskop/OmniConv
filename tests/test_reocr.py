import os
import shutil
import tempfile
import unittest
from unittest import mock

import fitz
from flask import Flask, g

from app.services import pdf_editor as pe
from app.services import pdf_scan
from tests.fixtures.build_fixtures import build, build_scan
from tests.test_wp2 import FakeSteps, wait_idle

FORCE = {'type': 'ocr', 'page': 0, 'force': True, 'retry': 1}
OLD = 'Bledny tekst ze starego OCR'


def texts(layout):
    return [''.join(s['t'] for line in b['lines'] for s in line['spans']) for b in layout['blocks']]


class ReOcrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.digital = build(os.path.join(cls.tmp, 'pe.pdf'))
        cls.scan = build_scan(os.path.join(cls.tmp, 'scan.pdf'), cls.digital)
        cls.layered = os.path.join(cls.tmp, 'layered.pdf')
        with fitz.open(cls.scan) as doc:
            page = doc[0]
            for i in range(3):
                page.insert_text((80, 120 + i * 30), f'{OLD} {i}', fontsize=12, render_mode=3)
            doc.save(cls.layered)
        cls.app = Flask(__name__)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def preview(self, path, ops):
        with self.app.test_request_context():
            g.client_id = 'me'
            g.edit_file_id = 'file1'
            return pe.render_preview(path, 0, list(ops), 120)

    def settled(self, path, ops):
        with mock.patch.object(pdf_scan, 'ocr_steps', lambda: FakeSteps(lines=4)):
            layout = self.preview(path, ops)
            if layout.get('ocr_pending'):
                wait_idle()
                layout = self.preview(path, ops)
        return layout

    def test_ocr_able_marks_scans_only(self):
        self.assertTrue(self.preview(self.layered, [])['ocr_able'])
        self.assertTrue(self.preview(self.scan, [])['ocr_able'])
        self.assertFalse(self.preview(self.digital, [])['ocr_able'])

    def test_plain_ocr_still_skips_a_page_with_text(self):
        layout = self.settled(self.layered, [{'type': 'ocr', 'page': 0}])
        self.assertTrue(any(OLD in text for text in texts(layout)))

    def test_forced_ocr_replaces_the_hidden_layer(self):
        layout = self.settled(self.layered, [FORCE])
        joined = ' '.join(texts(layout))
        self.assertNotIn(OLD, joined)
        self.assertIn('Line 1', joined)
        self.assertEqual(joined.count('Line 1'), 1)
        self.assertTrue(all(b['scan'] for b in layout['blocks']))

    def test_forced_ocr_keeps_the_scan_image(self):
        with fitz.open(self.layered) as doc:
            before = doc[0].get_pixmap(matrix=fitz.Matrix(0.5, 0.5)).samples
        with fitz.open(self.layered) as doc:
            page = pe.strip_hidden_text(doc[0])
            self.assertFalse(pe.hidden_spans(page)[0])
            self.assertEqual(page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5)).samples, before)

    def test_forced_ocr_is_ignored_on_digital_pages(self):
        layout = self.preview(self.digital, [dict(FORCE)])
        self.assertFalse(layout.get('ocr_pending'))
        self.assertIn('Synthetic editor test', ' '.join(texts(layout)))

    def test_earlier_text_edits_are_superseded_and_return_on_undo(self):
        base = self.settled(self.layered, [])
        block = base['blocks'][0]
        edit = {
            'type': 'text', 'page': 0, 'remove': [r for line in block['lines'] for r in line['rects']], 'rect': block['bbox'],
            'baseline': block['baseline'], 'lh': block['lh'], 'align': block['align'], 'family': 'original', 'fit': True,
            'runs': [dict(block['lines'][0]['spans'][0], t='Poprawka uzytkownika', rise=0)],
        }
        edited = self.settled(self.layered, [edit])
        self.assertIn('Poprawka uzytkownika', ' '.join(texts(edited)))
        reset = self.settled(self.layered, [edit, FORCE])
        self.assertNotIn('Poprawka uzytkownika', ' '.join(texts(reset)))
        self.assertIn('Line 1', ' '.join(texts(reset)))
        after = self.settled(self.layered, [FORCE, edit])
        self.assertIn('Poprawka uzytkownika', ' '.join(texts(after)))

    def test_plan_keeps_original_indexes(self):
        ops = [{'type': 'text'}, {'type': 'annot'}, {'type': 'ocr'}, FORCE, {'type': 'whiteout'}]
        self.assertEqual([i for i, _op in pe.page_plan(ops)], [3, 1, 4])
        self.assertEqual([i for i, _op in pe.page_plan(ops[:3])], [0, 1, 2])


if __name__ == '__main__':
    unittest.main()
