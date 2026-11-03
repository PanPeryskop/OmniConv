import base64
import hashlib
import json
import os
import re
import statistics
import threading
from collections import Counter, OrderedDict

import fitz
import pymupdf.mupdf as mupdf
from pymupdf import _make_PdfFilterOptions

from . import pdf_scan, pdf_tags, shaping
from .font_match import FontLibrary, family_key, pdf_font_profile
from .pdf_search import MAX_MATCHES, search_page
from .web_fonts import web_font_bytes

GENERIC_FONTS = {
    'sans': ('helv', 'hebo', 'heit', 'hebi'),
    'serif': ('tiro', 'tibo', 'tiit', 'tibi'),
    'mono': ('cour', 'cobo', 'coit', 'cobi'),
}
SUBSET_RE = re.compile(r'^[A-Z]{6}\+')
STYLE_RE = re.compile(r'[-,_ ]?(bold|black|heavy|semibold|demibold|italic|oblique|regular|roman|medium|book|mt|ps)+$', re.I)
BULLETS = set('•▪◦●○■□–-*·➢✓✔►▶➤◆◇')
MARKUP_KINDS = ('highlight', 'underline', 'strikeout', 'squiggly')
MOVABLE_ANNOTS = {'FreeText', 'Square', 'Circle', 'Text', 'Stamp', 'FileAttachment'}
WIDGET_TYPES = {
    fitz.PDF_WIDGET_TYPE_TEXT: 'text',
    fitz.PDF_WIDGET_TYPE_CHECKBOX: 'checkbox',
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON: 'radio',
    fitz.PDF_WIDGET_TYPE_COMBOBOX: 'combo',
    fitz.PDF_WIDGET_TYPE_LISTBOX: 'list',
}
KEEP_GRAPHICS = dict(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)


def hex_color(value):
    if isinstance(value, (list, tuple)):
        value = (round(value[0] * 255) << 16) + (round(value[1] * 255) << 8) + round(value[2] * 255)
    return f'#{int(value or 0) & 0xFFFFFF:06x}'


def rgb(value, default=(0, 0, 0)):
    if not value or not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        return default
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def rect_of(value):
    return fitz.Rect(*[float(v) for v in value[:4]])


def bare_name(name):
    return SUBSET_RE.sub('', name or '')


def family_of(name):
    return STYLE_RE.sub('', bare_name(name)).lower()


def style_of(name, flags=0):
    lower = bare_name(name).lower()
    bold = bool(flags & 16) or any(w in lower for w in ('bold', 'black', 'heavy', 'semibold', 'demibold'))
    italic = bool(flags & 2) or 'italic' in lower or 'oblique' in lower
    return bold, italic


def kind_of(name, flags=0):
    lower = bare_name(name).lower()
    if flags & 8 or any(w in lower for w in ('mono', 'courier', 'consol', 'code')):
        return 'mono'
    if 'sans' in lower:
        return 'sans'
    if flags & 4 or any(w in lower for w in ('times', 'serif', 'georgia', 'garamond', 'cambria', 'roman', 'book')) and 'sans' not in lower:
        return 'serif'
    return 'sans'


class EditContext:
    def __init__(self, doc, library=None, wait=True):
        self.doc = doc
        self.wait = wait
        self.library = library or FontLibrary.shared()
        self.original_xrefs = doc.xref_length()
        self.origins = {}
        self.chars = {}
        self.profiles = {}
        self.matches = {}
        self.overflow = {}
        self.current = None
        self.programs = {}
        self.scan_fonts = {}

    def scan_font(self, page, pixels=None):
        if page.number not in self.scan_fonts:
            try:
                self.scan_fonts[page.number] = pdf_scan.match_scan_font(page, page.get_text('words'), self.library, pixels)
            except Exception:
                self.scan_fonts[page.number] = None
        return self.scan_fonts[page.number]

    def program(self, xref):
        if xref not in self.programs:
            self.programs[xref] = (None, None)
            try:
                _name, ext, _type, buffer = self.doc.extract_font(xref)
                if buffer and ext != 'n/a':
                    self.programs[xref] = (fitz.Font(fontbuffer=buffer), hashlib.blake2b(buffer, digest_size=16).digest())
            except Exception:
                pass
        return self.programs[xref]

    def profile(self, xref):
        if xref not in self.profiles:
            try:
                self.profiles[xref] = pdf_font_profile(self.doc, xref)
            except Exception:
                self.profiles[xref] = None
        return self.profiles[xref]

    def fonts_ready(self):
        return self.wait or self.library.ready.is_set()

    def cover(self, char, kind):
        return self.library.cover(char, kind) if self.fonts_ready() else None

    def match(self, xref, bold, italic, need=''):
        profile = self.profile(xref)
        if not profile or not self.fonts_ready():
            return None, None
        polish = any(ord(c) > 0xFF for c in need)
        key = (xref, bold, italic, polish)
        if key not in self.matches:
            styled = dict(profile, bold=bold, italic=italic, weight=700 if bold else 400)
            self.matches[key] = self.library.match(styled, need)
        return self.matches[key]

    def web_names(self, xref):
        profile = self.profile(xref)
        if not profile:
            return []
        names = [profile.get('family'), profile.get('name_family')]
        if self.library.ready.is_set():
            entry, _quality = self.match(xref, profile['bold'], profile['italic'])
            if entry:
                names.append(entry['family'])
        return [n for n in dict.fromkeys(names) if n]

    def picker(self, page):
        return FontPicker(self, page)

    def stable_font(self, xref):
        if not xref:
            return 0
        if xref < self.original_xrefs:
            return xref
        return self.origins.get(xref, 0)


def prepare_page(page):
    if page.rotation:
        page.remove_rotation()


def page_fonts(page):
    return [(bare_name(basefont), xref, bool(SUBSET_RE.match(basefont))) for xref, _e, _t, basefont, *_ in page.get_fonts(full=True) if xref and basefont]


def font_key(name):
    return re.sub(r'(?<=.)regular$', '', re.sub(r'[^a-z0-9]', '', bare_name(name).lower()))


def font_lookup(fonts):
    lookup = {}
    for name, xref, _subset in fonts:
        lookup.setdefault(font_key(name), xref)
    return lookup


def is_bullet(spans):
    if len(spans) < 2:
        return False
    text = spans[0]['text'].strip()
    return len(text) == 1 and (0xF000 <= ord(text) <= 0xF0FF or text in BULLETS)


