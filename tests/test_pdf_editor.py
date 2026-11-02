import os
import shutil
import tempfile
import unittest

import io
from unittest import mock

import fitz
from fontTools.ttLib import TTFont

from app.services import font_match as fm
from app.services import pdf_ai
from app.services import pdf_editor as pe
from app.services import pdf_scan
from app.services import pdf_search as ps
from app.services.web_fonts import web_font_bytes
from tests.fixtures.build_fixtures import build, build_scan, build_tagged

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
        cls.scan = build_scan(os.path.join(cls.tmp, 'pe_scan.pdf'), cls.path)

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

    def block_with(self, page, needle, ops=()):
        return next(b for b in self.layout(page, ops)['blocks'] if line_fonts([b], needle))

    def test_letter_spacing_survives_edit(self):
        block = self.block_with(TEXT_PAGE, 'ROZSTRZELONY')
        self.assertEqual(block['lines'][0]['spans'][0]['t'].strip(), 'ROZSTRZELONY NAGŁÓWEK')
        self.assertAlmostEqual(block['lines'][0]['spans'][0]['cs'], 3, delta=0.1)
        edited = self.block_with(TEXT_PAGE, 'NOWY', [text_op(TEXT_PAGE, block, 'NOWY NAGŁÓWEK')])
        self.assertAlmostEqual(edited['lines'][0]['spans'][0]['cs'], 3, delta=0.1)

    def test_superscript_and_subscript_keep_their_offset(self):
        block = self.block_with(TEXT_PAGE, 'Energia')
        spans = block['lines'][0]['spans']
        self.assertEqual([round(s['rise']) for s in spans], [0, 5, 0, -3, 0])
        op = text_op(TEXT_PAGE, block, '')
        op['runs'] = [dict(spans[0], t='Moc E = mc'), *spans[1:]]
        edited = self.block_with(TEXT_PAGE, 'Moc', [op])
        self.assertEqual([round(s['rise']) for s in edited['lines'][0]['spans'] if s['t'] == '2'], [5, -3])
        self.assertTrue(all(s['rise'] == 0 for s in edited['lines'][0]['spans'] if s['t'] != '2'))

    def test_overflow_is_reported_and_fit_shrinks_text(self):
        block = self.layout(TEXT_PAGE)['blocks'][1]
        op = text_op(TEXT_PAGE, block, ' '.join(['Bardzo długi tekst, który nie zmieści się w ramce.'] * 8))
        self.assertIn('0', self.layout(TEXT_PAGE, [op])['overflow'])
        fitted = self.layout(TEXT_PAGE, [dict(op, fit=True)])
        self.assertEqual(fitted['overflow'], {})
        written = self.block_with(TEXT_PAGE, 'Bardzo', [dict(op, fit=True)])
        self.assertLessEqual(written['bbox'][3], block['bbox'][3] + 0.5)

    def test_missing_glyph_uses_metric_compatible_font(self):
        library = fm.FontLibrary.shared().load()
        if not library.by_key.get('liberationsans'):
            self.skipTest('Liberation Sans is not installed')
        block = self.layout(TEXT_PAGE)['blocks'][1]
        with saved(self.path, [text_op(TEXT_PAGE, block, 'Źdźbło QWERTY')]) as doc:
            fonts = {s['font'] for b in doc[TEXT_PAGE].get_text('dict')['blocks'] if b['type'] == 0
                     for line in b['lines'] for s in line['spans'] if s['text'].strip() in ('Ź', 'Q', 'QWERTY', 'Ź', 'W')}
        self.assertTrue(any('Liberation' in f for f in fonts), fonts)

    def test_embedded_cff_font_becomes_web_font_with_real_glyphs_only(self):
        with fitz.open(self.path) as doc:
            xref = next(x for x, ext, _type, name, *_ in doc[TEXT_PAGE].get_fonts() if ext == 'cid' and 'Sans Regular' in name)
            name, ext, _type, buffer = doc.extract_font(xref)
        data = web_font_bytes(buffer, ext, 'Test')
        cmap = TTFont(io.BytesIO(data)).getBestCmap()
        self.assertIn(ord('ż'), cmap)
        self.assertNotIn(ord('Q'), cmap)

    def test_page_structure_inserts_rotates_moves_and_deletes(self):
        ops = [
            {'type': 'page', 'action': 'insert', 'page': 5, 'to': 1, 'size': [300, 400]},
            {'type': 'annot', 'page': 5, 'kind': 'rect', 'rect': [20, 20, 120, 80], 'color': '#2563eb'},
            {'type': 'page', 'action': 'rotate', 'page': 0, 'angle': 90},
            {'type': 'page', 'action': 'delete', 'page': ANNOT_PAGE},
            {'type': 'page', 'action': 'move', 'page': FORM_PAGE, 'to': 0},
        ]
        blank = pe.render_preview(self.path, 5, ops, 200)
        self.assertEqual((blank['width'], blank['height']), (300, 400))
        self.assertEqual([a['kind'] for a in blank['annots']], ['Square'])
        with saved(self.path, ops) as doc:
            self.assertEqual(doc.page_count, 5)
            self.assertIn('Formularz', doc[0].get_text())
            self.assertEqual(doc[1].rotation, 90)
            self.assertEqual(tuple(doc[2].rect)[2:], (300, 400))
            self.assertTrue(all('pending redaction' not in page.get_text() for page in doc))

    def test_page_structure_ignores_invalid_ops(self):
        order, rotation, blanks = pe.page_structure([
            {'type': 'page', 'action': 'insert', 'page': 9, 'to': 0},
            {'type': 'page', 'action': 'delete', 'page': 0},
            {'type': 'page', 'action': 'delete', 'page': 1},
        ], 2)
        self.assertEqual((order, rotation, blanks), ([1], {}, {}))

    def test_finds_text_and_validated_patterns(self):
        matches, truncated = pe.search_document(self.path, [], 'pending redaction', ['pesel', 'iban', 'phone'])
        kinds = {(m['kind'], m['text']) for m in matches}
        self.assertFalse(truncated)
        self.assertIn(('pesel', '44051401359'), kinds)
        self.assertIn(('iban', 'PL61109010140000071219812874'), kinds)
        self.assertIn(('text', 'pending redaction'), kinds)
        self.assertNotIn('44051401359', [m['text'] for m in matches if m['kind'] == 'phone'])

    def test_redacting_matches_removes_text_and_overlapping_fields(self):
        pesel = next(m for m in pe.search_document(self.path, [], '', ['pesel'])[0])
        field = next(w for w in self.layout(FORM_PAGE)['widgets'] if w['name'] == 'imie')
        ops = [{'type': 'redact', 'page': pesel['page'], 'rects': pesel['rects']},
               {'type': 'redact', 'page': FORM_PAGE, 'rect': field['rect']}]
        with saved(self.path, ops) as doc:
            self.assertNotIn('44051401359', doc[ANNOT_PAGE].get_text())
            self.assertIn('IBAN', doc[ANNOT_PAGE].get_text())
            self.assertNotIn('imie', [w.field_name for w in doc[FORM_PAGE].widgets()])

    def test_sanitize_scrubs_metadata(self):
        with saved(self.path, [{'type': 'sanitize', 'page': -1, 'options': {'metadata': True, 'comments': True}}]) as doc:
            self.assertEqual(doc.metadata['title'], '')
            self.assertEqual([a.type[1] for a in doc[ANNOT_PAGE].annots()], [])

    def fake_ocr(self, page):
        with fitz.open(self.path) as original:
            source = original[TEXT_PAGE]
            lines = []
            for block in source.get_text('dict')['blocks'][:3]:
                for line in block.get('lines', []):
                    text = ''.join(span['text'] for span in line['spans']).strip()
                    x0, y0, x1, y1 = line['bbox']
                    lines.append(('\uff2e' + text[1:] if text.startswith('N') else text, fitz.Point(x0, y1 - (y1 - y0) * 0.2), fitz.Point(x1, y1 - (y1 - y0) * 0.2), y1 - y0))
        return lines

    def test_scanned_page_is_detected_and_recognized(self):
        self.assertTrue(pe.render_preview(self.scan, 0, [], 200)['scanned'])
        with mock.patch.object(pdf_scan.OCR, 'lines', self.fake_ocr):
            layout = pe.render_preview(self.scan, 0, [{'type': 'ocr', 'page': 0}], 200)
        self.assertFalse(layout['scanned'])
        self.assertTrue(layout['blocks'])
        self.assertTrue(all(b['scan'] for b in layout['blocks']))
        span = layout['blocks'][1]['lines'][0]['spans'][0]
        self.assertLess(int(span['c'][1:3], 16), 60)
        self.assertEqual(span['k'], 'sans')

    def test_editing_scanned_text_inpaints_the_old_text(self):
        with mock.patch.object(pdf_scan.OCR, 'lines', self.fake_ocr):
            block = pe.render_preview(self.scan, 0, [{'type': 'ocr', 'page': 0}], 200)['blocks'][0]
            op = text_op(0, block, 'Nowy', align='left')
            with fitz.open(self.scan) as doc:
                ctx = pe.EditContext(doc)
                page = pe.apply_page_ops(ctx, doc[0], [{'type': 'ocr', 'page': 0}, op])
                pixels = pdf_scan.raster(page, fitz.Rect(block['bbox']))
        right = pixels[:, pixels.shape[1] // 2:]
        self.assertGreater(right.min(), 150)

    def test_rotated_page_is_editable(self):
        layout = self.layout(ROTATED_PAGE)
        self.assertEqual((layout['width'], layout['height']), (842, 595))
        self.assertTrue(layout['blocks'])


if __name__ == '__main__':
    unittest.main()


class FontMatchTest(unittest.TestCase):
    def test_parses_pdf_font_names(self):
        self.assertEqual(fm.parse_name('Arial-BoldMT'), ('Arial', True, False))
        self.assertEqual(fm.parse_name('ABCDEF+Calibri,BoldItalic'), ('Calibri', True, True))
        self.assertEqual(fm.parse_name('Times New Roman'), ('Times New Roman', False, False))
        self.assertEqual(fm.family_key('TimesNewRomanPSMT'), 'timesnewroman')

    def test_prefers_exact_then_metric_alias(self):
        faces = [
            {'family': 'Carlito', 'key': 'carlito', 'bold': False, 'italic': False, 'weight': 400, 'kind': 'sans', 'latin_ext': True},
            {'family': 'Liberation Serif', 'key': 'liberationserif', 'bold': True, 'italic': False, 'weight': 700, 'kind': 'serif', 'latin_ext': True},
        ]
        library = fm.FontLibrary(dirs=[])
        library.load()
        library.entries = faces
        library.by_key = {f['key']: [f] for f in faces}
        calibri = {'family': 'Calibri', 'name_family': 'Calibri', 'bold': False, 'italic': False, 'weight': 400, 'kind': 'sans'}
        self.assertEqual(library.match(calibri)[1], 'metric')
        times = {'family': 'Times New Roman', 'name_family': 'TimesNewRomanPS', 'bold': True, 'italic': False, 'weight': 700, 'kind': 'serif'}
        self.assertEqual(library.match(times)[0]['family'], 'Liberation Serif')
        carlito = dict(calibri, family='Carlito', name_family='Carlito')
        self.assertEqual(library.match(carlito)[1], 'exact')


class ValidatorTest(unittest.TestCase):
    def test_checksums(self):
        self.assertTrue(ps.valid_pesel('44051401359'))
        self.assertFalse(ps.valid_pesel('44051401358'))
        self.assertTrue(ps.valid_nip('526-025-09-95'))
        self.assertFalse(ps.valid_nip('5260250996'))
        self.assertTrue(ps.valid_regon('123456785'))
        self.assertTrue(ps.valid_iban('PL61 1090 1014 0000 0712 1981 2874'))
        self.assertFalse(ps.valid_iban('PL61 1090 1014 0000 0712 1981 2875'))
        self.assertTrue(ps.valid_card('4111 1111 1111 1111'))
        self.assertFalse(ps.valid_card('4111 1111 1111 1112'))
        self.assertTrue(ps.valid_id_card('ABA300000'))
        self.assertFalse(ps.valid_id_card('ABA300001'))


class AiTest(unittest.TestCase):
    @staticmethod
    def segmented(_prompt, text):
        return '\n\n'.join(f'<<{n}>> DE {body.strip()}' for n, body in pdf_ai.SEGMENT_RE.findall(text))

    def test_translate_many_keeps_segment_order(self):
        with mock.patch.object(pdf_ai, 'ask', self.segmented):
            self.assertEqual(pdf_ai.translate_many(['eins', 'zwei'], 'German'), ['DE eins', 'DE zwei'])

    def test_translate_many_falls_back_to_single_requests(self):
        replies = iter(['broken output', 'DE eins', 'DE zwei'])
        with mock.patch.object(pdf_ai, 'ask', lambda _prompt, _text: next(replies)):
            self.assertEqual(pdf_ai.translate_many(['eins', 'zwei'], 'German'), ['DE eins', 'DE zwei'])

    def test_translated_page_becomes_fitted_text_ops(self):
        path = build(os.path.join(tempfile.mkdtemp(), 'pe.pdf'))
        layout = pe.render_preview(path, TEXT_PAGE, [], 100)
        with mock.patch.object(pdf_ai, 'ask', self.segmented):
            ops = pdf_ai.translate_page(layout, TEXT_PAGE, 'German')
        self.assertTrue(ops)
        self.assertTrue(all(op['fit'] and op['runs'][0]['t'].startswith('DE ') for op in ops))
        self.assertNotIn('•', [op['runs'][0]['t'][3:] for op in ops])
        self.assertEqual(pe.render_preview(path, TEXT_PAGE, ops, 100)['overflow'], {})

    def test_offline_model_is_reported(self):
        with mock.patch.object(pdf_ai, 'status', lambda: 'llm_offline'):
            with self.assertRaises(pdf_ai.AiError) as caught:
                pdf_ai.rewrite('Tekst', 'shorter')
        self.assertEqual(caught.exception.code, 'err_ai_llm_offline')


def self_signed_p12(password='tajne'):
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Jan Kowalski')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30)).sign(key, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(b'jan', key, cert, None, serialization.BestAvailableEncryption(password.encode()))


class DigitalSignatureTest(unittest.TestCase):
    def test_wrong_password_is_rejected(self):
        from app.services.pdf_sign import CertificateStore, SignError
        with self.assertRaises(SignError) as caught:
            CertificateStore().put('me', self_signed_p12(), 'zle')
        self.assertEqual(caught.exception.code, 'err_cert_password')

    def test_certificate_is_single_use_and_owned(self):
        from app.services.pdf_sign import CertificateStore
        store = CertificateStore()
        cert_id, info = store.put('me', self_signed_p12(), 'tajne')
        self.assertEqual(info['name'], 'Jan Kowalski')
        self.assertIsNone(store.take(cert_id, 'someone else'))
        self.assertIsNotNone(store.take(cert_id, 'me'))
        self.assertIsNone(store.take(cert_id, 'me'))

    def test_edit_job_signs_with_pades_after_edits(self):
        from app.services.pdf_tools import PdfTools
        folder = tempfile.mkdtemp()
        path = build(os.path.join(folder, 'pe.pdf'))
        ops = [
            {'type': 'whiteout', 'page': TEXT_PAGE, 'rect': [60, 420, 300, 450]},
            {'type': 'page', 'action': 'move', 'page': FORM_PAGE, 'to': 0},
            {'type': 'digital_sign', 'page': FORM_PAGE, 'rect': [300, 700, 520, 760], 'reason': 'Akceptacja'},
        ]
        out = PdfTools(lambda _p: None).run('edit', [path], os.path.join(folder, 'out'), {'ops': ops, 'certificate': (self_signed_p12(), 'tajne')})
        with fitz.open(out) as doc:
            widgets = [w for w in doc[0].widgets() if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE]
            self.assertEqual(len(widgets), 1)
            self.assertAlmostEqual(widgets[0].rect.y0, 700, delta=1)
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        with open(out, 'rb') as handle:
            reader = PdfFileReader(handle)
            signature = reader.embedded_signatures[0]
            status = validate_pdf_signature(signature)
            self.assertTrue(status.intact and status.valid)
            self.assertEqual(signature.sig_object['/SubFilter'], '/ETSI.CAdES.detached')


class ShapingTest(unittest.TestCase):
    def library_font(self, family):
        library = fm.FontLibrary.shared().load()
        entry = library.styled(fm.family_key(family), False, False)
        if not entry:
            self.skipTest(f'{family} is not installed')
        return library.font(entry)

    def test_kerning_changes_advance(self):
        from app.services import shaping
        font = self.library_font('Liberation Sans')
        glyphs = shaping.SHAPER.shape(font, 'AVATAR')
        self.assertLess(shaping.advance(glyphs, 20), font.text_length('AVATAR', fontsize=20))

    def test_rtl_paragraph_is_written_right_aligned_and_extractable(self):
        self.library_font('DejaVu Sans')
        path = build(os.path.join(tempfile.mkdtemp(), 'pe.pdf'))
        block = pe.render_preview(path, TEXT_PAGE, [], 100)['blocks'][4]
        with saved(path, [text_op(TEXT_PAGE, block, 'שלום עולם', align='left')]) as doc:
            line = next(l for b in doc[TEXT_PAGE].get_text('dict')['blocks'] if b['type'] == 0 for l in b['lines']
                        if 'שלום' in ''.join(s['text'] for s in l['spans']))
        self.assertGreater(line['bbox'][2], block['bbox'][0] + 100)


class TaggedTextTest(unittest.TestCase):
    def structure_texts(self, page):
        found = []

        def walk(blocks, tag=None):
            for block in blocks:
                if block['type'] == 2:
                    walk(block['blocks'], block['raw'])
                elif block['type'] == 0:
                    found.append((tag, ''.join(s['text'] for l in block['lines'] for s in l['spans']).strip()))
        walk(page.get_text('dict', flags=fitz.TEXT_COLLECT_STRUCTURE)['blocks'])
        return found

    def test_edited_paragraph_keeps_its_tag(self):
        from app.services import pdf_tags
        path = build_tagged(os.path.join(tempfile.mkdtemp(), 'tagged.pdf'))
        block = pe.render_preview(path, 0, [], 100)['blocks'][0]
        with saved(path, [text_op(0, block, 'Zmieniony akapit.')]) as doc:
            texts = self.structure_texts(doc[0])
            data = pdf_tags.contents(doc[0])[1]
        self.assertIn(('P', 'Zmieniony akapit.'), texts)
        self.assertIn(('P', 'Drugi otagowany akapit.'), texts)
        self.assertNotIn('Pierwszy', ' '.join(t for _tag, t in texts))
        ids = [s['mcid'] for s in pdf_tags.sequences(data) if s['mcid'] is not None]
        self.assertEqual(sorted(ids), [0, 1])

    def test_tokenizer_handles_strings_and_inline_images(self):
        from app.services import pdf_tags
        data = (b'/P <</MCID 3>> BDC BT (a\\) EMC \\(x\\)) Tj ET EMC '
                b'/Span <</MCID 4>> BDC BI /W 1 /H 1 /CS /G /BPC 8 ID \x00 EI EMC')
        found = {s['mcid']: (s['text'], s['paint']) for s in pdf_tags.sequences(data)}
        self.assertEqual(found, {3: (True, False), 4: (False, True)})
