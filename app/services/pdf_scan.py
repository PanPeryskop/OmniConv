import hashlib
import os
import shutil
import tempfile
import threading
import time
import unicodedata
from collections import OrderedDict

import cv2
import fitz
import numpy as np

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


class OcrPending(Exception):
    pass


def render_orientations(page, folder):
    service = OCRService()
    zoom = service.rapid_dpi / 72.0
    renders = []
    for angle in (0, 90, 270):
        matrix = fitz.Matrix(zoom, zoom).prerotate(angle)
        pix = page.get_pixmap(matrix=matrix)
        path = os.path.join(folder, f'page_{angle}.png')
        pix.save(path)
        renders.append((path, ~matrix * page.derotation_matrix, fitz.Point(pix.x, pix.y), zoom))
    return renders


def recognize_renders(renders):
    service = OCRService()
    best = None
    for index, (path, to_page, offset, zoom) in enumerate(renders):
        items = service._rapid_raw(path)
        quality, vertical = service._orientation_quality(items)
        if best is None or quality > best[0]:
            best = (quality, items, to_page, offset, zoom)
        if index == 0 and (not items or vertical < 0.3):
            break
    _quality, items, to_page, offset, zoom = best
    return service._page_lines(items, to_page, offset, zoom)


class OcrCache:
    def __init__(self, limit=32):
        self.limit = limit
        self.items = OrderedDict()
        self.pending = set()
        self.lock = threading.Lock()
        self.busy = threading.Lock()

    def store(self, key, lines):
        with self.lock:
            self.items[key] = lines
            self.pending.discard(key)
            while len(self.items) > self.limit:
                self.items.popitem(last=False)

    def run(self, key, folder, renders):
        try:
            with self.busy:
                lines = recognize_renders(renders)
        except Exception:
            lines = []
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.store(key, lines)

    def lines(self, page, wait=True):
        key = (page.parent.name, page.number, hashlib.blake2b(page.read_contents(), digest_size=16).digest())
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
            running = key in self.pending
            if not running:
                self.pending.add(key)
        if running:
            if not wait:
                raise OcrPending()
            while True:
                time.sleep(0.5)
                with self.lock:
                    if key in self.items:
                        return self.items[key]
        folder = tempfile.mkdtemp(prefix='pe_ocr_')
        renders = render_orientations(page, folder)
        if not wait:
            threading.Thread(target=self.run, args=(key, folder, renders), daemon=True).start()
            raise OcrPending()
        self.run(key, folder, renders)
        with self.lock:
            return self.items.get(key, [])


OCR = OcrCache()


def recognize(page, wait=True):
    lines = [(unicodedata.normalize('NFKC', text), *rest) for text, *rest in OCR.lines(page, wait)]
    if lines:
        OCRService._place_lines(page, lines, fitz.Font('helv'))
    return bool(lines)


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