def line_break_after(line, next_line, right):
    text = ''.join(s['text'] for s in line['spans']).rstrip()
    if not next_line or not text or next_line['bullet'] or all(kind_of(s['font'], s['flags']) == 'mono' for s in line['spans']):
        return True
    first = next(iter(''.join(s['text'] for s in next_line['spans']).split()), '')
    size = max(s['size'] for s in next_line['spans'])
    return right - line['bbox'][2] > len(first) * size * 0.55 + size * 0.5


def guess_align(lines, bbox, page_width):
    if len(lines) < 2:
        centered = abs((bbox.x0 + bbox.x1) / 2 - page_width / 2) < page_width * 0.03
        if centered and bbox.width < page_width * 0.85:
            return 'center'
        return 'right' if page_width - bbox.x1 < bbox.x0 * 0.5 else 'left'
    lefts = [l['bbox'][0] - bbox.x0 for l in lines]
    rights = [bbox.x1 - l['bbox'][2] for l in lines]
    if max(lefts) < 2:
        return 'justify' if len(lines) > 2 and max(rights[:-1]) < 2 else 'left'
    if max(rights) < 2:
        return 'right'
    if all(abs(a - b) < 3 for a, b in zip(lefts, rights)):
        return 'center'
    return 'left'


def collapse_tracking(span):
    chars = span['chars']
    text = ''.join(c['c'] for c in chars)
    letters = [c for c in text if not c.isspace()]
    if len(letters) < 4 or not re.fullmatch(r'(?:\S {1,3})+\S? *', text):
        span['text'] = text
        return
    kept = []
    for i, char in enumerate(chars):
        if char['c'] != ' ':
            kept.append(char)
        elif i + 1 < len(chars) and chars[i + 1]['c'] == ' ' and (not kept or kept[-1]['c'] != ' '):
            kept.append(char)
    span['chars'] = kept
    span['text'] = ''.join(c['c'] for c in kept)


def raw_lines(page):
    blocks = []
    for block in page.get_text('rawdict', flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP)['blocks']:
        if block['type'] != 0:
            continue
        lines = []
        for line in block['lines']:
            for span in line['spans']:
                collapse_tracking(span)
            spans = [s for s in line['spans'] if s['text']]
            if not spans or not ''.join(s['text'] for s in spans).strip() or tuple(line['dir']) != (1.0, 0.0):
                continue
            bullet = is_bullet(spans)
            if bullet:
                spans = spans[1:]
                while spans and not spans[0]['text'].strip():
                    spans = spans[1:]
            if spans:
                bbox = fitz.Rect(spans[0]['bbox'])
                for span in spans[1:]:
                    bbox |= fitz.Rect(span['bbox'])
                lines.append({'bbox': tuple(bbox), 'spans': spans, 'bullet': bullet})
        if lines:
            blocks.append(lines)
    return blocks


def aligned(line, first, last):
    x0, x1 = line['bbox'][0], line['bbox'][2]
    if abs(x0 - first['bbox'][0]) < 2 or abs(x0 - last['bbox'][0]) < 2 or abs(x1 - last['bbox'][2]) < 2:
        return True
    return abs((x0 + x1) / 2 - (last['bbox'][0] + last['bbox'][2]) / 2) < 3


def group_paragraphs(blocks):
    paragraphs = []
    for lines in blocks:
        for line in lines:
            prev = paragraphs[-1] if paragraphs else None
            if prev and not line['bullet']:
                last = prev[-1]
                size = line['spans'][0]['size']
                gap = line['bbox'][1] - last['bbox'][3]
                if aligned(line, prev[0], last) and abs(size - last['spans'][-1]['size']) < 0.6 and -size * 0.3 < gap < size * 0.7:
                    prev.append(line)
                    continue
            paragraphs.append([line])
    return paragraphs


def absorb_shadows(blocks):
    kept = []
    for block in blocks:
        key = ''.join(s['t'] for l in block['lines'] for s in l['spans']).strip()
        twin = next((i for i, k in enumerate(kept) if k['key'] == key and abs(k['bbox'][0] - block['bbox'][0]) < 4 and abs(k['bbox'][1] - block['bbox'][1]) < 4), None)
        block['key'] = key
        block['extra'] = []
        if twin is None:
            kept.append(block)
            continue
        other = kept[twin]
        block['extra'] = other['extra'] + [r for l in other['lines'] for r in l['rects']]
        kept[twin] = block
    for block in kept:
        del block['key']
    return kept


def line_baseline(line):
    return max(line['spans'], key=lambda s: s['size'])['origin'][1]


def letter_spacing(span, font):
    chars = span['chars']
    if not font or len(chars) < 3:
        return 0.0
    gaps = []
    for char, following in zip(chars, chars[1:]):
        if char['c'].isspace() or following['c'].isspace() or not font.has_glyph(ord(char['c'])):
            continue
        gaps.append(following['origin'][0] - char['origin'][0] - font.glyph_advance(ord(char['c'])) * span['size'])
    if len(gaps) < 2:
        return 0.0
    spacing = statistics.median(gaps)
    return round(spacing, 3) if abs(spacing) > span['size'] * 0.02 else 0.0


def text_blocks(page, fonts, ctx):
    lookup = {name: ctx.stable_font(xref) for name, xref in font_lookup(fonts).items()}
    kinds, names = {}, {}
    for xref in set(lookup.values()) - {0}:
        profile = ctx.profile(xref)
        kinds[xref] = profile['kind'] if profile else None
        names[xref] = ctx.web_names(xref)
    result = []
    paragraphs = group_paragraphs(raw_lines(page))
    scanned = [all(s.get('alpha', 255) == 0 for l in lines for s in l['spans']) for lines in paragraphs]
    pixels = pdf_scan.raster(page) if any(scanned) else None
    scan_font = ctx.scan_font(page, pixels) if pixels is not None else None
    for lines in paragraphs:
        bbox = fitz.Rect(lines[0]['bbox'])
        for line in lines[1:]:
            bbox |= fitz.Rect(line['bbox'])
        baselines = [line_baseline(l) for l in lines]
        size = statistics.median(s['size'] for l in lines for s in l['spans'])
        deltas = [b - a for a, b in zip(baselines, baselines[1:]) if b - a > size * 0.5]
        scan = all(s.get('alpha', 255) == 0 for l in lines for s in l['spans'])
        align = guess_align(lines, bbox, page.rect.width)
        scan_color = pdf_scan.ink_color(pdf_scan.crop(pixels, bbox)) if scan else None
        out_lines = []
        for i, line in enumerate(lines):
            spans = []
            for s in line['spans']:
                bold, italic = style_of(s['font'], s['flags'])
                xref = 0 if scan else lookup.get(font_key(s['font']), 0)
                rise = baselines[i] - s['origin'][1]
                spans.append({
                    't': s['text'], 's': round(size if scan else s['size'], 2), 'c': (scan_color or '#000000') if scan else hex_color(s['color']),
                    'b': bold and not scan, 'i': italic and not scan, 'f': xref,
                    'k': (scan_font[1] if scan_font else 'serif') if scan else kinds.get(xref) or kind_of(s['font'], s['flags']),
                    'n': ([scan_font[0]] if scan_font else []) if scan else names.get(xref, []),
                    'lib': scan_font[0] if scan and scan_font else '',
                    'cs': 0.0 if scan or align == 'justify' else letter_spacing(s, ctx.program(xref)[0] if xref else None),
                    'rise': round(rise, 2) if abs(rise) > 0.5 and not scan else 0.0,
                })
            out_lines.append({
                'bbox': [round(v, 2) for v in line['bbox']],
                'brk': line_break_after(line, lines[i + 1] if i + 1 < len(lines) else None, bbox.x1),
                'spans': spans,
                'rects': [[round(v, 2) for v in s['bbox']] for s in line['spans']],
            })
        result.append({
            'bbox': [round(v, 2) for v in bbox],
            'scan': scan,
            'baseline': round(baselines[0], 2),
            'lh': round(min(deltas) / size, 3) if deltas else 1.2,
            'align': align,
            'lines': out_lines,
        })
    return absorb_shadows(result)


