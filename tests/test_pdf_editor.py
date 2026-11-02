import os
import shutil
import tempfile
import unittest

import fitz

from app.services import pdf_editor as pe
from tests.fixtures.build_fixtures import build

TEXT_PAGE, IMAGE_PAGE, ANNOT_PAGE, FORM_PAGE, ROTATED_PAGE = range(5)


def text_op(page, block, text, **extra):
    return {
        'type': 'text', 'page': page,
        'remove': [r for line in block['lines'] for r in line['rects']],
        'rect': block['bbox'], 'baseline': block['baseline'], 'lh': block['lh'],
        'align': block['align'], 'family': 'original', 'grow': all(line['brk'] for line in block['lines']),
        'runs': [dict(block['lines'][0]['spans'][0], t=text)], **extra,
    }


def line_fonts(blocks, needle, resolve=lambda f: f):
    for block in blocks:
        for line in block['lines']:
            if needle in ''.join(s['t'] for s in line['spans']):
                return [resolve(s['f']) for s in line['spans']]
    return None


def saved(path, ops):
    out = path + '.out.pdf'
    with fitz.open(path) as doc:
        pe.apply_ops(doc, ops)
        doc.save(out, garbage=3, deflate=True)
    return fitz.open(out)


class PdfEditorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = build(os.path.join(cls.tmp, 'pe_test.pdf'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def layout(self, page, ops=()):
        return pe.render_preview(self.path, page, list(ops), 200)

    def test_lists_inline_and_nested_images_but_not_patterns(self):
        images = self.layout(IMAGE_PAGE)['images']
        self.assertEqual(len(images), 6)
        self.assertIn(0, [i['xref'] for i in images])
        self.assertFalse(next(i for i in images if i['bbox'][0] == 340)['movable'])

    def test_moves_inline_image(self):
        images = self.layout(IMAGE_PAGE)['images']
        inline = next(i for i in images if i['xref'] == 0)
        target = [inline['bbox'][0] - 200, inline['bbox'][1] + 100, inline['bbox'][2] - 200, inline['bbox'][3] + 100]
        after = self.layout(IMAGE_PAGE, [{'type': 'image', 'page': IMAGE_PAGE, 'xref': 0, 'remove': inline['bbox'], 'rect': target}])['images']
        boxes = [i['bbox'] for i in after]
        self.assertEqual(len(after), len(images))
        self.assertIn(target, boxes)
        self.assertNotIn(inline['bbox'], boxes)

    def test_moving_xobject_image_reuses_it(self):
        images = self.layout(IMAGE_PAGE)['images']
        photo = images[2]
        target = [photo['bbox'][0], photo['bbox'][1] + 300, photo['bbox'][2], photo['bbox'][3] + 300]
        with fitz.open(self.path) as doc:
            digest = next(i['digest'] for i in doc[IMAGE_PAGE].get_image_info(xrefs=True) if i['xref'] == photo['xref'])
            stored = len(doc[IMAGE_PAGE].get_images())
        with saved(self.path, [{'type': 'image', 'page': IMAGE_PAGE, 'xref': photo['xref'], 'remove': photo['bbox'], 'rect': target}]) as doc:
            infos = doc[IMAGE_PAGE].get_image_info(xrefs=True)
            moved = [i for i in infos if abs(i['bbox'][1] - target[1]) < 0.5]
            self.assertEqual([i['digest'] for i in moved], [digest])
            self.assertEqual(len(infos), len(images))
            self.assertEqual(len(doc[IMAGE_PAGE].get_images()), stored)

    def test_deletes_image_inside_form_only(self):
        images = self.layout(IMAGE_PAGE)['images']
        nested = images[4]
        after = self.layout(IMAGE_PAGE, [{'type': 'image', 'page': IMAGE_PAGE, 'xref': nested['xref'], 'remove': nested['bbox']}])
        self.assertEqual([i['bbox'] for i in after['images']], [i['bbox'] for i in images if i is not nested])
        self.assertEqual(len(after['blocks']), 1)

    def test_rotated_image_is_not_moved(self):
        rotated = next(i for i in self.layout(IMAGE_PAGE)['images'] if not i['movable'])
        target = [0, 0, 100, 150]
        after = self.layout(IMAGE_PAGE, [{'type': 'image', 'page': IMAGE_PAGE, 'xref': rotated['xref'], 'remove': rotated['bbox'], 'rect': target}])
        self.assertIn(rotated['bbox'], [i['bbox'] for i in after['images']])

    def test_text_edit_keeps_pending_redactions(self):
        block = self.layout(ANNOT_PAGE)['blocks'][0]
        with saved(self.path, [text_op(ANNOT_PAGE, block, 'Changed sentence.')]) as doc:
            page = doc[ANNOT_PAGE]
            kinds = [a.type[1] for a in page.annots()]
            self.assertIn('Redact', kinds)
            self.assertIn('pending redaction', page.get_text())
            self.assertIn('Changed sentence.', page.get_text())

    def test_redaction_keeps_other_pending_marks(self):
        with saved(self.path, [{'type': 'redact', 'page': ANNOT_PAGE, 'rect': [55, 115, 540, 140]}]) as doc:
            page = doc[ANNOT_PAGE]
            self.assertNotIn('PESEL', page.get_text())
            self.assertIn('pending redaction', page.get_text())
            self.assertEqual(sum(1 for a in page.annots() if a.type[1] == 'Redact'), 1)

    def test_polish_text_uses_original_font(self):
        block = self.layout(TEXT_PAGE)['blocks'][1]
        original = block['lines'][0]['spans'][0]['f']
        after = self.layout(TEXT_PAGE, [text_op(TEXT_PAGE, block, 'gęśla żółć jaźń')])
        self.assertEqual(line_fonts(after['blocks'], 'gęśla żółć jaźń'), [original])

    def test_font_ids_match_between_preview_and_save(self):
        first = self.layout(TEXT_PAGE)['blocks'][1]
        other = self.layout(ANNOT_PAGE)['blocks'][0]
        once = [text_op(ANNOT_PAGE, other, 'Edited once')]
        edited = next(b for b in self.layout(ANNOT_PAGE, once)['blocks'] if line_fonts([b], 'Edited once'))
        ops = [text_op(TEXT_PAGE, first, 'Shift every new xref'), *once, text_op(ANNOT_PAGE, edited, 'Edited twice')]
        preview = self.layout(ANNOT_PAGE, [o for o in ops if o['page'] == ANNOT_PAGE])
        expected = line_fonts(preview['blocks'], 'Edited twice')
        with fitz.open(self.path) as original, saved(self.path, ops) as doc:
            limit = original.xref_length()
            fonts = {name: xref for name, xref, _subset in pe.page_fonts(original[ANNOT_PAGE])}
            actual = line_fonts(pe.page_layout(doc[ANNOT_PAGE])['blocks'], 'Edited twice')
        self.assertIn(other['lines'][0]['spans'][0]['f'], expected)
        self.assertTrue(all(f < limit for f in expected))
        self.assertEqual(len(actual), len(expected))
        self.assertTrue(fonts)

    def test_radio_group_stays_exclusive(self):
        widgets = self.layout(FORM_PAGE)['widgets']
        radios = [w for w in widgets if w['kind'] == 'radio']
        ops = [{'type': 'form', 'page': FORM_PAGE, 'name': 'plec', 'rect': radios[2]['rect'], 'value': True},
               {'type': 'form', 'page': FORM_PAGE, 'name': 'plec', 'rect': radios[0]['rect'], 'value': False}]
        after = [w['value'] for w in self.layout(FORM_PAGE, ops)['widgets'] if w['kind'] == 'radio']
        self.assertEqual(after, [False, False, True])

    def test_rotated_page_is_editable(self):
        layout = self.layout(ROTATED_PAGE)
        self.assertEqual((layout['width'], layout['height']), (842, 595))
        self.assertTrue(layout['blocks'])


if __name__ == '__main__':
    unittest.main()
