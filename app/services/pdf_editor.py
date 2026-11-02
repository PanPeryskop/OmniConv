import base64
import re
import statistics
from collections import Counter

import fitz

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
    if flags & 4 or any(w in lower for w in ('times', 'serif', 'georgia', 'garamond', 'cambria', 'roman', 'book')) and 'sans' not in lower:
        return 'serif'
    return 'sans'


def prepare_page(page):
    if page.rotation:
        page.remove_rotation()


def page_fonts(page):
    return [(bare_name(basefont), xref, bool(SUBSET_RE.match(basefont))) for xref, _e, _t, basefont, *_ in page.get_fonts(full=True) if xref and basefont]


def font_lookup(fonts):
    lookup = {}
    for name, xref, _subset in fonts:
        lookup.setdefault(name, xref)
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
        return 'center' if centered and bbox.width < page_width * 0.85 else 'left'
    lefts = [l['bbox'][0] - bbox.x0 for l in lines]
    rights = [bbox.x1 - l['bbox'][2] for l in lines]
    if max(lefts) < 2:
        return 'justify' if len(lines) > 2 and max(rights[:-1]) < 2 else 'left'
    if max(rights) < 2:
        return 'right'
    if all(abs(a - b) < 3 for a, b in zip(lefts, rights)):
        return 'center'
    return 'left'


def raw_lines(page):
    blocks = []
    for block in page.get_text('dict', flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP)['blocks']:
        if block['type'] != 0:
            continue
        lines = []
        for line in block['lines']:
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


def text_blocks(page, fonts):
    lookup = font_lookup(fonts)
    result = []
    for lines in group_paragraphs(raw_lines(page)):
        bbox = fitz.Rect(lines[0]['bbox'])
        for line in lines[1:]:
            bbox |= fitz.Rect(line['bbox'])
        baselines = [l['spans'][0]['origin'][1] for l in lines]
        size = statistics.median(s['size'] for l in lines for s in l['spans'])
        deltas = [b - a for a, b in zip(baselines, baselines[1:]) if b - a > size * 0.5]
        scan = all(s.get('alpha', 255) == 0 for l in lines for s in l['spans'])
        out_lines = []
        for i, line in enumerate(lines):
            spans = []
            for s in line['spans']:
                bold, italic = style_of(s['font'], s['flags'])
                spans.append({
                    't': s['text'], 's': round(size if scan else s['size'], 2), 'c': '#000000' if scan else hex_color(s['color']),
                    'b': bold and not scan, 'i': italic and not scan,
                    'f': 0 if scan else lookup.get(bare_name(s['font']), 0), 'k': 'serif' if scan else kind_of(s['font'], s['flags']),
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
            'align': guess_align(lines, bbox, page.rect.width),
            'lines': out_lines,
        })
    return absorb_shadows(result)


def page_layout(page):
    fonts = page_fonts(page)
    images = []
    for info in page.get_image_info(xrefs=True):
        bbox = fitz.Rect(info['bbox']) & page.rect
        if bbox.width > 4 and bbox.height > 4:
            images.append({'xref': info['xref'], 'bbox': [round(v, 2) for v in bbox]})
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
    return {
        'width': round(page.rect.width, 2), 'height': round(page.rect.height, 2),
        'blocks': text_blocks(page, fonts), 'images': images, 'annots': annots, 'widgets': widgets, 'words': words,
    }


INK_CACHE = {}


def glyph_has_ink(font, char):
    key = (font.name, font.glyph_count, len(font.buffer), char)
    if key not in INK_CACHE:
        with fitz.open() as doc:
            page = doc.new_page(width=40, height=40)
            writer = fitz.TextWriter(page.rect)
            writer.append((8, 30), char, font=font, fontsize=24)
            writer.write_text(page)
            INK_CACHE[key] = min(page.get_pixmap(alpha=False).samples) < 160
    return INK_CACHE[key]


