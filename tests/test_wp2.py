import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import fitz
from flask import Flask, g

from app.services import pdf_editor as pe
from app.services import pdf_scan
from app.services.editor_tasks import TASKS
from app.services.ocr import OCRService
from tests.fixtures.build_fixtures import build, build_scan

OCR_OP = {'type': 'ocr', 'page': 0}


class FakeSteps:
    def __init__(self, lines=20, gate=None):
        self.count = lines
        self.gate = gate
        self.recognized = 0

    def detect(self, path):
        zoom = OCRService().rapid_dpi / 72.0
        boxes = [(80 * zoom, (90 + i * 30) * zoom, 420 * zoom, (108 + i * 30) * zoom) for i in range(self.count)]
        batches = [list(range(i, min(i + 8, self.count))) for i in range(0, self.count, 8)]
        return SimpleNamespace(boxes=boxes, batches=batches, texts={})

    def recognize(self, scan, batch):
        if self.gate and self.recognized:
            self.gate.wait(5)
        self.recognized += 1
        for index in batch:
            scan.texts[index] = f'Line {index + 1}'

    def items(self, scan):
        return [(scan.texts[i], 0.99, box) for i, box in enumerate(scan.boxes) if i in scan.texts]


def scan_file():
    folder = tempfile.mkdtemp()
    return build_scan(os.path.join(folder, 'scan.pdf'), build(os.path.join(folder, 'pe.pdf')))


def wait_idle(timeout=10):
    until = time.time() + timeout
    while pdf_scan.OCR.pending and time.time() < until:
        time.sleep(0.05)


