import contextvars
import hashlib
import importlib
import os
import shutil
import tempfile
import threading
import time
import unicodedata
from collections import OrderedDict
from types import SimpleNamespace

import cv2
import fitz
import numpy as np
from flask import g, has_request_context

from ..utils.client import client_id
from .editor_tasks import FINAL, TASKS
from .font_match import family_key
from .ocr import OCRService

ZOOM = 2
INK_DISTANCE = 60
RESIDUE_DISTANCE = 24
SHAPE_CANDIDATES = (
    'Liberation Sans', 'Liberation Serif', 'Liberation Mono', 'Carlito', 'Caladea', 'DejaVu Sans', 'DejaVu Serif',
    'Arial', 'Times New Roman', 'Calibri', 'Cambria', 'Georgia', 'Verdana', 'Courier New',
)
GENERIC = (('Helvetica', 'helv', 'sans'), ('Times', 'tiro', 'serif'), ('Courier', 'cour', 'mono'))


RENDERED, ORIENTING, DETECTED, RECOGNIZED, PLACING, LAYING, MATCHING = 0.06, 0.08, 0.15, 0.85, 0.9, 0.93, 0.96
HANDOFF_TTL = 600
ATTEMPT = contextvars.ContextVar('ocr_attempt', default='')


class OcrPending(Exception):
    def __init__(self, task_id=None):
        super().__init__(task_id)
        self.task_id = task_id


class OcrProgress:
    def __init__(self, task_id=None, page=None, attempt=''):
        self.task_id = task_id
        self.attempt = attempt
        self.size = [round(page.rect.width, 2), round(page.rect.height, 2)] if page is not None else None
        self.view = page.rotation_matrix if page is not None else fitz.Identity
        self.value = 0.0
        self.started = None
        self.at = time.time()

    def task(self):
        return TASKS.get(self.task_id) if self.task_id else None

    def cancelled(self):
        task = self.task()
        return bool(task and task.cancelled)

    def update(self, stage, progress, **detail):
        task = self.task()
        if not task or task.status in FINAL:
            return
        self.value = max(self.value, progress)
        self.at = time.time()
        TASKS.update(self.task_id, stage=stage, progress=round(self.value, 4), detail={**task.detail, **detail})

    def queue(self):
        task = self.task()
        if task and task.status not in FINAL:
            TASKS.update(self.task_id, status='queued')

    def rendered(self, done, total):
        self.update('render', RENDERED * done / total, done=done, total=total)

    def detected(self, boxes, batches):
        self.started = time.time()
        self.update('detect', DETECTED, boxes=boxes, size=self.size, done=0, total=batches, lines=0)

    def recognized(self, done, total, lines):
        elapsed = time.time() - self.started
        eta = round(elapsed / done * (total - done), 1) if done else None
        self.update('recognize', DETECTED + (RECOGNIZED - DETECTED) * done / max(total, 1), done=done, total=total, lines=lines, eta_s=eta)

    def finish(self, status='done', error=None):
        task = self.task()
        if task and task.status not in FINAL:
            TASKS.finish(self.task_id, status, error)


class Silent(OcrProgress):
    def update(self, stage, progress, **detail):
        pass


def ocr_steps():
    name = os.environ.get('PE_OCR_STEPS')
    if name:
        return importlib.import_module(name).steps()
    service = OCRService()
    return RapidSteps(service._get_rapid(service.rapid_quality, service.rapid_script))