class FontPicker:
    def __init__(self, doc, page):
        self.doc = doc
        self.cache = {}
        self.fonts = page_fonts(page)
        self.names = {xref: name for name, xref, _subset in self.fonts}
        self.subset = {xref for _name, xref, subset in self.fonts if subset}
        lookup = font_lookup(self.fonts)
        self.chars = {}
        for block in page.get_text('rawdict')['blocks']:
            for line in block.get('lines', []):
                for span in line['spans']:
                    xref = lookup.get(bare_name(span['font']))
                    if xref:
                        self.chars.setdefault(xref, set()).update(c['c'] for c in span['chars'])

    def load(self, xref):
        if xref not in self.cache:
            try:
                _name, ext, _type, buffer = self.doc.extract_font(xref)
                self.cache[xref] = fitz.Font(fontbuffer=buffer) if buffer and ext != 'n/a' else None
            except Exception:
                self.cache[xref] = None
        return self.cache[xref]

    def candidates(self, xref, bold, italic):
        family = family_of(self.names.get(xref, ''))
        same = [x for name, x, _subset in self.fonts if family and family_of(name) == family and style_of(name) == (bold, italic)]
        if style_of(self.names.get(xref, '')) == (bold, italic):
            same.insert(0, xref)
        return list(dict.fromkeys(same))

    def has(self, font, xref, char):
        if not font.has_glyph(ord(char)):
            return False
        return xref not in self.subset or char in self.chars.get(xref, ()) or glyph_has_ink(font, char)

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

    def generic(self, kind, bold, italic):
        code = GENERIC_FONTS[kind if kind in GENERIC_FONTS else 'sans'][int(bold) + 2 * int(italic)]
        if code not in self.cache:
            self.cache[code] = fitz.Font(code)
        return self.cache[code]


def space_width(font, size, mono):
    if font.has_glyph(32):
        return font.text_length(' ', fontsize=size)
    if mono:
        return font.glyph_advance(ord('0')) * size
    return size * 0.25


def split_pieces(text, originals, fallback, picker):
    pieces = []
    for char in text:
        font = next((f for f, xref in originals if picker.has(f, xref, char)), fallback)
        if pieces and pieces[-1][1] is font:
            pieces[-1][0] += char
        else:
            pieces.append([char, font])
    return pieces


def layout_runs(op, picker):
    family = op.get('family') or 'original'
    tokens = []
    for run in op.get('runs') or []:
        if not run.get('t'):
            continue
        bold, italic = bool(run.get('b')), bool(run.get('i'))
        kind = family if family in GENERIC_FONTS else run.get('k')
        fallback = picker.generic(kind, bold, italic)
        originals = picker.originals(run) if family == 'original' else []
        size = max(1.0, min(400.0, float(run.get('s') or 12)))
        for part in re.split(r'(\n| +)', str(run['t'])):
            if not part:
                continue
            if part == '\n':
                tokens.append(None)
                continue
            if part.isspace():
                width = space_width(originals[0][0] if originals else fallback, size, kind == 'mono') * len(part)
                tokens.append({'pieces': [], 'run': run, 'size': size, 'space': True, 'width': width})
                continue
            pieces = split_pieces(part, originals, fallback, picker)
            width = sum(font.text_length(text, fontsize=size) for text, font in pieces)
            tokens.append({'pieces': pieces, 'run': run, 'size': size, 'space': False, 'width': width})
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


def write_text(page, op, picker):
    rect = text_rect(page, op)
    tokens = layout_runs(op, picker)
    if not any(t and not t['space'] for t in tokens):
        return
    align = op.get('align') or 'left'
    lh = max(0.8, min(3.0, float(op.get('lh') or 1.2)))
    width = max(rect.width, 4)
    lines = wrap_tokens(tokens, width)
    first = next(t for t in tokens if t and not t['space'])
    baseline = float(op['baseline']) if op.get('baseline') is not None else rect.y0 + first['pieces'][0][1].ascender * first['size']
    writers = {}
    for index, (line, last) in enumerate(lines):
        while line and line[-1]['space']:
            line = line[:-1]
        size = max((t['size'] for t in line), default=first['size'])
        if index:
            baseline += lh * size
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
            if token['space']:
                x += token['width'] + gap_extra
                continue
            color = token['run'].get('c') or '#000000'
            writer = writers.setdefault(color, fitz.TextWriter(page.rect))
            for text, font in token['pieces']:
                writer.append((x, baseline), text, font=font, fontsize=token['size'])
                x += font.text_length(text, fontsize=token['size'])
    for color, writer in writers.items():
        writer.write_text(page, color=rgb(color))


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


