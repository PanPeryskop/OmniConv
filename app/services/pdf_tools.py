import os
import re
import threading
import zipfile
from collections import OrderedDict
from typing import Optional, Callable, Dict, Any, List

import fitz


class PdfToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


PAGE_NUMBER_POSITIONS = {
    'top-left', 'top-center', 'top-right',
    'bottom-left', 'bottom-center', 'bottom-right',
}

WATERMARK_COLORS = {
    'gray': (0.5, 0.5, 0.5),
    'black': (0.1, 0.1, 0.1),
    'red': (0.8, 0.1, 0.1),
    'blue': (0.1, 0.3, 0.8),
}

MARGINS = {'small': 18.0, 'normal': 30.0, 'large': 48.0}

LEGACY_NUMBER_FORMATS = {'n': '{n}', 'n_of_total': '{n} / {total}', 'dash': '- {n} -'}

_doc_cache: "OrderedDict[tuple, fitz.Document]" = OrderedDict()
_doc_lock = threading.Lock()


def parse_page_ranges(spec: str, page_count: int) -> List[List[int]]:
    ranges = []
    for part in re.split(r'[,;]', spec or ''):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r'(\d*)\s*-\s*(\d*)', part)
        if match:
            start = int(match.group(1)) if match.group(1) else 1
            end = int(match.group(2)) if match.group(2) else page_count
        elif part.isdigit():
            start = end = int(part)
        else:
            raise PdfToolError('err_pdf_ranges', f"Invalid page range: {part}")
        if start < 1 or end > page_count or start > end:
            raise PdfToolError('err_pdf_ranges', f"Page range out of bounds: {part}")
        ranges.append(list(range(start - 1, end)))
    if not ranges:
        raise PdfToolError('err_pdf_ranges', "No page ranges given")
    return ranges


def selected_pages(spec: Optional[str], page_count: int) -> List[int]:
    if not spec or not str(spec).strip():
        return list(range(page_count))
    seen = set()
    result = []
    for group in parse_page_ranges(str(spec), page_count):
        for i in group:
            if i not in seen:
                seen.add(i)
                result.append(i)
    return sorted(result)


def safe_name(text: str, fallback: str) -> str:
    cleaned = re.sub(r'[^\w\- ]+', '', text or '', flags=re.UNICODE).strip().replace(' ', '_')
    return cleaned[:60] or fallback