class Wp2Test(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.events = []
        self.listener = lambda task: self.events.append((task.id, task.status, task.stage, task.progress, dict(task.detail)))
        self.interval, TASKS.interval = TASKS.interval, 0
        TASKS.subscribe(self.listener)

    def tearDown(self):
        TASKS.listeners.remove(self.listener)
        TASKS.interval = self.interval

    def preview(self, path, ops=(OCR_OP,), owner='me'):
        with self.app.test_request_context():
            g.client_id = owner
            g.edit_file_id = 'file1'
            return pe.render_preview(path, 0, list(ops), 120)

    def trail(self, task_id):
        return [event for event in self.events if event[0] == task_id]

    def test_preview_reports_stages_boxes_and_progress(self):
        path = scan_file()
        with mock.patch.object(pdf_scan, 'ocr_steps', lambda: FakeSteps()):
            pending = self.preview(path)
            self.assertTrue(pending['ocr_pending'])
            task_id = pending['task_id']
            self.assertEqual(self.preview(path)['task_id'], task_id)
            wait_idle()
            layout = self.preview(path)
        self.assertIn('Line 1', ' '.join(s['t'] for b in layout['blocks'] for line in b['lines'] for s in line['spans']))
        trail = self.trail(task_id)
        stages = [stage for i, (_id, _status, stage, _p, _d) in enumerate(trail) if stage and (i == 0 or trail[i - 1][2] != stage)]
        self.assertEqual(stages, ['render', 'orientation', 'detect', 'recognize', 'layout', 'fonts'])
        progress = [p for *_rest, p, _d in trail if p is not None]
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(trail[-1][1], 'done')
        detect = next(e[4] for e in trail if e[2] == 'detect')
        self.assertEqual(len(detect['boxes']), 20)
        self.assertEqual(detect['size'], [595.0, 842.0])
        self.assertEqual(detect['lines'], 0)
        self.assertAlmostEqual(detect['boxes'][0][0], 80, delta=1)
        self.assertAlmostEqual(detect['boxes'][0][1], 90, delta=1)
        batches = [e[4] for e in trail if e[2] == 'recognize']
        self.assertEqual([(d['done'], d['total'], d['lines']) for d in batches], [(1, 3, 8), (2, 3, 16), (3, 3, 20)])
        self.assertIsNotNone(batches[-1]['eta_s'])
        self.assertEqual(TASKS.get(task_id).file_id, 'file1')
        self.assertEqual(TASKS.get(task_id).page, 0)

    def test_other_owner_does_not_get_task_id(self):
        path = scan_file()
        gate = threading.Event()
        with mock.patch.object(pdf_scan, 'ocr_steps', lambda: FakeSteps(gate=gate)):
            self.assertIn('task_id', self.preview(path))
            self.assertEqual(self.preview(path, owner='other'), {'ocr_pending': True})
            gate.set()
            wait_idle()

    def test_cancel_stops_batches_and_drops_result(self):
        path = scan_file()
        gate = threading.Event()
        steps = FakeSteps(gate=gate)
        with mock.patch.object(pdf_scan, 'ocr_steps', lambda: steps):
            task_id = self.preview(path)['task_id']
            until = time.time() + 5
            while not any(e[2] == 'recognize' for e in self.trail(task_id)) and time.time() < until:
                time.sleep(0.02)
            self.assertTrue(TASKS.cancel('me', task_id))
            gate.set()
            wait_idle()
            self.assertIn(steps.recognized, (1, 2))
            self.assertEqual(TASKS.get(task_id).status, 'cancelled')
            self.assertFalse(any(e[2] in ('layout', 'fonts') for e in self.trail(task_id)))
            again = self.preview(path)
            self.assertNotIn('ocr_pending', again)
            self.assertEqual(again['blocks'], [])
            retry = self.preview(path, [dict(OCR_OP), dict(OCR_OP, retry=1)])
            self.assertNotEqual(retry['task_id'], task_id)
            wait_idle()
            done = self.preview(path, [dict(OCR_OP), dict(OCR_OP, retry=1)])
        self.assertTrue(done['blocks'])

    def test_second_page_waits_in_queue(self):
        path = scan_file()
        gate = threading.Event()
        with mock.patch.object(pdf_scan, 'ocr_steps', lambda: FakeSteps(gate=gate)):
            first = self.preview(path)['task_id']
            second = self.preview(scan_file())['task_id']
            self.assertEqual(TASKS.get(second).status, 'queued')
            gate.set()
            wait_idle()
        self.assertEqual(self.trail(first)[-1][2], 'layout')

    def test_save_blocks_and_creates_no_task(self):
        path = scan_file()
        before = len(TASKS.tasks)
        with mock.patch.object(pdf_scan, 'ocr_steps', lambda: FakeSteps(lines=3)):
            with fitz.open(path) as doc:
                pe.apply_ops(doc, [OCR_OP])
                self.assertIn('Line 1', doc[0].get_text())
        self.assertEqual(len(TASKS.tasks), before)

    def test_progress_is_silent_without_task(self):
        renders = [('a', fitz.Identity, fitz.Point(0, 0), 1), ('b', fitz.Identity, fitz.Point(0, 0), 1)]
        steps = FakeSteps(lines=2)
        with mock.patch.object(pdf_scan, 'ocr_steps', lambda: steps):
            lines = pdf_scan.recognize_renders(renders)
        self.assertEqual([line[0] for line in lines], ['Line 1', 'Line 2'])


@unittest.skipUnless(os.environ.get('PE_SKIP_RAPID') is None, 'real RapidOCR disabled')
class RapidSplitTest(unittest.TestCase):
    def test_split_matches_engine_output(self):
        doc = fitz.open()
        page = doc.new_page(width=420, height=320)
        for i in range(14):
            page.insert_text((24, 22 + i * 21), f'Wiersz {i + 1}: Zazolc gesla jazn {"x" * (i % 5)}', fontsize=12 + (i % 3))
        path = os.path.join(tempfile.mkdtemp(), 'lines.png')
        page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72)).save(path)
        service = OCRService()
        expected = service._rapid_raw(path)
        steps = pdf_scan.RapidSteps(service._get_rapid(service.rapid_quality, service.rapid_script))
        scan = steps.detect(path)
        self.assertGreater(len(scan.batches), 1)
        self.assertEqual(len(scan.boxes), len(scan.images))
        for batch in scan.batches:
            steps.recognize(scan, batch)
        self.assertEqual(steps.items(scan), expected)
        self.assertTrue(service._get_rapid(service.rapid_quality, service.rapid_script).use_rec)


if __name__ == '__main__':
    unittest.main()