def page_layout(page, ctx=None):
    ctx = ctx or EditContext(page.parent)
    fonts = page_fonts(page)
    images = []
    for image in page_images(page):
        bbox = image['bbox'] & page.rect
        if bbox.width > 4 and bbox.height > 4:
            images.append({
                'xref': image['xref'], 'bbox': [round(v, 2) for v in image['bbox']], 'movable': image['movable'],
                'stable': 0 < image['xref'] < ctx.original_xrefs,
            })
    annots = []
    for annot in page.annots():
        kind = annot.type[1]
        if kind in ('Popup', 'Link', 'Widget'):
            continue
        annots.append({'kind': kind, 'rect': [round(v, 2) for v in annot.rect], 'movable': kind in MOVABLE_ANNOTS, 'text': annot.info.get('content', '')})
    widgets = []
    for widget in page.widgets():
        kind = WIDGET_TYPES.get(widget.field_type)
        if not kind:
            continue
        widgets.append({
            'name': widget.field_name, 'kind': kind, 'rect': [round(v, 2) for v in widget.rect],
            'value': widget.field_value if kind not in ('checkbox', 'radio') else widget.field_value not in (False, 'Off', '', None),
            'options': widget.choice_values or [], 'multiline': bool(widget.field_flags & fitz.PDF_TX_FIELD_IS_MULTILINE),
            'readonly': bool(widget.field_flags & fitz.PDF_FIELD_IS_READ_ONLY),
        })
    words = [[round(w[0], 1), round(w[1], 1), round(w[2], 1), round(w[3], 1), w[5], w[6]] for w in page.get_text('words', flags=fitz.TEXT_MEDIABOX_CLIP)]
    blocks = text_blocks(page, fonts, ctx)
    covered = sum((fitz.Rect(i['bbox']) & page.rect).get_area() for i in images)
    return {
        'width': round(page.rect.width, 2), 'height': round(page.rect.height, 2),
        'blocks': blocks, 'images': images, 'annots': annots, 'widgets': widgets, 'words': words,
        'scanned': not words and covered >= page.rect.get_area() * 0.5,
    }


INK_CACHE = {}
INK_CACHE_LIMIT = 20000


def glyph_has_ink(font, digest, char):
    key = (digest, char)
    if key not in INK_CACHE:
        if len(INK_CACHE) >= INK_CACHE_LIMIT:
            INK_CACHE.clear()
        with fitz.open() as doc:
            page = doc.new_page(width=40, height=40)
            writer = fitz.TextWriter(page.rect)
            writer.append((8, 30), char, font=font, fontsize=24)
            writer.write_text(page)
            INK_CACHE[key] = min(page.get_pixmap(alpha=False).samples) < 160
    return INK_CACHE[key]


def used_chars(page):
    lookup = font_lookup(page_fonts(page))
    chars = {}
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                xref = lookup.get(font_key(span['font']))
                if xref:
                    chars.setdefault(xref, set()).update(c['c'] for c in span['chars'])
    return chars


class FontPicker:
    def __init__(self, ctx, page):
        self.ctx = ctx
        self.cache = {}
        self.digests = {}
        self.fonts = [f for f in page_fonts(page) if f[1] < ctx.original_xrefs]
        self.names = {xref: name for name, xref, _subset in self.fonts}
        self.subset = {xref for _name, xref, subset in self.fonts if subset}
        chars = ctx.chars.get(page.number)
        self.chars = used_chars(page) if chars is None else chars

    def load(self, xref):
        font, digest = self.ctx.program(xref)
        if font:
            self.digests[xref] = digest
        return font

    def candidates(self, xref, bold, italic):
        family = family_of(self.names.get(xref, ''))
        same = [x for name, x, _subset in self.fonts if family and family_of(name) == family and style_of(name) == (bold, italic)]
        if style_of(self.names.get(xref, '')) == (bold, italic):
            same.insert(0, xref)
        return list(dict.fromkeys(same))

    def has(self, font, xref, char):
        if not font.has_glyph(ord(char)):
            return False
        return xref not in self.subset or char in self.chars.get(xref, ()) or glyph_has_ink(font, self.digests[xref], char)

    def originals(self, run):
        if not run.get('f'):
            return []
        chars = {c for c in str(run.get('t') or '') if not c.isspace()}
        found = []
        for xref in self.candidates(int(run['f']), bool(run.get('b')), bool(run.get('i'))):
            font = self.load(xref)
            if font:
                found.append((sum(1 for c in chars if self.has(font, xref, c)), len(found), font, xref))
        return [(font, xref) for _hits, _order, font, xref in sorted(found, key=lambda f: (-f[0], f[1]))]

    def substitute(self, run):
        entry, quality = self.ctx.match(int(run['f']), bool(run.get('b')), bool(run.get('i')), str(run.get('t') or ''))
        font = self.ctx.library.font(entry) if entry else None
        return (font, quality) if font else (None, None)

    def sources(self, run):
        if not run.get('f'):
            entry = self.ctx.library.styled(family_key(run.get('lib') or ''), bool(run.get('b')), bool(run.get('i'))) if run.get('lib') and self.ctx.fonts_ready() else None
            font = self.ctx.library.font(entry) if entry else None
            return [(font, 0, covers(font))] if font else []
        source = int(run['f'])
        font, quality = self.substitute(run)
        if quality == 'exact':
            return [(font, source, covers(font))]
        found = [(f, xref, lambda c, f=f, xref=xref: self.has(f, xref, c)) for f, xref in self.originals(run)]
        if font:
            found.append((font, source, covers(font)))
        return found

    def generic(self, kind, bold, italic):
        code = GENERIC_FONTS[kind if kind in GENERIC_FONTS else 'sans'][int(bold) + 2 * int(italic)]
        if code not in self.cache:
            self.cache[code] = fitz.Font(code)
        return self.cache[code]


