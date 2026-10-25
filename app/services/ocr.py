import os
import re
import html
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from .converter import BaseConverter
from ..utils.exceptions import OCRError
from .llm import LLMService

OCR_DPI = 200
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}


class OcrPage:
    def __init__(self, text: str, lines: Optional[list] = None):
        self.text = text or ''
        self.lines = lines or []


def _paragraphs_from_boxes(items) -> str:
    items = sorted(items, key=lambda item: (round(item[2][1] / 10), item[2][0]))
    paragraphs: List[str] = []
    current: List[str] = []
    previous_bottom = previous_height = None
    for text, _, (x0, y0, x1, y1) in items:
        height = y1 - y0
        if previous_bottom is not None and y0 - previous_bottom > max(height, previous_height) * 0.9:
            paragraphs.append('\n'.join(current))
            current = []
        current.append(text)
        previous_bottom, previous_height = y1, height
    if current:
        paragraphs.append('\n'.join(current))
    return '\n\n'.join(paragraphs)


class OCRService(BaseConverter):
    ENGINES = ('rapid', 'qwen')
    DEFAULT_ENGINE = 'rapid'

    _rapid = None
    _rapid_lock = threading.Lock()
    _status_cache = {'at': 0.0, 'data': None}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.llm = LLMService()
        self.info: Dict[str, Any] = {}

    @classmethod
    def engine_status(cls, max_age: float = 20.0) -> Dict[str, Dict[str, Any]]:
        cache = cls._status_cache
        if cache['data'] is not None and time.time() - cache['at'] < max_age:
            return cache['data']

        llm = LLMService()
        status = {}

        try:
            import rapidocr
            status['rapid'] = {'available': True, 'reason': None}
        except ImportError:
            status['rapid'] = {'available': False, 'reason': 'missing_rapidocr'}

        ocr_model = os.environ.get('LLM_OCR_MODEL', 'qwen/qwen3-vl-8b')
        qwen = llm.model_status(ocr_model)
        status['qwen'] = {'available': qwen == 'ok', 'reason': None if qwen == 'ok' else qwen, 'model': ocr_model}


        formatting_model = os.environ.get('LLM_FORMATTING_MODEL', 'ministral-3-8b-instruct-2512')
        correction = llm.model_status(formatting_model)
        status['correction'] = {'available': correction == 'ok', 'reason': None if correction == 'ok' else correction, 'model': formatting_model}


        cache['at'], cache['data'] = time.time(), status
        return status

    def _resolve_engine(self, options: Dict[str, Any]) -> Tuple[str, bool]:
        engine = options.get('ocr_engine') or self.DEFAULT_ENGINE
        if engine not in self.ENGINES:
            raise OCRError(f"Unknown OCR engine: {engine}", code='err_ocr_engine')
        status = self.engine_status()
        info = status[engine]
        if not info['available']:
            raise OCRError(f"OCR engine '{engine}' is not available ({info['reason']})", code=f"err_ocr_{info['reason']}")
        correct = bool(options.get('use_llm'))
        if correct and not status['correction']['available']:
            raise OCRError("AI text correction is not available", code=f"err_ocr_{status['correction']['reason']}")
        return engine, correct

    @classmethod
    def _get_rapid(cls):
        with cls._rapid_lock:
            if cls._rapid is None:
                from rapidocr import RapidOCR
                cls._rapid = RapidOCR()
            return cls._rapid


    def _rapid_raw(self, image_path: str):
        result = self._get_rapid()(image_path)
        boxes = result.boxes if result.boxes is not None else []
        items = []
        for box, text, score in zip(boxes, result.txts or [], result.scores or []):
            text = (text or '').strip()
            if not text:
                continue
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            items.append((text, float(score), (min(xs), min(ys), max(xs), max(ys))))
        return items

    @staticmethod
    def _orientation_quality(items) -> Tuple[float, float]:
        if not items:
            return 0.0, 0.0
        vertical = sum(1 for _, _, (x0, y0, x1, y1) in items if (y1 - y0) > (x1 - x0) * 1.5)
        quality = sum(len(text) * score for text, score, (x0, y0, x1, y1) in items if (x1 - x0) >= (y1 - y0))
        return quality, vertical / len(items)

    def _recognize_rapid(self, image_path: str) -> OcrPage:
        items = self._rapid_raw(image_path)
        return OcrPage(_paragraphs_from_boxes(items), [])

    def _ocr_pdf_page(self, page, engine: str, output_format: str, options: Dict[str, Any], temp_path: str) -> OcrPage:
        import fitz
        zoom = OCR_DPI / 72.0
        if engine != 'rapid':
            page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(temp_path)
            return self.recognize(temp_path, engine, output_format, options)

        best = None
        for angle in (0, 90, 270):
            matrix = fitz.Matrix(zoom, zoom).prerotate(angle)
            pix = page.get_pixmap(matrix=matrix)
            pix.save(temp_path)
            items = self._rapid_raw(temp_path)
            quality, vertical_ratio = self._orientation_quality(items)
            if best is None or quality > best[0]:
                best = (quality, items, matrix, fitz.Point(pix.x, pix.y))
            if angle == 0 and (not items or vertical_ratio < 0.3):
                break

        _, items, matrix, offset = best
        to_page = ~matrix * page.derotation_matrix
        lines = []
        for text, _, (x0, y0, x1, y1) in items:
            height = y1 - y0
            baseline = y1 - height * 0.18
            start = (fitz.Point(x0, baseline) + offset) * to_page
            end = (fitz.Point(x1, baseline) + offset) * to_page
            lines.append((text, start, end, height / zoom))
        return OcrPage(_paragraphs_from_boxes(items), lines)

    def _recognize_llm(self, image_path: str, output_format: str, options: Dict[str, Any]) -> OcrPage:
        prompt = (
            "Transcribe the text from this image exactly as it appears. "
            "Output ONLY plain text. Do NOT use Markdown formatting, do NOT use HTML tags. "
            "Keep paragraphs separated by blank lines."
        )
        if output_format == 'md':
            prompt = (
                "Transcribe the content of this image into well-formatted Markdown. "
                "Use # and ## for headings, - for bullet lists, 1. for numbered lists, **bold**, "
                "| tables | with | pipes | and > for quotes. Output ONLY the raw markdown, no code fences."
            )
        elif output_format == 'html':
            theme = 'a DARK theme (background #1a1a1a, text #e0e0e0)' if options.get('ocr_theme') == 'dark' else 'a LIGHT theme (white background, dark text)'
            css_limit = ''
            if options.get('css_limit_enabled'):
                css_limit = f" Keep the CSS under about {int(options.get('css_limit_value', 1000))} characters."
            prompt = (
                "Transcribe the content of this image into clean, semantic HTML5 (h1, h2, p, ul, table...). "
                f"Add one small <style> block for {theme}.{css_limit} "
                "Do not embed images. Output ONLY the raw HTML."
            )
        try:
            text = self.llm.generate_from_image(image_path, prompt)
        except Exception as e:
            raise OCRError(str(e), code='err_ocr_llm_offline')
        return OcrPage(self._strip_fences(text))


    def recognize(self, image_path: str, engine: str, output_format: str = 'txt', options: Optional[Dict[str, Any]] = None) -> OcrPage:
        options = options or {}
        if engine == 'rapid':
            return self._recognize_rapid(image_path)
        return self._recognize_llm(image_path, output_format, options)

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = (text or '').strip()
        text = re.sub(r'^```[a-zA-Z]*\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        return text.strip()

    def _iter_ocr_pages(self, input_path: str, engine: str, output_format: str, options: Dict[str, Any], temp_dir: str):
        import fitz
        if Path(input_path).suffix.lower() in IMAGE_EXTENSIONS:
            yield 0, 1, self.recognize(input_path, engine, output_format, options)
            return
        with fitz.open(input_path) as doc:
            if doc.needs_pass:
                raise OCRError("PDF is password protected", code='err_pdf_password')
            total = doc.page_count
            for i, page in enumerate(doc):
                if self.is_cancelled:
                    return
                yield i, total, self._ocr_pdf_page(page, engine, output_format, options, os.path.join(temp_dir, f'page_{i}.png'))

    def _recognize_document(self, input_path: str, output_format: str, options: Dict[str, Any]) -> List[str]:
        engine, correct = self._resolve_engine(options)
        temp_dir = tempfile.mkdtemp(prefix='ocr_')
        texts = []
        try:
            for i, total, page in self._iter_ocr_pages(input_path, engine, output_format, options, temp_dir):
                if self.is_cancelled:
                    return []
                text = page.text
                if correct and output_format != 'html':
                    text = self.llm.correct_text(text, output_format)
                texts.append(text)
                self.report_progress(5 + int((i + 1) / total * 85))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        self.info = {'engine': engine, 'correction': correct, 'pages': len(texts)}
        if not any(t.strip() for t in texts):
            raise OCRError("No text was recognized", code='err_ocr_no_text')
        return texts

    def get_text_from_image(self, input_path: str, lang: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> str:
        return '\n\n'.join(self._recognize_document(input_path, 'txt', options or {}))

    def _html_document(self, pages: List[str], options: Dict[str, Any], engine_html: bool) -> str:
        dark = options.get('ocr_theme') == 'dark'
        if engine_html:
            styles = []
            bodies = []
            for page in pages:
                styles.extend(re.findall(r'<style[^>]*>(.*?)</style>', page, flags=re.S | re.I))
                body = re.search(r'<body[^>]*>(.*?)</body>', page, flags=re.S | re.I)
                content = body.group(1) if body else re.sub(r'</?(html|head|body)[^>]*>|<!DOCTYPE[^>]*>|<style[^>]*>.*?</style>|<title>.*?</title>|<meta[^>]*>', '', page, flags=re.S | re.I)
                bodies.append(f'<section class="page">{content.strip()}</section>')
            style = styles[0] if styles else ''
        else:
            bodies = []
            for page in pages:
                paragraphs = ''.join(f'<p>{html.escape(p).replace(chr(10), "<br>")}</p>' for p in page.split('\n\n') if p.strip())
                bodies.append(f'<section class="page">{paragraphs}</section>')
            style = ''
        base_style = (
            f"body{{font-family:system-ui,sans-serif;max-width:820px;margin:40px auto;padding:0 20px;line-height:1.6;"
            f"background:{'#1a1a1a' if dark else '#fff'};color:{'#e0e0e0' if dark else '#1a1a1a'}}}"
            f".page+.page{{border-top:1px solid {'#333' if dark else '#ddd'};margin-top:32px;padding-top:32px}}"
        )
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>OCR</title>'
            f'<style>{base_style}{style}</style></head><body>{"".join(bodies)}</body></html>'
        )

    def _write_docx(self, pages: List[str], output_path: str):
        from docx import Document
        from docx.enum.text import WD_BREAK
        document = Document()
        for n, page in enumerate(pages):
            for paragraph in page.split('\n\n'):
                if paragraph.strip():
                    document.add_paragraph(paragraph.strip())
            if n < len(pages) - 1:
                document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        document.save(output_path)

    def _make_searchable_pdf(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import fitz
        engine, correct = self._resolve_engine(options)
        force = bool(options.get('ocr_force'))
        font = fitz.Font('helv')
        ext = Path(input_path).suffix.lower()

        if ext in IMAGE_EXTENSIONS:
            with fitz.open(input_path) as img:
                doc = fitz.open('pdf', img.convert_to_pdf())
        else:
            doc = fitz.open(input_path)
            if doc.needs_pass:
                doc.close()
                raise OCRError("PDF is password protected", code='err_pdf_password')

        temp_dir = tempfile.mkdtemp(prefix='ocr_pdf_')
        recognized = skipped = 0
        try:
            total = doc.page_count
            for i, page in enumerate(doc):
                if self.is_cancelled:
                    return None
                if not force and page.get_text().strip():
                    skipped += 1
                    self.report_progress(5 + int((i + 1) / total * 90))
                    continue
                result = self._ocr_pdf_page(page, engine, 'txt', options, os.path.join(temp_dir, f'page_{i}.png'))
                if result.lines:
                    self._place_lines(page, result.lines, font)
                elif result.text.strip():
                    text = self.llm.correct_text(result.text, 'txt') if correct else result.text
                    self._place_block(page, text, font)
                recognized += 1
                self.report_progress(5 + int((i + 1) / total * 90))
            doc.save(output_path, garbage=3, deflate=True)
        finally:
            doc.close()
            shutil.rmtree(temp_dir, ignore_errors=True)
        self.info = {'engine': engine, 'pages_ocr': recognized, 'pages_skipped': skipped}
        return output_path

    @staticmethod
    def _place_lines(page, lines, font):
        import math
        import fitz
        for text, start, end, height in lines:
            dx, dy = end.x - start.x, end.y - start.y
            width = math.hypot(dx, dy)
            if width <= 0 or height <= 0:
                continue
            fontsize = height * 0.85
            length = font.text_length(text, fontsize=fontsize)
            if length > 0:
                fontsize = max(height * 0.4, min(height * 1.3, fontsize * width / length))
            angle = math.degrees(math.atan2(dy, dx))
            writer = fitz.TextWriter(page.rect)
            writer.append(start, text, font=font, fontsize=fontsize)
            morph = (start, fitz.Matrix(-angle)) if abs(angle) > 0.5 else None
            writer.write_text(page, render_mode=3, morph=morph)

    @staticmethod
    def _place_block(page, text, font):
        import fitz
        rect = fitz.Rect(page.rect * page.derotation_matrix).normalize() + (24, 24, -24, -24)
        for fontsize in (10, 8, 6, 4, 3):
            writer = fitz.TextWriter(page.rect)
            overflow = writer.fill_textbox(rect, text, font=font, fontsize=fontsize)
            if not overflow or fontsize == 3:
                writer.write_text(page, render_mode=3)
                return

    def convert(self, input_path: str, output_path: str, output_format: str, options: Optional[Dict[str, Any]] = None) -> str:
        options = options or {}
        output_format = output_format.lower()
        if output_format.startswith('ocr-'):
            output_format = output_format[4:]
        if output_format == 'pdf_ocr':
            output_format = 'pdf'

        self.report_progress(3)
        if output_format == 'pdf':
            result = self._make_searchable_pdf(input_path, output_path, options)
            self.report_progress(100)
            return result

        pages = self._recognize_document(input_path, output_format, options)
        if self.is_cancelled:
            return None
        engine, correct = self.info.get('engine'), self.info.get('correction')

        if output_format == 'docx':
            self._write_docx(pages, output_path)
        elif output_format == 'html':
            if engine in ('qwen',):
                content = self._html_document(pages, options, engine_html=True)
            elif correct:
                css_limit = int(options.get('css_limit_value', 1000)) if options.get('css_limit_enabled') else None
                content = self._strip_fences(self.llm.generate_html('\n\n'.join(pages), options.get('ocr_theme', 'light'), css_limit))
            else:
                content = self._html_document(pages, options, engine_html=False)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
        else:
            separator = '\n\n---\n\n' if output_format == 'md' else '\n\n'
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(separator.join(pages))

        self.report_progress(100)
        return output_path

    @staticmethod
    def get_supported_input_formats() -> set:
        return {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff', 'tif', 'pdf'}

    @staticmethod
    def get_supported_output_formats() -> set:
        return {'txt', 'md', 'html', 'ocr-txt', 'ocr-md', 'ocr-html', 'docx', 'ocr-docx', 'pdf', 'ocr-pdf'}