class RapidSteps:
    def __init__(self, engine):
        self.engine = engine

    def detect(self, path):
        from rapidocr.ch_ppocr_cls import TextClsOutput
        from rapidocr.main import RapidOCRError
        from rapidocr.utils.process_img import map_boxes_to_original
        engine = self.engine
        original = engine.load_img(OCRService._padded_image(path))
        image, record = engine.preprocess_img(original)
        scan = SimpleNamespace(original=original, record=record, boxes=[], batches=[], texts={}, scores={}, words={})
        try:
            scan.crops, scan.det = engine.detect_and_crop(image, record)
            scan.images, scan.cls = engine.cls_and_rotate(scan.crops) if engine.use_cls else (scan.crops, TextClsOutput())
        except RapidOCRError:
            return scan
        height, width = original.shape[:2]
        mapped = map_boxes_to_original(np.array(scan.det.boxes, dtype=float), dict(record), height, width)
        scan.boxes = [(float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 0].max()), float(b[:, 1].max())) for b in mapped]
        order = np.argsort(np.array([img.shape[1] / float(img.shape[0]) for img in scan.images]))
        size = engine._load_rec_model().rec_batch_num
        scan.batches = [order[i:i + size].tolist() for i in range(0, len(order), size)]
        return scan

    def recognize(self, scan, batch):
        result = self.engine.recognize_txt([scan.images[i] for i in batch])
        for index, text, score, words in zip(batch, result.txts, result.scores, result.word_results, strict=True):
            scan.texts[index], scan.scores[index], scan.words[index] = text, score, words

    def items(self, scan):
        from rapidocr.ch_ppocr_rec import TextRecOutput
        if not scan.batches:
            return []
        indexes = range(len(scan.images))
        rec = TextRecOutput(
            imgs=scan.images, txts=tuple(scan.texts[i] for i in indexes), scores=tuple(scan.scores[i] for i in indexes),
            word_results=tuple(scan.words[i] for i in indexes),
        )
        return raw_items(self.engine.build_final_output(scan.original, scan.det, scan.cls, rec, scan.crops, scan.record))


def raw_items(result):
    items = []
    for box, text, score in zip(result.boxes if result.boxes is not None else [], result.txts or [], result.scores or []):
        text = (text or '').strip()
        if text:
            xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
            items.append((text, float(score), (min(xs), min(ys), max(xs), max(ys))))
    return items


def render_orientations(page, folder, done=None):
    service = OCRService()
    zoom = service.rapid_dpi / 72.0
    renders = []
    for angle in (0, 90, 270):
        matrix = fitz.Matrix(zoom, zoom).prerotate(angle)
        pix = page.get_pixmap(matrix=matrix)
        path = os.path.join(folder, f'page_{angle}.png')
        pix.save(path)
        renders.append((path, ~matrix * page.derotation_matrix, fitz.Point(pix.x, pix.y), zoom))
        if done:
            done(len(renders), 3)
    return renders


def page_boxes(boxes, render, view):
    _path, to_page, offset, _zoom = render
    shift = (offset.x, offset.y, offset.x, offset.y)
    return [[round(v, 1) for v in (fitz.Rect(box) + shift) * to_page * view] for box in boxes]


def scan_render(steps, render, progress, shown):
    scan = steps.detect(render[0])
    total = len(scan.batches)
    if shown:
        progress.detected(page_boxes(scan.boxes, render, progress.view), total)
    lines = 0
    for done, batch in enumerate(scan.batches, 1):
        if progress.cancelled():
            return None
        steps.recognize(scan, batch)
        lines += len(batch)
        if shown:
            progress.recognized(done, total, lines)
    return None if progress.cancelled() else steps.items(scan)


def recognize_renders(renders, progress=None):
    progress = progress or Silent()
    steps = ocr_steps()
    best = None
    for index, render in enumerate(renders):
        progress.update('orientation', ORIENTING if index == 0 else RECOGNIZED + (PLACING - RECOGNIZED) * (index - 1) / 2)
        items = scan_render(steps, render, progress, index == 0)
        if items is None:
            return None
        quality, vertical = OCRService._orientation_quality(items)
        if best is None or quality > best[0]:
            best = (quality, items, render)
        if index == 0 and (not items or vertical < 0.3):
            break
    _quality, items, (_path, to_page, offset, zoom) = best
    return OCRService._page_lines(items, to_page, offset, zoom)


def recognize_with(renders, progress):
    return recognize_renders(renders, progress) if progress.task_id else recognize_renders(renders)


def start_task(page):
    if not has_request_context():
        return None
    return TASKS.create(client_id(), 'ocr', getattr(g, 'edit_file_id', None), page.number).id