def covers(font):
    return lambda char: bool(font.has_glyph(ord(char)))


def space_width(font, size, mono):
    if font.has_glyph(32):
        return font.text_length(' ', fontsize=size)
    if mono:
        return font.glyph_advance(ord('0')) * size
    return size * 0.25


def split_pieces(text, sources, fallback, cover):
    pieces = []
    for char in text:
        font, source = next(((f, xref) for f, xref, has in sources if has(char)), (fallback, 0))
        if font is fallback and not char.isspace() and not fallback.has_glyph(ord(char)):
            font = cover(char) or fallback
        if pieces and pieces[-1][1] is font:
            pieces[-1][0] += char
        else:
            pieces.append([char, font, source])
    return pieces


def shaped(piece):
    text, font, source = piece
    return [text, font, source, shaping.SHAPER.shape(font, text)]


def piece_width(piece, size, spacing):
    text, font, _source, glyphs = piece
    if glyphs is not None:
        return shaping.advance(glyphs, size, spacing)
    return font.text_length(text, fontsize=size) + spacing * len(text)


def layout_runs(op, picker):
    family = op.get('family') or 'original'
    tokens = []
    for run in op.get('runs') or []:
        if not run.get('t'):
            continue
        bold, italic = bool(run.get('b')), bool(run.get('i'))
        kind = family if family in GENERIC_FONTS else run.get('k')
        fallback = picker.generic(kind, bold, italic)
        sources = picker.sources(run) if family == 'original' else []
        size = max(1.0, min(400.0, float(run.get('s') or 12)))
        spacing = max(-size * 0.5, min(size * 2, float(run.get('cs') or 0)))
        rise = max(-size, min(size, float(run.get('rise') or 0)))
        for part in re.split(r'(\n| +)', str(run['t'])):
            if not part:
                continue
            if part == '\n':
                tokens.append(None)
                continue
            base = {'run': run, 'size': size, 'cs': spacing, 'rise': rise}
            if part.isspace():
                font, source = (sources[0][0], sources[0][1]) if sources else (fallback, 0)
                width = (space_width(font, size, kind == 'mono') + spacing) * len(part)
                pieces = [[part, font, source, None]] if font.has_glyph(32) else []
                tokens.append(dict(base, pieces=pieces, space=True, width=width))
                continue
            pieces = [shaped(piece) for piece in split_pieces(part, sources, fallback, lambda c: picker.ctx.cover(c, kind))]
            width = sum(piece_width(piece, size, spacing) for piece in pieces)
            tokens.append(dict(base, pieces=pieces, space=False, width=width))
    return tokens


def wrap_tokens(tokens, width):
    lines, line, used = [], [], 0.0
    for token in tokens + [None]:
        if token is None:
            lines.append((line, True))
            line, used = [], 0.0
            continue
        if token['space'] and not line:
            continue
        if not token['space'] and line and used + token['width'] > width + 0.5:
            while line and line[-1]['space']:
                line.pop()
            lines.append((line, False))
            line, used = [], 0.0
        line.append(token)
        used += token['width']
    if len(lines) > 1 and not lines[-1][0]:
        lines.pop()
    return lines


def text_rect(page, op):
    rect = rect_of(op['rect'])
    if not op.get('grow'):
        return rect
    width = page.rect.width
    align = op.get('align') or 'left'
    if align == 'right':
        rect.x0 = min(rect.x0, width - rect.x1)
    elif align == 'center':
        half = max(rect.width / 2, min(rect.x0 + rect.width / 2, width - rect.x0 - rect.width / 2))
        center = rect.x0 + rect.width / 2
        rect.x0, rect.x1 = center - half, center + half
    else:
        rect.x1 = max(rect.x1, width - min(rect.x0, 36))
    return rect


def scaled(tokens, scale):
    if scale == 1:
        return tokens
    return [t and dict(t, size=t['size'] * scale, width=t['width'] * scale, cs=t['cs'] * scale, rise=t['rise'] * scale) for t in tokens]


def typeset(page, op, tokens, scale=1.0):
    rect = text_rect(page, op)
    tokens = scaled(tokens, scale)
    lh = max(0.8, min(3.0, float(op.get('lh') or 1.2)))
    width = max(rect.width, 4)
    first = next(t for t in tokens if t and not t['space'])
    if op.get('baseline') is not None:
        baseline = rect.y0 + (float(op['baseline']) - rect.y0) * scale
    else:
        baseline = rect.y0 + first['pieces'][0][1].ascender * first['size']
    placed = []
    size = first['size']
    for index, (line, last) in enumerate(wrap_tokens(tokens, width)):
        while line and line[-1]['space']:
            line = line[:-1]
        size = max((t['size'] for t in line), default=first['size'])
        if index:
            baseline += lh * size
        placed.append((line, last, baseline))
    return {'rect': rect, 'width': width, 'lines': placed, 'bottom': baseline + size * 0.25, 'size': first['size']}


def fitted(page, op, tokens):
    layout = typeset(page, op, tokens)
    if not op.get('fit') or layout['bottom'] <= layout['rect'].y1:
        return layout
    low, high, best = 0.5, 1.0, typeset(page, op, tokens, 0.5)
    for _ in range(8):
        middle = (low + high) / 2
        candidate = typeset(page, op, tokens, middle)
        if candidate['bottom'] <= candidate['rect'].y1:
            low, best = middle, candidate
        else:
            high = middle
    return best


def token_direction(token):
    if token['space']:
        return 'space'
    return 'rtl' if any(shaping.is_rtl(piece[0]) for piece in token['pieces']) else 'ltr'