def op_text(doc, page, op, picker):
    removes = [rect_of(r) for r in op.get('remove') or []]
    if removes:
        area = fitz.Rect(removes[0])
        for r in removes[1:]:
            area |= r
        area = (area + (-1, -1, 1, 1)) & page.rect
        before = page.get_pixmap(clip=area, matrix=fitz.Matrix(2, 2), alpha=False)
        for r in removes:
            page.add_redact_annot(shrink(r), fill=False)
        page.apply_redactions(**KEEP_GRAPHICS)
        cover = baked_background(page, area, before)
        if cover:
            page.draw_rect(area, color=None, fill=cover, overlay=True)
    if op.get('runs') and op.get('rect'):
        write_text(page, op, picker)


def image_pixmap(doc, xref):
    pix = fitz.Pixmap(doc, xref)
    smask = doc.xref_get_key(xref, 'SMask')
    if smask[0] == 'xref':
        try:
            pix = fitz.Pixmap(pix, fitz.Pixmap(doc, int(smask[1].split()[0])))
        except Exception:
            pass
    if pix.colorspace and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix


def rect_distance(a, b):
    return abs(a.x0 - b.x0) + abs(a.y0 - b.y0) + abs(a.x1 - b.x1) + abs(a.y1 - b.y1)


def find_image(page, xref, bbox):
    target = rect_of(bbox)
    infos = page.get_image_info(xrefs=True)
    scored = [(rect_distance(fitz.Rect(info['bbox']) & page.rect, target) - (0.5 if info['xref'] == xref else 0), i) for i, info in enumerate(infos)]
    score, index = min(scored, default=(99, -1))
    return infos[index] if score < 4 else None


def remove_image(doc, page, info):
    xref = info['xref']
    same = [i for i in page.get_image_info(xrefs=True) if i['xref'] == xref]
    names = [item[7] for item in page.get_images(full=True) if item[0] == xref]
    if same and names:
        index = min(range(len(same)), key=lambda i: rect_distance(fitz.Rect(same[i]['bbox']), fitz.Rect(info['bbox'])))
        page.clean_contents()
        xrefs = page.get_contents()
        if len(xrefs) == 1:
            stream = doc.xref_stream(xrefs[0])
            pattern = rb'/(?:' + b'|'.join(re.escape(n.encode()) for n in set(names)) + rb')\s+Do\b'
            found = list(re.finditer(pattern, stream))
            if len(found) == len(same):
                hit = found[index]
                doc.update_stream(xrefs[0], stream[:hit.start()] + stream[hit.end():])
                return
    page.draw_rect(fitz.Rect(info['bbox']) & page.rect, color=None, fill=(1, 1, 1), overlay=True)


def op_image(doc, page, op, picker):
    found = find_image(page, int(op.get('xref') or 0), op['remove']) if op.get('remove') else None
    pix = image_pixmap(doc, found['xref']) if found and op.get('rect') and not op.get('path') else None
    if found:
        remove_image(doc, page, found)
    if op.get('rect'):
        rect = rect_of(op['rect'])
        if op.get('path'):
            page.insert_image(rect, filename=op['path'], keep_proportion=False)
        elif pix:
            page.insert_image(rect, pixmap=pix, keep_proportion=False)


def op_annot(doc, page, op, picker):
    kind = op.get('kind')
    color = rgb(op.get('color'), (1, 0.85, 0) if kind == 'highlight' else (0.9, 0.1, 0.1))
    fill = rgb(op['fill']) if op.get('fill') else None
    width = max(0.2, min(30.0, float(op.get('width') or 2)))
    if kind in MARKUP_KINDS:
        quads = [rect_of(r).quad for r in op.get('rects') or []]
        if not quads:
            return
        annot = getattr(page, f'add_{kind}_annot')(quads)
        annot.set_colors(stroke=color)
    elif kind == 'ink':
        strokes = [[(float(x), float(y)) for x, y in stroke] for stroke in op.get('points') or [] if len(stroke) > 1]
        if not strokes:
            return
        annot = page.add_ink_annot(strokes)
        annot.set_colors(stroke=color)
        annot.set_border(width=width)
    elif kind in ('rect', 'ellipse'):
        rect = rect_of(op['rect'])
        annot = page.add_rect_annot(rect) if kind == 'rect' else page.add_circle_annot(rect)
        annot.set_colors(stroke=color, fill=fill)
        annot.set_border(width=width)
    elif kind in ('line', 'arrow'):
        x0, y0, x1, y1 = [float(v) for v in op['rect']]
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
        return
    if op.get('opacity') is not None:
        annot.set_opacity(max(0.05, min(1.0, float(op['opacity']))))
    annot.update()