class OcrCache:
    def __init__(self, limit=32):
        self.limit = limit
        self.items = OrderedDict()
        self.pending = set()
        self.tasks = {}
        self.handoffs = {}
        self.dropped = set()
        self.lock = threading.Lock()
        self.busy = threading.Lock()

    @staticmethod
    def key(page):
        return (page.parent.name, page.number, hashlib.blake2b(page.read_contents(), digest_size=16).digest())

    def store(self, key, lines):
        with self.lock:
            self.items[key] = lines
            self.pending.discard(key)
            while len(self.items) > self.limit:
                self.items.popitem(last=False)

    def drop(self, key, progress):
        with self.lock:
            self.pending.discard(key)
            self.tasks.pop(key, None)
            self.dropped.add((key, progress.attempt))
        progress.finish('cancelled')

    def is_dropped(self, page, attempt):
        with self.lock:
            return (self.key(page), attempt) in self.dropped

    def hand_off(self, key, progress):
        with self.lock:
            self.tasks.pop(key, None)
            if progress.task_id:
                self.handoffs[key] = progress
        progress.update('layout', PLACING)

    def take_handoff(self, page):
        with self.lock:
            return self.handoffs.pop(self.key(page), None)

    def expire(self):
        with self.lock:
            stale = [k for k, p in self.handoffs.items() if time.time() - p.at > HANDOFF_TTL]
            expired = [self.handoffs.pop(k) for k in stale]
        for progress in expired:
            progress.finish()

    def adopt(self, key):
        with self.lock:
            task = TASKS.get(self.tasks.get(key)) if key in self.tasks else None
        if not task or not has_request_context() or task.owner != client_id():
            return None
        if task.file_id is None and getattr(g, 'edit_file_id', None):
            TASKS.update(task.id, file_id=g.edit_file_id)
        return task.id

    def run(self, key, folder, renders, progress):
        try:
            if self.busy.locked():
                progress.queue()
            with self.busy:
                lines = None if progress.cancelled() else recognize_with(renders, progress)
        except Exception as error:
            lines = []
            progress.finish('failed', {'code': 'err_ocr_failed', 'message': str(error)})
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        if lines is None:
            self.drop(key, progress)
            return
        self.store(key, lines)
        self.hand_off(key, progress)

    def wait_for(self, key, page):
        while True:
            time.sleep(0.5)
            with self.lock:
                if key in self.items:
                    return self.items[key]
                if key not in self.pending:
                    break
        return self.lines(page, True)

    def lines(self, page, wait=True):
        key = self.key(page)
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
            running = key in self.pending
            if not running:
                self.pending.add(key)
        if running:
            if not wait:
                raise OcrPending(self.adopt(key))
            return self.wait_for(key, page)
        self.expire()
        progress = OcrProgress(None if wait else start_task(page), page, ATTEMPT.get())
        if progress.task_id:
            with self.lock:
                self.tasks[key] = progress.task_id
        folder = tempfile.mkdtemp(prefix='pe_ocr_')
        renders = render_orientations(page, folder, progress.rendered)
        if not wait:
            threading.Thread(target=self.run, args=(key, folder, renders, progress), daemon=True).start()
            raise OcrPending(progress.task_id)
        self.run(key, folder, renders, progress)
        with self.lock:
            return self.items.get(key, [])


OCR = OcrCache()


def recognize(page, wait=True, attempt=None):
    attempt = '' if attempt is None else str(attempt)
    if OCR.is_dropped(page, attempt):
        return None
    token = ATTEMPT.set(attempt)
    try:
        found = OCR.lines(page, wait)
    finally:
        ATTEMPT.reset(token)
    handoff = None if wait else OCR.take_handoff(page)
    if handoff:
        handoff.update('layout', LAYING)
    lines = [(unicodedata.normalize('NFKC', text), *rest) for text, *rest in found]
    if lines:
        OCRService._place_lines(page, lines, fitz.Font('helv'))
    return handoff


def raster(page, clip=None):
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=clip, alpha=False, colorspace=fitz.csRGB)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()


def background(pixels):
    edge = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    return np.median(edge, axis=0)