class PdfTools:
    def __init__(self, progress_callback: Optional[Callable[[int], None]] = None):
        self.progress_callback = progress_callback
        self.cancelled = False
        self.info_result = None

    def cancel(self):
        self.cancelled = True

    def report_progress(self, progress: float):
        if self.cancelled:
            raise PdfToolError('err_cancelled', "Cancelled")
        if self.progress_callback:
            self.progress_callback(min(100, max(0, int(progress))))

    @staticmethod
    def open(path: str, password: Optional[str] = None) -> fitz.Document:
        try:
            doc = fitz.open(path)
        except Exception:
            raise PdfToolError('err_pdf_damaged', "The PDF could not be opened")
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                doc.close()
                if password:
                    raise PdfToolError('err_pdf_wrong_password', "Wrong password")
                raise PdfToolError('err_pdf_password', "PDF is password protected")
        return doc

    @staticmethod
    def save(doc: fitz.Document, out_path: str, **kwargs):
        doc.save(out_path, garbage=3, deflate=True, use_objstms=1, **kwargs)

    @staticmethod
    def info(path: str) -> Dict[str, Any]:
        try:
            doc = fitz.open(path)
        except Exception:
            raise PdfToolError('err_pdf_damaged', "The PDF could not be opened")
        with doc:
            info = {
                'pages': doc.page_count,
                'encrypted': bool(doc.needs_pass),
                'restricted': bool(doc.is_encrypted) and not doc.needs_pass,
                'size': os.path.getsize(path),
            }
            if doc.needs_pass:
                return info
            meta = doc.metadata or {}
            needed = fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY | fitz.PDF_PERM_MODIFY
            info['restricted'] = bool(meta.get('encryption')) or (doc.permissions & needed) != needed
            info['metadata'] = {key: meta.get(key) or '' for key in ('title', 'author', 'subject', 'keywords')}
            info['has_forms'] = bool(doc.is_form_pdf)
            try:
                info['signed'] = doc.get_sigflags() > 0
            except Exception:
                info['signed'] = False
            info['bookmarks'] = sum(1 for level, *_ in doc.get_toc(simple=True) if level == 1)
            sample = range(min(doc.page_count, 30))
            text_pages = sum(1 for i in sample if doc[i].get_text().strip())
            info['text_ratio'] = round(text_pages / max(1, len(sample)), 2)
            if doc.page_count:
                rect = doc[0].rect
                info['page_width'] = round(rect.width, 1)
                info['page_height'] = round(rect.height, 1)
            return info

    @staticmethod
    def render_page(path: str, index: int, width: int = 200) -> bytes:
        key = (path, os.path.getmtime(path))
        with _doc_lock:
            doc = _doc_cache.get(key)
            if doc is None:
                for stale in [k for k in _doc_cache if k[0] == path]:
                    _doc_cache.pop(stale).close()
                doc = PdfTools.open(path)
                _doc_cache[key] = doc
                while len(_doc_cache) > 6:
                    _doc_cache.popitem(last=False)[1].close()
            else:
                _doc_cache.move_to_end(key)
            if index < 0 or index >= doc.page_count:
                raise PdfToolError('err_pdf_ranges', "Page out of range")
            page = doc[index]
            zoom = max(0.05, min(4.0, width / max(1.0, page.rect.width)))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            return pix.tobytes(output='jpeg', jpg_quality=82)

    def run(self, tool: str, input_paths: List[str], out_base: str, options: Dict[str, Any]) -> str:
        handler = getattr(self, f'tool_{tool}', None)
        if not handler:
            raise PdfToolError('err_generic', f"Unknown tool: {tool}")
        self.report_progress(5)
        result = handler(input_paths, out_base, options or {})
        self.report_progress(100)
        return result

    def tool_organize(self, paths, out_base, options):
        pages = options.get('pages') or []
        if not pages:
            raise PdfToolError('err_pdf_no_pages', "At least one page must remain")
        docs = [self.open(p) for p in paths]
        try:
            main = docs[0]
            simple = all(not item.get('blank') and int(item.get('src', 0)) == 0 for item in pages)
            out_path = out_base + '.pdf'
            if simple:
                indices, rotations = [], []
                for item in pages:
                    index = int(item.get('index', -1))
                    if index < 0 or index >= main.page_count:
                        raise PdfToolError('err_pdf_ranges', "Page out of range")
                    indices.append(index)
                    rotations.append(int(item.get('rotate', 0)) % 360)
                main.select(indices)
                for page, rotate in zip(main, rotations):
                    if rotate:
                        page.set_rotation((page.rotation + rotate) % 360)
                self.save(main, out_path)
                return out_path

            with fitz.open() as out:
                last_rect = main[0].rect if main.page_count else fitz.paper_rect('a4')
                for n, item in enumerate(pages):
                    if item.get('blank'):
                        out.new_page(width=last_rect.width, height=last_rect.height)
                    else:
                        src = int(item.get('src', 0))
                        if src < 0 or src >= len(docs):
                            raise PdfToolError('err_pdf_ranges', "Unknown source document")
                        source = docs[src]
                        index = int(item.get('index', -1))
                        if index < 0 or index >= source.page_count:
                            raise PdfToolError('err_pdf_ranges', "Page out of range")
                        out.insert_pdf(source, from_page=index, to_page=index)
                        page = out[-1]
                        rotate = int(item.get('rotate', 0)) % 360
                        if rotate:
                            page.set_rotation((page.rotation + rotate) % 360)
                        last_rect = page.rect
                    self.report_progress(5 + (n + 1) / len(pages) * 90)
                self.save(out, out_path)
            return out_path
        finally:
            for doc in docs:
                doc.close()

    def tool_split(self, paths, out_base, options):
        mode = options.get('mode', 'every')
        name = os.path.basename(out_base)
        with self.open(paths[0]) as doc:
            labels = None
            if mode == 'every':
                groups = [[i] for i in range(doc.page_count)]
            elif mode == 'every_n':
                n = int(options.get('n') or 0)
                if n < 1:
                    raise PdfToolError('err_pdf_split_n', "Invalid page count")
                groups = [list(range(i, min(i + n, doc.page_count))) for i in range(0, doc.page_count, n)]
            elif mode == 'bookmarks':
                toc = [(page - 1, title) for level, title, page in doc.get_toc(simple=True) if level == 1 and page > 0]
                if not toc:
                    raise PdfToolError('err_pdf_no_bookmarks', "This PDF has no bookmarks")
                starts = sorted({p for p, _ in toc})
                titles = {}
                for p, title in toc:
                    titles.setdefault(p, title)
                if starts[0] != 0:
                    starts.insert(0, 0)
                groups = [list(range(s, (starts[i + 1] if i + 1 < len(starts) else doc.page_count))) for i, s in enumerate(starts)]
                labels = [safe_name(titles.get(g[0], ''), f"{g[0] + 1}-{g[-1] + 1}") for g in groups]
            else:
                groups = parse_page_ranges(options.get('ranges', ''), doc.page_count)
                if mode == 'extract':
                    groups = [[i for group in groups for i in group]]

            if len(groups) == 1:
                out_path = out_base + '.pdf'
                with fitz.open() as part:
                    for i in groups[0]:
                        part.insert_pdf(doc, from_page=i, to_page=i)
                    self.save(part, out_path)
                return out_path

            out_path = out_base + '.zip'
            used = set()
            with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for n, group in enumerate(groups, start=1):
                    with fitz.open() as part:
                        for i in group:
                            part.insert_pdf(doc, from_page=i, to_page=i)
                        label = labels[n - 1] if labels else (f"{group[0] + 1}" if len(group) == 1 else f"{group[0] + 1}-{group[-1] + 1}")
                        filename = f"{name}_{n:02d}_{label}.pdf" if labels else f"{name}_{label}.pdf"
                        while filename in used:
                            filename = filename.replace('.pdf', '_.pdf')
                        used.add(filename)
                        zf.writestr(filename, part.tobytes(garbage=3, deflate=True))
                    self.report_progress(5 + n / len(groups) * 90)
        return out_path

    def tool_merge(self, paths, out_base, options):
        names = options.get('names') or []
        if len(paths) < 2:
            raise PdfToolError('err_pdf_merge_count', "At least two PDFs are needed")
        with fitz.open() as merged:
            toc = []
            for n, path in enumerate(paths):
                with self.open(path) as doc:
                    start = merged.page_count
                    merged.insert_pdf(doc)
                    title = names[n] if n < len(names) and names[n] else os.path.basename(path)
                    toc.append([1, os.path.splitext(title)[0], start + 1])
                self.report_progress(5 + (n + 1) / len(paths) * 85)
            try:
                merged.set_toc(toc)
            except Exception:
                pass
            out_path = out_base + '.pdf'
            self.save(merged, out_path)
        return out_path

    def tool_compress(self, paths, out_base, options):
        from .compressor import PdfCompressor
        compressor = PdfCompressor(lambda p: self.report_progress(5 + p * 0.9))
        mode = options.get('mode', 'balanced')
        if mode not in PdfCompressor.PRESETS and mode != 'target':
            mode = 'balanced'
        try:
            target_mb = float(options.get('target_mb') or 0)
        except (TypeError, ValueError):
            target_mb = 0
        if mode == 'target' and target_mb <= 0:
            raise PdfToolError('err_pdf_target_size', "Target size must be greater than 0")
        out_path = out_base + '.pdf'
        compressor.compress(paths[0], out_path, target_mb, {
            'mode': mode,
            'grayscale': bool(options.get('grayscale')),
            'strip_metadata': bool(options.get('strip_metadata')),
        })
        self.info_result = compressor.info
        return out_path

    def tool_protect(self, paths, out_base, options):
        password = options.get('password') or ''
        if len(password) < 4:
            raise PdfToolError('err_pdf_password_short', "Password must have at least 4 characters")
        require_open = options.get('require_open', True) is not False
        allow_print = options.get('allow_print', True) is not False
        allow_copy = options.get('allow_copy', True) is not False
        allow_edit = options.get('allow_edit', True) is not False
        if not require_open and allow_print and allow_copy and allow_edit:
            raise PdfToolError('err_pdf_protect_nothing', "Nothing to protect")
        permissions = fitz.PDF_PERM_ACCESSIBILITY
        if allow_print:
            permissions |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
        if allow_copy:
            permissions |= fitz.PDF_PERM_COPY
        if allow_edit:
            permissions |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM | fitz.PDF_PERM_ASSEMBLE
        with self.open(paths[0]) as doc:
            out_path = out_base + '.pdf'
            doc.save(out_path, garbage=3, deflate=True,
                     encryption=fitz.PDF_ENCRYPT_AES_256,
                     owner_pw=password, user_pw=password if require_open else '',
                     permissions=permissions)
        return out_path

    def tool_unlock(self, paths, out_base, options):
        password = options.get('password') or ''
        try:
            doc = fitz.open(paths[0])
        except Exception:
            raise PdfToolError('err_pdf_damaged', "The PDF could not be opened")
        with doc:
            if doc.needs_pass and not doc.authenticate(password):
                raise PdfToolError('err_pdf_wrong_password', "Wrong password")
            out_path = out_base + '.pdf'
            doc.save(out_path, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)
        return out_path

    @staticmethod
    def _visual_to_page(page: fitz.Page, point: fitz.Point) -> fitz.Point:
        return point * page.derotation_matrix

    @staticmethod
    def _load_watermark_image(path: str, opacity: float) -> fitz.Pixmap:
        try:
            pix = fitz.Pixmap(path)
        except Exception:
            raise PdfToolError('err_pdf_watermark_image', "The watermark image could not be read")
        if pix.colorspace and pix.colorspace.n not in (1, 3):
            pix = fitz.Pixmap(fitz.csRGB, pix)
        longest = max(pix.width, pix.height)
        if longest > 1600:
            shrink = 0
            while longest >> shrink > 1600:
                shrink += 1
            pix.shrink(shrink)
        if not pix.alpha:
            pix = fitz.Pixmap(pix, 1)
        alpha = pix.samples_mv[pix.n - 1::pix.n]
        pix.set_alpha(bytes(int(a * opacity) for a in alpha))
        return pix

    def tool_watermark(self, paths, out_base, options):
        kind = 'image' if options.get('kind') == 'image' else 'text'
        text = (options.get('text') or '').strip()
        if kind == 'text' and not text:
            raise PdfToolError('err_pdf_watermark_empty', "Watermark text is empty")
        image_path = options.get('image_path')
        if kind == 'image' and not image_path:
            raise PdfToolError('err_pdf_watermark_image', "No watermark image")
        opacity = min(1.0, max(0.05, float(options.get('opacity', 0.2))))
        size_ratio = min(0.3, max(0.02, float(options.get('size', 0.08))))
        position = options.get('position', 'center')
        if position not in ('center', 'top', 'bottom'):
            position = 'center'
        diagonal = bool(options.get('diagonal', True)) and position == 'center'
        overlay = not bool(options.get('behind'))
        color = WATERMARK_COLORS.get(options.get('color'), WATERMARK_COLORS['gray'])
        font = fitz.Font('helv')
        image = self._load_watermark_image(image_path, opacity) if kind == 'image' else None

        with self.open(paths[0]) as doc:
            targets = selected_pages(options.get('pages'), doc.page_count)
            for n, index in enumerate(targets):
                page = doc[index]
                visual = page.rect
                if kind == 'image':
                    width = visual.width * min(0.95, size_ratio * 5)
                    height = width * image.height / max(1, image.width)
                    x0 = (visual.width - width) / 2
                    if position == 'top':
                        y0 = visual.height * 0.05
                    elif position == 'bottom':
                        y0 = visual.height * 0.95 - height
                    else:
                        y0 = (visual.height - height) / 2
                    target = fitz.Rect(x0, y0, x0 + width, y0 + height) * page.derotation_matrix
                    page.insert_image(target, pixmap=image, overlay=overlay, rotate=page.rotation)
                else:
                    fontsize = max(8.0, min(visual.width, visual.height) * size_ratio)
                    text_width = font.text_length(text, fontsize=fontsize)
                    max_width = (visual.width * 0.85) / (0.75 if diagonal else 1.0)
                    if text_width > max_width:
                        fontsize *= max_width / text_width
                        text_width = font.text_length(text, fontsize=fontsize)
                    if position == 'top':
                        center_y = visual.height * 0.06 + fontsize * 0.5
                    elif position == 'bottom':
                        center_y = visual.height * 0.94 - fontsize * 0.5
                    else:
                        center_y = visual.height / 2
                    pivot = self._visual_to_page(page, fitz.Point(visual.width / 2, center_y))
                    origin = fitz.Point(pivot.x - text_width / 2, pivot.y + fontsize * 0.35)
                    writer = fitz.TextWriter(page.rect)
                    writer.append(origin, text, font=font, fontsize=fontsize)
                    angle = ((45 if diagonal else 0) + page.rotation) % 360
                    morph = (pivot, fitz.Matrix(angle)) if angle else None
                    writer.write_text(page, color=color, opacity=opacity, morph=morph, overlay=overlay)
                self.report_progress(5 + (n + 1) / len(targets) * 90)
            out_path = out_base + '.pdf'
            self.save(doc, out_path)
        return out_path

    def tool_page_numbers(self, paths, out_base, options):
        position = options.get('position', 'bottom-center')
        if position not in PAGE_NUMBER_POSITIONS:
            position = 'bottom-center'
        template = str(options.get('template') or LEGACY_NUMBER_FORMATS.get(options.get('format'), '{n}'))[:80]
        if '{n}' not in template:
            raise PdfToolError('err_pdf_numbers_template', "The template must contain {n}")
        start = int(options.get('start', 1) or 0)
        digits = min(12, max(0, int(options.get('digits', 0) or 0)))
        fontsize = min(36.0, max(6.0, float(options.get('font_size', 11))))
        margin = MARGINS.get(options.get('margin'), MARGINS['normal'])
        font = fitz.Font('helv')
        with self.open(paths[0]) as doc:
            spec = options.get('pages')
            if not spec and options.get('skip_first') and doc.page_count > 1:
                spec = '2-'
            targets = selected_pages(spec, doc.page_count)
            total = start + len(targets) - 1

            def number(value):
                return str(value).zfill(digits) if digits else str(value)

            for n, index in enumerate(targets):
                page = doc[index]
                label = template.replace('{total}', number(total)).replace('{n}', number(start + n))
                visual = page.rect
                width = font.text_length(label, fontsize=fontsize)
                vertical, horizontal = position.split('-')
                y = margin + fontsize * 0.8 if vertical == 'top' else visual.height - margin
                if horizontal == 'left':
                    x = margin
                elif horizontal == 'right':
                    x = visual.width - margin - width
                else:
                    x = (visual.width - width) / 2
                origin = self._visual_to_page(page, fitz.Point(x, y))
                writer = fitz.TextWriter(page.rect)
                writer.append(origin, label, font=font, fontsize=fontsize)
                morph = (origin, fitz.Matrix(page.rotation)) if page.rotation else None
                writer.write_text(page, color=(0.2, 0.2, 0.2), morph=morph)
                self.report_progress(5 + (n + 1) / len(targets) * 90)
            out_path = out_base + '.pdf'
            self.save(doc, out_path)
        return out_path

    def tool_metadata(self, paths, out_base, options):
        with self.open(paths[0]) as doc:
            if options.get('strip'):
                doc.set_metadata({})
                doc.del_xml_metadata()
            else:
                meta = dict(doc.metadata or {})
                for key in ('title', 'author', 'subject', 'keywords'):
                    if key in options:
                        meta[key] = str(options.get(key) or '')
                doc.set_metadata(meta)
            out_path = out_base + '.pdf'
            self.save(doc, out_path)
        return out_path

    def tool_extract_images(self, paths, out_base, options):
        min_side = int(options.get('min_side', 32))
        out_path = out_base + '.zip'
        count = 0
        seen = set()
        with self.open(paths[0]) as doc, zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for n, page in enumerate(doc):
                for img in page.get_images(full=True):
                    xref = img[0]
                    if xref in seen:
                        continue
                    seen.add(xref)
                    try:
                        data = doc.extract_image(xref)
                    except Exception:
                        continue
                    if not data or min(data.get('width', 0), data.get('height', 0)) < min_side:
                        continue
                    count += 1
                    zf.writestr(f"image_{count:03d}_page{n + 1}.{data.get('ext', 'png')}", data['image'])
                self.report_progress(5 + (n + 1) / doc.page_count * 90)
        if not count:
            os.remove(out_path)
            raise PdfToolError('err_pdf_no_images', "No images found in this PDF")
        return out_path

    def tool_to_images(self, paths, out_base, options):
        dpi = min(300, max(50, int(options.get('dpi', 150))))
        fmt = 'jpg' if options.get('format') == 'jpg' else 'png'
        name = os.path.basename(out_base)
        with self.open(paths[0]) as doc:
            targets = selected_pages(options.get('pages'), doc.page_count)

            def render(page):
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                return pix.tobytes(output='jpeg', jpg_quality=90) if fmt == 'jpg' else pix.tobytes(output='png')

            if len(targets) == 1:
                out_path = f"{out_base}.{fmt}"
                with open(out_path, 'wb') as f:
                    f.write(render(doc[targets[0]]))
                return out_path

            out_path = out_base + '.zip'
            with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_STORED) as zf:
                for n, index in enumerate(targets):
                    zf.writestr(f"{name}_{index + 1:03d}.{fmt}", render(doc[index]))
                    self.report_progress(5 + (n + 1) / len(targets) * 90)
        return out_path
