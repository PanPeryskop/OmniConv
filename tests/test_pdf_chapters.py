import os
import shutil
import tempfile
import unittest
import zipfile

import fitz

from app.services import pdf_chapters
from app.services.pdf_tools import PdfTools

BODY = 'To jest zwykly akapit tekstu ksiazki, ktory ciagnie sie przez kilka linii i ma typowy rozmiar czcionki. ' * 6
STARTS = [2, 5, 8, 11]


def book(path, style='keyword', bookmarks=False, headers=True):
    doc = fitz.open()
    cover = doc.new_page()
    cover.insert_text((80, 200), 'Wielka Ksiazka', fontsize=36)
    contents = doc.new_page()
    contents.insert_text((72, 80), 'Spis tresci', fontsize=18)
    for i in range(1, 9):
        contents.insert_text((72, 120 + i * 22), f'Rozdzial {i}. Tytul rozdzialu {i} ........ {i * 3}', fontsize=11)
    for chapter in range(1, 5):
        for k in range(3):
            page = doc.new_page()
            if headers:
                page.insert_text((72, 40), 'Wielka Ksiazka - naglowek strony', fontsize=9)
                page.insert_text((290, 820), str(doc.page_count), fontsize=9)
            y = 90
            if k == 0 and style == 'keyword':
                page.insert_text((72, 110), f'Rozdzial {chapter}', fontsize=22)
                page.insert_text((72, 145), f'Tytul rozdzialu {chapter}', fontsize=22)
                y = 200
            elif k == 0 and style == 'numbered':
                page.insert_text((72, 120), f'{chapter}. Tytul rozdzialu {chapter}', fontsize=24)
                y = 170
            page.insert_textbox(fitz.Rect(72, y, 520, 780), BODY, fontsize=11)
    if bookmarks:
        toc = []
        for i, start in enumerate(STARTS, 1):
            toc.append([1, f'Czesc {i}', start + 1])
            if i == 2:
                toc.append([2, 'Pod', start + 2])
        doc.set_toc(toc)
    doc.save(path)
    doc.close()
    return path


def scan(path):
    doc = fitz.open()
    for _ in range(4):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 80), False)
        pix.clear_with(200)
        page.insert_image(page.rect, pixmap=pix)
    doc.save(path)
    doc.close()
    return path


class DetectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def starts(self, result):
        return [part['start'] for part in result['chapters']]

    def test_keyword_headings(self):
        result = pdf_chapters.detect(book(self.path('kw.pdf')))
        self.assertEqual(result['source'], 'headings')
        self.assertEqual(self.starts(result), [0] + STARTS)
        self.assertEqual(result['chapters'][1]['title'], 'Rozdzial 1 - Tytul rozdzialu 1')
        self.assertEqual([(p['start'], p['end']) for p in result['chapters']][-1], (11, 13))

    def test_numbered_large_titles(self):
        result = pdf_chapters.detect(book(self.path('num.pdf'), style='numbered'))
        self.assertEqual(self.starts(result), [0] + STARTS)
        self.assertEqual(result['chapters'][2]['title'], '2. Tytul rozdzialu 2')

    def test_contents_page_and_running_headers_are_not_chapters(self):
        result = pdf_chapters.detect(book(self.path('kw2.pdf')))
        self.assertNotIn(1, self.starts(result))
        titles = ' '.join(part['title'] for part in result['chapters'])
        self.assertNotIn('naglowek', titles)

    def test_plain_text_has_no_chapters(self):
        result = pdf_chapters.detect(book(self.path('plain.pdf'), style='none'))
        self.assertEqual(result['source'], 'none')
        self.assertEqual(result['chapters'], [{'start': 0, 'end': 13, 'title': ''}])

    def test_bookmarks_win_and_levels_are_selectable(self):
        path = book(self.path('bm.pdf'), style='none', bookmarks=True)
        first = pdf_chapters.detect(path)
        self.assertEqual((first['source'], first['levels'], first['level']), ('bookmarks', 2, 1))
        self.assertEqual(self.starts(first), [0] + STARTS)
        self.assertEqual(first['chapters'][1]['title'], 'Czesc 1')
        second = pdf_chapters.detect(path, level=2)
        self.assertEqual(self.starts(second), [0, 2, 5, 6, 8, 11])
        self.assertEqual(pdf_chapters.detect(path, level=7)['level'], 2)

    def test_headings_can_be_forced_over_bookmarks(self):
        path = book(self.path('bm2.pdf'), bookmarks=True)
        result = pdf_chapters.detect(path, source='headings')
        self.assertEqual(result['source'], 'headings')
        self.assertTrue(result['bookmarks'])
        self.assertTrue(result['chapters'][1]['title'].startswith('Rozdzial 1'))

    def test_scan_is_reported(self):
        result = pdf_chapters.detect(scan(self.path('scan.pdf')))
        self.assertEqual(result['source'], 'none')
        self.assertTrue(result['scanned'])

    def test_damaged_file(self):
        bad = self.path('bad.pdf')
        with open(bad, 'wb') as handle:
            handle.write(b'not a pdf')
        with self.assertRaises(pdf_chapters.ChapterError):
            pdf_chapters.detect(bad)


class SplitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = book(os.path.join(cls.tmp, 'book.pdf'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_groups_are_sanitized(self):
        parts = pdf_chapters.groups_from_starts([{'start': 5, 'title': ' B '}, {'start': 2, 'title': 'A'}, {'start': 5, 'title': 'dup'}, {'start': 99}, {'start': 'x'}, 'junk'], 14)
        self.assertEqual(parts, [{'start': 0, 'end': 1, 'title': ''}, {'start': 2, 'end': 4, 'title': 'A'}, {'start': 5, 'end': 13, 'title': 'B'}])

    def test_split_writes_one_file_per_part(self):
        out = PdfTools().run('split', [self.path], os.path.join(self.tmp, 'out'), {
            'mode': 'chapters', 'chapters': [{'start': 0, 'title': ''}, {'start': 2, 'title': 'Wstęp/Intro'}, {'start': 8, 'title': 'Koniec'}],
        })
        with zipfile.ZipFile(out) as archive:
            names = sorted(archive.namelist())
            counts = [fitz.open(stream=archive.read(name), filetype='pdf').page_count for name in names]
        self.assertEqual(len(names), 3)
        self.assertEqual(counts, [2, 6, 6])
        self.assertTrue(any('Koniec' in name for name in names))
        self.assertTrue(all('/' not in name for name in names))


class RouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import create_app
        from app.routes.api_common import conversion_jobs
        cls.tmp = tempfile.mkdtemp()
        cls.path = book(os.path.join(cls.tmp, 'book.pdf'), bookmarks=True)
        conversion_jobs['chapters-test'] = {'input_path': cls.path, 'original_filename': 'book.pdf', 'owner': None}
        cls.client = create_app().test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_route_returns_parts(self):
        body = self.client.post('/api/pdf/chapters', json={'file_id': 'chapters-test', 'level': 2}).get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['data']['level'], 2)
        self.assertEqual(len(body['data']['chapters']), 6)

    def test_route_rejects_bad_input(self):
        self.assertEqual(self.client.post('/api/pdf/chapters', json={'file_id': 'missing'}).status_code, 404)
        self.assertEqual(self.client.post('/api/pdf/chapters', json={'file_id': 'chapters-test', 'level': 'x'}).status_code, 400)
        body = self.client.post('/api/pdf/chapters', json={'file_id': 'chapters-test', 'source': 'evil'}).get_json()
        self.assertEqual(body['data']['source'], 'bookmarks')


if __name__ == '__main__':
    unittest.main()