def visual_order(line):
    segments = []
    for token in line:
        kind = token_direction(token)
        if segments and segments[-1][0] == 'ltr' and kind in ('ltr', 'space'):
            segments[-1][1].append(token)
        else:
            segments.append([kind, [token]])
    ordered = []
    for kind, tokens in segments:
        trailing = []
        while kind == 'ltr' and tokens and tokens[-1]['space']:
            trailing.insert(0, tokens.pop())
        ordered.append(tokens)
        if trailing:
            ordered.append(trailing)
    return [token for tokens in reversed(ordered) for token in tokens]


def draw_layout(page, layout, align, ctx, rtl=False):
    rect, width = layout['rect'], layout['width']
    writers = {}
    if rtl and align == 'left':
        align = 'right'
    for line, last, baseline in layout['lines']:
        if rtl:
            line = visual_order(line)
        used = sum(t['width'] for t in line)
        x = rect.x0
        gap_extra = 0.0
        if align == 'center':
            x += (width - used) / 2
        elif align == 'right':
            x += width - used
        elif align == 'justify' and not last:
            gaps = sum(1 for t in line if t['space'])
            gap_extra = (width - used) / gaps if gaps else 0.0
        for token in line:
            color = token['run'].get('c') or '#000000'
            y = baseline - token['rise']
            if token['space']:
                for text, font, source, _glyphs in token['pieces']:
                    writer = writers.setdefault((color, source), fitz.TextWriter(page.rect))
                    writer.append((x, y), text, font=font, fontsize=token['size'])
                x += token['width'] + gap_extra
                continue
            pieces = token['pieces'][::-1] if rtl and any(shaping.is_rtl(p[0]) for p in token['pieces']) else token['pieces']
            for text, font, source, glyphs in pieces:
                writer = writers.setdefault((color, source), fitz.TextWriter(page.rect))
                if glyphs is not None:
                    x += shaping.append(writer, (x, y), font, token['size'], glyphs, token['cs'])
                    continue
                for chunk in (text if token['cs'] else [text]):
                    writer.append((x, y), chunk, font=font, fontsize=token['size'])
                    x += font.text_length(chunk, fontsize=token['size']) + token['cs'] * len(chunk)
    for (color, source), writer in writers.items():
        before = {f[0] for f in page.get_fonts()}
        writer.write_text(page, color=rgb(color))
        if source:
            for xref in {f[0] for f in page.get_fonts()} - before:
                ctx.origins[xref] = ctx.stable_font(source)


def write_text(page, op, picker, ctx):
    tokens = layout_runs(op, picker)
    if not any(t and not t['space'] for t in tokens):
        return 0.0
    layout = fitted(page, op, tokens)
    text = ''.join(str(run.get('t') or '') for run in op.get('runs') or [])
    draw_layout(page, layout, op.get('align') or 'left', ctx, shaping.mostly_rtl(text))
    overflow = layout['bottom'] - layout['rect'].y1
    return overflow if overflow > layout['size'] * 0.35 else 0.0


def shrink(rect):
    r = rect_of(rect)
    pad = r.height * 0.25
    return fitz.Rect(r.x0 + 0.3, r.y0 + pad, r.x1 - 0.3, r.y1 - pad)