def find_annot(page, rect):
    target = rect_of(rect)
    best, score = None, 3.0
    for annot in page.annots():
        if annot.type[1] in ('Popup', 'Link', 'Widget'):
            continue
        r = annot.rect
        diff = abs(r.x0 - target.x0) + abs(r.y0 - target.y0) + abs(r.x1 - target.x1) + abs(r.y1 - target.y1)
        if diff < score:
            best, score = annot, diff
    return best


def op_annot_edit(doc, page, op, picker):
    annot = find_annot(page, op['target'])
    if not annot:
        return
    if op.get('delete'):
        page.delete_annot(annot)
    elif op.get('rect') and annot.type[1] in MOVABLE_ANNOTS:
        annot.set_rect(rect_of(op['rect']))
        annot.update()


def op_whiteout(doc, page, op, picker):
    page.draw_rect(rect_of(op['rect']), color=None, fill=rgb(op.get('color'), (1, 1, 1)), overlay=True)


def op_redact(doc, page, op, picker):
    page.add_redact_annot(rect_of(op['rect']), fill=(0, 0, 0))
    page.apply_redactions()


def op_form(doc, page, op, picker):
    target = rect_of(op['rect']) if op.get('rect') else None
    for widget in page.widgets():
        if widget.field_name != op.get('name'):
            continue
        if target and abs(widget.rect.x0 - target.x0) + abs(widget.rect.y0 - target.y0) > 2:
            continue
        kind = WIDGET_TYPES.get(widget.field_type)
        value = op.get('value')
        if kind in ('checkbox', 'radio'):
            widget.field_value = widget.on_state() if value else 'Off'
        else:
            widget.field_value = '' if value is None else str(value)
        widget.update()
        doc.xref_set_key(doc.pdf_catalog(), 'AcroForm/NeedAppearances', 'true')


OPS = {
    'text': op_text, 'image': op_image, 'annot': op_annot, 'annot_edit': op_annot_edit,
    'whiteout': op_whiteout, 'redact': op_redact, 'form': op_form,
}


def apply_page_ops(doc, page, ops):
    prepare_page(page)
    picker = None
    for op in ops:
        handler = OPS.get(op.get('type'))
        if not handler:
            continue
        if op.get('type') == 'text' and picker is None:
            picker = FontPicker(doc, page)
        handler(doc, page, op, picker)
        if op.get('type') in ('text', 'image', 'redact'):
            page = doc.reload_page(page)
            picker = None
    return page


def group_ops(ops, page_count):
    pages = {}
    for op in ops or []:
        try:
            index = int(op.get('page'))
        except (TypeError, ValueError):
            continue
        if 0 <= index < page_count:
            pages.setdefault(index, []).append(op)
    return pages


def apply_ops(doc, ops):
    for index, page_ops in sorted(group_ops(ops, doc.page_count).items()):
        apply_page_ops(doc, doc[index], page_ops)


def render_preview(path, index, ops, width):
    with fitz.open(path) as doc:
        if doc.needs_pass or index < 0 or index >= doc.page_count:
            return None
        page = apply_page_ops(doc, doc[index], [op for op in ops or [] if op.get('page') == index])
        layout = page_layout(doc.reload_page(page))
        page = doc[index]
        zoom = max(0.05, min(5.0, width / max(1.0, page.rect.width)))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        layout['image'] = 'data:image/jpeg;base64,' + base64.b64encode(pix.tobytes(output='jpeg', jpg_quality=85)).decode()
        return layout


def web_font(path, xref):
    with fitz.open(path) as doc:
        if xref <= 0 or xref >= doc.xref_length():
            return None
        try:
            _name, ext, _type, buffer = doc.extract_font(xref)
        except Exception:
            return None
        return (ext, buffer) if ext in ('ttf', 'otf') and buffer else None


def page_sizes(path):
    with fitz.open(path) as doc:
        sizes = []
        for page in doc:
            rect = page.rect
            sizes.append([round(rect.width, 2), round(rect.height, 2)])
        return sizes