def ink_mask(pixels, base=None, distance=INK_DISTANCE):
    base = background(pixels) if base is None else base
    return (np.abs(pixels.astype(np.int16) - base.astype(np.int16)).max(axis=2) > distance).astype(np.uint8)


def ink_color(pixels):
    distance = np.abs(pixels.astype(np.int16) - background(pixels).astype(np.int16)).max(axis=2)
    ink = distance > INK_DISTANCE
    if ink.sum() < 4:
        return None
    core = distance >= np.percentile(distance[ink], 75)
    color = np.median(pixels[core & ink], axis=0)
    return '#{:02x}{:02x}{:02x}'.format(*[int(v) for v in color])


def crop(pixels, rect, origin=(0, 0)):
    x0, y0, x1, y1 = [int(round((v - o) * ZOOM)) for v, o in zip(rect, origin * 2, strict=True)]
    height, width = pixels.shape[:2]
    return pixels[max(0, y0):min(height, y1), max(0, x0):min(width, x1)]


def inpaint(page, area, before, rects):
    pixels = np.frombuffer(before.samples, dtype=np.uint8).reshape(before.height, before.width, before.n)[:, :, :3].copy()
    region = np.zeros(pixels.shape[:2], dtype=np.uint8)
    scale = before.width / max(area.width, 1)
    for rect in rects:
        x0, y0 = int((rect.x0 - area.x0) * scale) - 2, int((rect.y0 - area.y0) * scale) - 2
        x1, y1 = int((rect.x1 - area.x0) * scale) + 2, int((rect.y1 - area.y0) * scale) + 2
        region[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 1
    mask = ink_mask(pixels, distance=RESIDUE_DISTANCE) & region
    if not mask.any():
        return False
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=3)
    restored = cv2.inpaint(cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR), mask * 255, 3, cv2.INPAINT_TELEA)
    ok, png = cv2.imencode('.png', restored)
    if not ok:
        return False
    page.insert_image(area, stream=png.tobytes(), keep_proportion=False, overlay=True)
    return True


def tight(mask):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def rendered_mask(font, text):
    size = 48
    width = font.text_length(text, fontsize=size) + size
    with fitz.open() as doc:
        page = doc.new_page(width=width, height=size * 2)
        writer = fitz.TextWriter(page.rect)
        writer.append((size / 2, size * 1.4), text, font=font, fontsize=size)
        writer.write_text(page)
        pixels = raster(page)
    return tight(ink_mask(pixels, np.array([255, 255, 255])))


def similarity(target, candidate):
    if target is None or candidate is None:
        return 0.0
    resized = cv2.resize(candidate, (target.shape[1], target.shape[0]), interpolation=cv2.INTER_AREA) > 0
    wanted = target > 0
    union = np.logical_or(wanted, resized).sum()
    return float(np.logical_and(wanted, resized).sum() / union) if union else 0.0


def candidate_fonts(library):
    found = []
    if library.ready.is_set() or library.entries is not None:
        for name in SHAPE_CANDIDATES:
            entry = library.styled(family_key(name), False, False)
            font = library.font(entry) if entry else None
            if font:
                found.append((entry['family'], font, entry['kind']))
    found += [(name, fitz.Font(code), kind) for name, code, kind in GENERIC]
    return found


def match_scan_font(page, words, library, pixels=None):
    samples = sorted((w for w in words if len(w[4]) >= 4 and w[4].isalpha() and w[4].isascii()), key=lambda w: -(w[2] - w[0]))[:5]
    if not samples:
        return None
    pixels = raster(page) if pixels is None else pixels
    targets = [(w[4], tight(ink_mask(crop(pixels, w[:4])))) for w in samples]
    best, score = None, 0.0
    for name, font, kind in candidate_fonts(library):
        usable = [(text, target) for text, target in targets if all(font.has_glyph(ord(c)) for c in text)]
        if len(usable) < len(targets) / 2:
            continue
        value = sum(similarity(target, rendered_mask(font, text)) for text, target in usable) / len(usable)
        if value > score:
            best, score = (name, kind), value
    return best