def baked_background(page, area, before):
    after = page.get_pixmap(clip=area, matrix=fitz.Matrix(2, 2), alpha=False)
    a, b = after.samples, before.samples
    if len(a) != len(b) or not a:
        return None
    step = max(1, len(a) // 200000)
    samples = range(0, len(a), step)
    if sum(abs(a[i] - b[i]) for i in samples) / len(samples) >= 3:
        return None
    stride = 3 * max(1, len(a) // 60000)
    color = Counter(a[i:i + 3] for i in range(0, len(a) - 2, stride)).most_common(1)[0][0]
    return tuple(c / 255 for c in color)


def apply_own_redactions(page, rects, fill, **options):
    doc = page.parent
    pending = [xref for xref, kind, _id in page.annot_xrefs() if kind == fitz.PDF_ANNOT_REDACT]
    if pending:
        keep = [xref for xref, kind, _id in page.annot_xrefs() if kind != fitz.PDF_ANNOT_REDACT]
        doc.xref_set_key(page.xref, 'Annots', annots_array(keep))
        page = doc.reload_page(page)
    for rect in rects:
        page.add_redact_annot(rect, fill=fill)
    page.apply_redactions(**options)
    if pending:
        current = [xref for xref, _kind, _id in page.annot_xrefs()]
        doc.xref_set_key(page.xref, 'Annots', annots_array(current + pending))
        page = doc.reload_page(page)
    return page


def annots_array(xrefs):
    return '[' + ' '.join(f'{xref} 0 R' for xref in xrefs) + ']'


def op_text(ctx, page, op):
    removes = [rect_of(r) for r in op.get('remove') or []]
    marker = None
    if removes:
        before = pdf_tags.text_ids(pdf_tags.contents(page)[1]) if pdf_tags.is_tagged(ctx.doc, page) else {}
        area = fitz.Rect(removes[0])
        for r in removes[1:]:
            area |= r
        area = (area + (-1, -1, 1, 1)) & page.rect
        snapshot = page.get_pixmap(clip=area, matrix=fitz.Matrix(2, 2), alpha=False)
        page = apply_own_redactions(page, [shrink(r) for r in removes], False, **KEEP_GRAPHICS)
        if before:
            marker = pdf_tags.detach(page, before)
            page = ctx.doc.reload_page(page)
        cover = baked_background(page, area, snapshot)
        if cover and not pdf_scan.inpaint(page, area, snapshot, removes):
            page.draw_rect(area, color=None, fill=cover, overlay=True)
    if op.get('runs') and op.get('rect'):
        previous = set(page.get_contents())
        overflow = write_text(page, op, ctx.picker(page), ctx)
        if marker:
            pdf_tags.attach(page, marker, previous)
        if overflow:
            ctx.overflow[ctx.current] = round(overflow, 2)
    return page


def rect_distance(a, b):
    return abs(a.x0 - b.x0) + abs(a.y0 - b.y0) + abs(a.x1 - b.x1) + abs(a.y1 - b.y1)


def image_draws(page, drop=None, capture=None):
    pdfpage = fitz._as_pdf_page(page)
    page_matrix = mupdf.FzMatrix()
    mupdf.pdf_page_transform(pdfpage, mupdf.FzRect(), page_matrix)
    unit = mupdf.FzRect(mupdf.FzRect.Fixed_UNIT)
    draws = []
    dropped = []

    class Options(mupdf.PdfSanitizeFilterOptions2):
        def __init__(self):
            super().__init__()
            self.use_virtual_image_filter()

        def image_filter(self, _ctx, ctm, _name, image, _scissor):
            ctm = mupdf.FzMatrix(ctm)
            box = mupdf.fz_transform_rect(unit, mupdf.fz_concat(ctm, page_matrix))
            draws.append({
                'bbox': fitz.Rect(box.x0, box.y0, box.x1, box.y1),
                'upright': abs(ctm.b) < 1e-6 and abs(ctm.c) < 1e-6 and ctm.a > 0 and ctm.d > 0,
                'mask': bool(image.imagemask),
            })
            if len(draws) - 1 in (drop, capture):
                dropped.append(mupdf.FzImage(mupdf.ll_fz_keep_image(image)))
            if len(draws) - 1 == drop:
                return None
            return mupdf.ll_fz_keep_image(image)

    options = Options()
    filters = _make_PdfFilterOptions(recurse=1, instance_forms=1, no_update=int(drop is None), sanitize=1, sopts=options)
    mupdf.pdf_filter_page_contents(pdfpage.doc(), pdfpage, filters)
    return draws, (dropped[0] if dropped else None)


def page_images(page):
    draws, _ = image_draws(page)
    infos = page.get_image_info(xrefs=True)
    for draw in draws:
        match = min(infos, key=lambda info: rect_distance(fitz.Rect(info['bbox']), draw['bbox']), default=None)
        close = match is not None and rect_distance(fitz.Rect(match['bbox']), draw['bbox']) < 1
        draw['xref'] = match['xref'] if close else 0
        draw['movable'] = draw['upright'] and not draw['mask']
    return draws


def find_image(images, xref, bbox):
    target = rect_of(bbox)
    scored = [(rect_distance(image['bbox'], target) - (0.5 if xref and image['xref'] == xref else 0), i) for i, image in enumerate(images)]
    score, index = min(scored, default=(99, -1))
    return index if score < 4 else -1


def decoded_pixmap(image):
    pix = fitz.Pixmap(mupdf.fz_get_pixmap_from_image(image, mupdf.FzIrect(mupdf.fz_infinite_irect), mupdf.FzMatrix())[0])
    if pix.colorspace and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix


def copy_image(ctx, page, rect, source):
    xref = int(source.get('xref') or 0)
    if 0 < xref < ctx.original_xrefs:
        page.insert_image(rect, xref=xref, keep_proportion=False)
    elif source.get('bbox'):
        images = page_images(page)
        index = find_image(images, xref, source['bbox'])
        if index >= 0:
            _draws, decoded = image_draws(page, capture=index)
            if decoded is not None:
                page.insert_image(rect, pixmap=decoded_pixmap(decoded), keep_proportion=False)
    return page


def op_image(ctx, page, op):
    rect = rect_of(op['rect']) if op.get('rect') else None
    path = op.get('path')
    if rect and isinstance(op.get('source'), dict) and not path:
        return copy_image(ctx, page, rect, op['source'])
    if op.get('remove'):
        images = page_images(page)
        index = find_image(images, int(op.get('xref') or 0), op['remove'])
        if index >= 0:
            image = images[index]
            if rect and not path and not image['movable']:
                return page
            _draws, decoded = image_draws(page, drop=index)
            page = ctx.doc.reload_page(page)
            if rect and not path:
                if image['xref']:
                    page.insert_image(rect, xref=image['xref'], keep_proportion=False)
                elif decoded is not None:
                    page.insert_image(rect, pixmap=decoded_pixmap(decoded), keep_proportion=False)
                return page
        elif rect and not path:
            return page
    if rect and path:
        page.insert_image(rect, filename=path, keep_proportion=False)
    return page


def op_annot(ctx, page, op):
    kind = op.get('kind')
    color = rgb(op.get('color'), (1, 0.85, 0) if kind == 'highlight' else (0.9, 0.1, 0.1))
    fill = rgb(op['fill']) if op.get('fill') else None
    width = max(0.2, min(30.0, float(op.get('width') or 2)))
    if kind in MARKUP_KINDS:
        quads = [rect_of(r).quad for r in op.get('rects') or []]
        if not quads:
            return page
        annot = getattr(page, f'add_{kind}_annot')(quads)
        annot.set_colors(stroke=color)
    elif kind == 'ink':
        strokes = [[(float(x), float(y)) for x, y in stroke] for stroke in op.get('points') or [] if len(stroke) > 1]
        if not strokes:
            return page
        annot = page.add_ink_annot(strokes)
        annot.set_colors(stroke=color)
        annot.set_border(width=width)
    elif kind in ('rect', 'ellipse'):
        rect = rect_of(op['rect'])
        annot = page.add_rect_annot(rect) if kind == 'rect' else page.add_circle_annot(rect)
        annot.set_colors(stroke=color, fill=fill)
        annot.set_border(width=width)
    elif kind in ('line', 'arrow'):
        x0, y0, x1, y1 = [float(v) for v in op['rect'][:4]]
        annot = page.add_line_annot((x0, y0), (x1, y1))
        annot.set_colors(stroke=color, fill=color)
        annot.set_border(width=width)
        if kind == 'arrow':
            annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
    elif kind == 'note':
        x, y = [float(v) for v in op['rect'][:2]]
        annot = page.add_text_annot((x, y), str(op.get('text') or ''), icon='Comment')
        annot.set_colors(stroke=color)
    else:
        return page
    if op.get('opacity') is not None:
        annot.set_opacity(max(0.05, min(1.0, float(op['opacity']))))
    annot.update()
    return page


def find_annot(page, rect):
    target = rect_of(rect)
    best, score = None, 3.0
    for annot in page.annots():
        if annot.type[1] in ('Popup', 'Link', 'Widget'):
            continue
        diff = rect_distance(annot.rect, target)
        if diff < score:
            best, score = annot, diff
    return best


def shifted(points, dx, dy):
    return [(x + dx, y + dy) for x, y in points]


def clone_annot(page, annot, dx, dy):
    kind = annot.type[1]
    colors = annot.colors
    rect = annot.rect + (dx, dy, dx, dy)
    vertices = annot.vertices or []
    if kind in ('Square', 'Circle'):
        copy = page.add_rect_annot(rect) if kind == 'Square' else page.add_circle_annot(rect)
    elif kind == 'Ink':
        copy = page.add_ink_annot([shifted(stroke, dx, dy) for stroke in vertices])
    elif kind == 'Line' and len(vertices) >= 2:
        copy = page.add_line_annot(*shifted(vertices[:2], dx, dy))
        copy.set_line_ends(*annot.line_ends)
    elif kind in ('Highlight', 'Underline', 'StrikeOut', 'Squiggly') and len(vertices) >= 4:
        points = shifted(vertices, dx, dy)
        quads = [fitz.Quad(*points[i:i + 4]) for i in range(0, len(points) - 3, 4)]
        copy = getattr(page, f'add_{kind.lower()}_annot')(quads)
    elif kind == 'Text':
        copy = page.add_text_annot(rect.tl, annot.info.get('content', ''), icon='Comment')
    else:
        return
    copy.set_colors(stroke=colors.get('stroke'), fill=colors.get('fill'))
    if annot.border.get('width') is not None and kind not in ('Highlight', 'Underline', 'StrikeOut', 'Squiggly', 'Text'):
        copy.set_border(width=annot.border['width'])
    copy.set_opacity(annot.opacity if annot.opacity >= 0 else 1)
    copy.set_info(annot.info)
    copy.update()


def op_annot_edit(ctx, page, op):
    annot = find_annot(page, op['target'])
    if not annot:
        return page
    if isinstance(op.get('copy'), list):
        dx, dy = [float(v) for v in op['copy'][:2]]
        clone_annot(page, annot, dx, dy)
    elif op.get('delete'):
        page.delete_annot(annot)
    elif op.get('rect') and annot.type[1] in MOVABLE_ANNOTS:
        annot.set_rect(rect_of(op['rect']))
        annot.update()
    return page


def op_ocr(ctx, page, op):
    if page.get_text('words'):
        return page
    progress = pdf_scan.recognize(page, ctx.wait, op.get('retry'))
    if progress:
        page = ctx.doc.reload_page(page)
        progress.update('fonts', pdf_scan.MATCHING)
        ctx.scan_font(page)
        progress.finish()
    return page


def op_whiteout(ctx, page, op):
    page.draw_rect(rect_of(op['rect']), color=None, fill=rgb(op.get('color'), (1, 1, 1)), overlay=True)
    return page


def without_ref(value, xref):
    refs = [ref for ref in re.findall(r'(\d+) (\d+) R', value) if int(ref[0]) != xref]
    return '[' + ' '.join(f'{num} {gen} R' for num, gen in refs) + ']'


def detach_field(doc, xref):
    kind, parent = doc.xref_get_key(xref, 'Parent')
    if kind == 'xref':
        owner = int(parent.split()[0])
        kids = without_ref(doc.xref_get_key(owner, 'Kids')[1], xref)
        doc.xref_set_key(owner, 'Kids', kids)
        if kids == '[]':
            detach_field(doc, owner)
        return
    fields = doc.xref_get_key(doc.pdf_catalog(), 'AcroForm/Fields')
    if fields[0] == 'array':
        doc.xref_set_key(doc.pdf_catalog(), 'AcroForm/Fields', without_ref(fields[1], xref))


def remove_widgets(page, xrefs):
    doc = page.parent
    keep = [xref for xref, _kind, _id in page.annot_xrefs() if xref not in xrefs]
    doc.xref_set_key(page.xref, 'Annots', annots_array(keep))
    for xref in xrefs:
        detach_field(doc, xref)
    return doc.reload_page(page)


def op_redact(ctx, page, op):
    rects = [rect_of(r) for r in op.get('rects') or [op['rect']]]
    hits = lambda area: any(area.intersects(r) for r in rects)
    covered = [w.xref for w in page.widgets() if hits(w.rect)]
    if covered:
        page = remove_widgets(page, set(covered))
    for xref in [a.xref for a in page.annots() if a.type[1] not in ('Popup', 'Redact') and hits(a.rect)]:
        annot = page.load_annot(xref)
        if annot:
            page.delete_annot(annot)
    for link in [link for link in page.get_links() if hits(fitz.Rect(link['from']))]:
        page.delete_link(link)
    return apply_own_redactions(page, rects, (0, 0, 0))


def op_form(ctx, page, op):
    target = rect_of(op['rect']) if op.get('rect') else None
    for widget in page.widgets():
        if widget.field_name != op.get('name'):
            continue
        if target and abs(widget.rect.x0 - target.x0) + abs(widget.rect.y0 - target.y0) > 2:
            continue
        kind = WIDGET_TYPES.get(widget.field_type)
        value = op.get('value')
        if kind == 'radio':
            if not value:
                continue
            widget.field_value = True
        elif kind == 'checkbox':
            widget.field_value = widget.on_state() if value else 'Off'
        else:
            widget.field_value = '' if value is None else str(value)
        widget.update()
        ctx.doc.xref_set_key(ctx.doc.pdf_catalog(), 'AcroForm/NeedAppearances', 'true')
    return page


OPS = {
    'text': op_text, 'image': op_image, 'annot': op_annot, 'annot_edit': op_annot_edit,
    'whiteout': op_whiteout, 'redact': op_redact, 'form': op_form, 'ocr': op_ocr,
}
RELOAD_AFTER = {'text', 'image', 'redact', 'ocr'}


def apply_page_ops(ctx, page, ops):
    prepare_page(page)
    ctx.chars[page.number] = used_chars(page)
    for index, op in enumerate(ops):
        handler = OPS.get(op.get('type'))
        if not handler:
            continue
        ctx.current = (page.number, index)
        page = handler(ctx, page, op)
        if op.get('type') in RELOAD_AFTER:
            page = ctx.doc.reload_page(page)
    return page


PAGE_SIZE_LIMIT = (36, 14400)


def group_ops(ops, page_count):
    pages = {}
    for op in ops or []:
        if op.get('type') in ('page', 'sanitize', 'digital_sign'):
            continue
        try:
            index = int(op.get('page'))
        except (TypeError, ValueError):
            continue
        if 0 <= index < page_count:
            pages.setdefault(index, []).append(op)
    return pages


def blank_size(op):
    try:
        width, height = [float(v) for v in op.get('size')[:2]]
    except (TypeError, ValueError, IndexError):
        return 595.0, 842.0
    low, high = PAGE_SIZE_LIMIT
    return max(low, min(high, width)), max(low, min(high, height))


def page_structure(ops, count):
    order = list(range(count))
    rotation = {}
    blanks = {}
    for op in ops or []:
        if op.get('type') != 'page':
            continue
        try:
            pid = int(op.get('page'))
            target = int(op.get('to') or 0)
        except (TypeError, ValueError):
            continue
        action = op.get('action')
        if action == 'insert' and pid == count + len(blanks) and pid not in order:
            blanks[pid] = blank_size(op)
            order.insert(max(0, min(len(order), target)), pid)
        elif pid not in order:
            continue
        elif action == 'delete' and len(order) > 1:
            order.remove(pid)
        elif action == 'move':
            order.remove(pid)
            order.insert(max(0, min(len(order), target)), pid)
        elif action == 'rotate':
            rotation[pid] = (rotation.get(pid, 0) + int(op.get('angle') or 90)) % 360
    return order, rotation, blanks


def add_blanks(doc, blanks, upto=None):
    for pid in sorted(blanks):
        if upto is not None and pid > upto:
            break
        width, height = blanks[pid]
        doc.new_page(width=width, height=height)


def sanitize(doc, options):
    pick = lambda key: bool(options.get(key))
    if pick('comments'):
        for page in doc:
            for xref in [a.xref for a in page.annots() if a.type[1] not in ('Widget', 'Link')]:
                annot = page.load_annot(xref)
                if annot:
                    page.delete_annot(annot)
    doc.scrub(
        attached_files=pick('attachments'), embedded_files=pick('attachments'), hidden_text=pick('hidden_text'),
        javascript=pick('javascript'), metadata=pick('metadata'), xml_metadata=pick('metadata'),
        remove_links=pick('links'), reset_fields=pick('fields'), reset_responses=pick('comments'),
        thumbnails=True, redactions=False, clean_pages=True,
    )


def signature_placement(doc, ops, order):
    op = next((o for o in reversed(ops or []) if o.get('type') == 'digital_sign'), None)
    try:
        pid = int(op['page']) if op else -1
        rect = rect_of(op['rect']) if op else None
    except (KeyError, TypeError, ValueError):
        return None
    if pid not in order or rect is None or rect.is_empty:
        return None
    page = doc[pid]
    prepare_page(page)
    box = (rect * ~page.transformation_matrix).normalize()
    return {
        'page': order.index(pid), 'box': tuple(round(v, 2) for v in box),
        'reason': str(op.get('reason') or '')[:200], 'location': str(op.get('location') or '')[:200],
    }


def apply_ops(doc, ops, progress=None):
    ctx = EditContext(doc)
    count = doc.page_count
    order, rotation, blanks = page_structure(ops, count)
    add_blanks(doc, blanks)
    grouped = sorted(group_ops(ops, doc.page_count).items())
    for done, (index, page_ops) in enumerate(grouped, 1):
        apply_page_ops(ctx, doc[index], page_ops)
        if progress:
            progress(done, len(grouped))
    placement = signature_placement(doc, ops, order)
    for pid, angle in rotation.items():
        page = doc[pid]
        page.set_rotation((page.rotation + angle) % 360)
    cleanup = next((op for op in reversed(ops or []) if op.get('type') == 'sanitize'), None)
    if cleanup and isinstance(cleanup.get('options'), dict):
        sanitize(doc, cleanup['options'])
    if order != list(range(doc.page_count)):
        doc.select(order)
    return {'signature': placement, 'fonts_added': bool(ctx.origins) or any(op.get('type') == 'text' and op.get('runs') for op in ops or [])}


def search_document(path, ops, query, kinds, whole_word=False, progress=None):
    with fitz.open(path) as doc:
        if doc.needs_pass:
            return [], False
        ctx = EditContext(doc, wait=False)
        order, _rotation, blanks = page_structure(ops, doc.page_count)
        add_blanks(doc, blanks)
        grouped = group_ops(ops, doc.page_count)
        results = []
        if progress:
            progress(0, len(order))
        for done, index in enumerate(order, 1):
            page = doc[index]
            try:
                page = apply_page_ops(ctx, page, grouped[index]) if grouped.get(index) else page
            except pdf_scan.OcrPending:
                page = doc.reload_page(page)
            prepare_page(page)
            for match in search_page(page, query, kinds, whole_word):
                results.append(dict(match, page=index))
                if len(results) >= MAX_MATCHES:
                    return results, True
            if progress:
                progress(done, len(order))
        return results, False


class PreviewCache:
    def __init__(self, limit=48):
        self.limit = limit
        self.items = OrderedDict()
        self.lock = threading.Lock()

    def key(self, path, index, ops, width):
        stat = os.stat(path)
        payload = json.dumps(ops, sort_keys=True, separators=(',', ':'), default=str)
        ready = FontLibrary.shared().ready.is_set()
        return (path, stat.st_mtime_ns, stat.st_size, index, width, ready, hashlib.blake2b(payload.encode(), digest_size=16).digest())

    def get(self, key):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        return None

    def put(self, key, value):
        with self.lock:
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.limit:
                self.items.popitem(last=False)


PREVIEWS = PreviewCache()


def render_preview(path, index, ops, width):
    key = PREVIEWS.key(path, index, ops, width)
    cached = PREVIEWS.get(key)
    if cached is None:
        cached = build_preview(path, index, ops, width)
        if cached is not None and not cached.get('ocr_pending'):
            PREVIEWS.put(key, cached)
    return dict(cached) if cached is not None else None


def build_preview(path, index, ops, width):
    with fitz.open(path) as doc:
        if doc.needs_pass or index < 0:
            return None
        ctx = EditContext(doc, wait=False)
        _order, _rotation, blanks = page_structure(ops, doc.page_count)
        if index >= doc.page_count:
            if index not in blanks:
                return None
            add_blanks(doc, blanks, index)
        try:
            page = apply_page_ops(ctx, doc[index], group_ops(ops, doc.page_count).get(index, []))
        except pdf_scan.OcrPending as pending:
            return {'ocr_pending': True, **({'task_id': pending.task_id} if pending.task_id else {})}
        layout = page_layout(page, ctx)
        layout['overflow'] = {str(i): by for (number, i), by in ctx.overflow.items() if number == index}
        zoom = max(0.05, min(5.0, width / max(1.0, page.rect.width)))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        layout['image'] = 'data:image/jpeg;base64,' + base64.b64encode(pix.tobytes(output='jpeg', jpg_quality=85)).decode()
        return layout


def web_font(path, xref):
    with fitz.open(path) as doc:
        if xref <= 0 or xref >= doc.xref_length():
            return None
        try:
            name, ext, _type, buffer = doc.extract_font(xref)
        except Exception:
            return None
        if not buffer:
            return None
        data = web_font_bytes(buffer, ext, bare_name(name) or 'Embedded')
        return ('otf' if ext in ('cff', 'cid', 'otf') else 'ttf', data) if data else None


def page_sizes(path):
    with fitz.open(path) as doc:
        sizes = []
        for page in doc:
            rect = page.rect
            sizes.append([round(rect.width, 2), round(rect.height, 2)])
        return sizes
