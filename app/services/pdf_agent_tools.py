import difflib
import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Callable

import fitz

from . import pdf_ai, pdf_editor
from .pdf_search import PATTERNS


@dataclass
class ToolContext:
    path: str
    file_id: str
    ops: list
    working_ops: list
    scope: dict
    emit: Callable = lambda event, data: None


@dataclass
class ToolResult:
    content: dict
    proposals: list = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable


def block_id(page, index, block):
    text = ''.join(span['t'] for line in block['lines'] for span in line['spans'])
    digest = hashlib.sha1((text + repr(block['bbox'])).encode('utf-8')).hexdigest()[:6]
    return f'p{page}b{index}-{digest}'


def page_base(ops, page):
    page_ops = [op for op in ops if op.get('page') == page]
    return {'count': len(page_ops), 'last_g': page_ops[-1].get('g') if page_ops else None}


def make_proposal(kind, page, title, ops, base, before='', after='', reason='', rects=None, depends_on=None):
    return {
        'id': 'prp_' + secrets.token_urlsafe(8), 'kind': kind, 'page': page, 'title': title, 'reason': reason,
        'before': before, 'after': after, 'rects': rects or [], 'ops': ops, 'base': base, 'depends_on': depends_on or [],
    }


TOOLS = {}


def register(spec):
    TOOLS[spec.name] = spec
    return spec


def tool_specs():
    return list(TOOLS.values())


BLOCK_RE = re.compile(r'^p(\d+)b(\d+)-[0-9a-f]{6}$')
COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
ALIGNS = ('left', 'center', 'right', 'justify')
HIGHLIGHT = '#ffd400'
NOTE_COLOR = '#f59e0b'
DEFAULT_RUN = {'s': 12, 'c': '#000000', 'b': False, 'i': False, 'f': 0, 'k': 'sans', 'cs': 0, 'rise': 0, 'lib': ''}
MAX_LIST_PAGES = 60
MAX_MATCHES = 40
MAX_PROOFREAD_BLOCKS = 15
MAX_TRANSLATE_PAGES = 3
MIN_SIMILARITY = 0.6
MESSAGES = {
    'stale_block': 'Unknown or outdated block id. Call read_page again and use the new ids.',
    'out_of_scope': 'This page is outside the scope chosen by the user. Work only on the allowed pages.',
    'no_page': 'This page does not exist. Call list_pages to see the page ids.',
    'ocr_pending': 'Text recognition is still running on this page. Try again later.',
    'no_change': 'The result is the same as the current state, nothing to propose.',
}
PAGE = {'type': 'integer', 'description': 'Page id from list_pages. The first page is 0.'}
PAGES = {
    'type': 'array', 'items': {'type': 'integer'},
    'description': 'Page ids from list_pages, e.g. [0, 1]. Leave out to use every page in scope.',
}
BLOCK = {'type': 'string', 'description': 'Block id from read_page, e.g. "p0b3-a1b2c3".'}
QUERY = {'type': 'string', 'description': 'Exact text to find, e.g. "Jan Kowalski". Case is ignored.'}
PATTERN_LIST = {
    'type': 'array', 'items': {'type': 'string', 'enum': list(PATTERNS)},
    'description': 'Built-in detectors for personal data, e.g. ["pesel", "iban"].',
}
POINT = 'in PDF points from the top-left corner of the page'


class ToolError(Exception):
    def __init__(self, code, message=''):
        super().__init__(message or code)
        self.code = code
        self.message = message or MESSAGES.get(code, '')


def guarded(handler):
    def run(ctx, args=None):
        try:
            return handler(ctx, dict(args) if isinstance(args, dict) else {})
        except ToolError as e:
            return ToolResult({'error': e.code, 'message': e.message})
        except pdf_ai.AiError as e:
            return ToolResult({'error': e.code, 'message': str(e)})
    return run


def tool(name, description, properties=None, required=()):
    def wrap(handler):
        parameters = {'type': 'object', 'properties': properties or {}, 'required': list(required)}
        register(ToolSpec(name, description, parameters, guarded(handler)))
        return handler
    return wrap


def run_tool(ctx, name, args):
    spec = TOOLS.get(name)
    if not spec:
        return ToolResult({'error': 'unknown_tool', 'message': 'Use one of: ' + ', '.join(TOOLS)})
    return spec.handler(ctx, args)


def as_int(args, key, default=None):
    value = args.get(key, default)
    if value is None or isinstance(value, bool):
        raise ToolError('bad_args', f'"{key}" must be a whole number.')
    try:
        return int(float(value))
    except (TypeError, ValueError):
        raise ToolError('bad_args', f'"{key}" must be a whole number.') from None


def as_number(args, key):
    try:
        return round(float(args.get(key)), 2)
    except (TypeError, ValueError):
        raise ToolError('bad_args', f'"{key}" must be a number.') from None


def as_text(args, key, limit=pdf_ai.MAX_TEXT):
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError('bad_args', f'"{key}" must be a non-empty text.')
    return value.strip()[:limit]


def as_color(args, key, default):
    value = args.get(key) or default
    if not isinstance(value, str) or not COLOR_RE.match(value):
        raise ToolError('bad_args', f'"{key}" must be a hex color like "#ff0000".')
    return value.lower()


def as_patterns(args):
    value = args.get('patterns') or []
    names = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    names = [str(n).strip().lower() for n in names if str(n).strip()]
    unknown = [n for n in names if n not in PATTERNS]
    if unknown:
        raise ToolError('bad_args', 'Unknown patterns: ' + ', '.join(unknown) + '. Use: ' + ', '.join(PATTERNS))
    return names


def squash(text):
    return ' '.join(str(text).split())


def rounded(box):
    return [round(v, 1) for v in box]


def page_count(path):
    with fitz.open(path) as doc:
        return doc.page_count


def structure(ctx):
    count = page_count(ctx.path)
    order, _rotation, blanks = pdf_editor.page_structure(ctx.working_ops, count)
    return count, order, blanks


def scope_pages(ctx, order):
    scope = ctx.scope or {}
    kind = scope.get('kind') or 'document'
    if kind == 'document':
        return list(order)
    pages = {int(p) for p in scope.get('pages') or [] if isinstance(p, int) or str(p).isdigit()}
    if kind == 'selection' and not pages:
        pages = {int(m.group(1)) for m in (BLOCK_RE.match(str(b)) for b in scope.get('block_ids') or []) if m}
    return [p for p in order if p in pages]


def ops_for_page(ops, page, count):
    blank = page >= count
    return [op for op in ops if op.get('page') == page or (blank and op.get('type') == 'page' and op.get('action') == 'insert')]


def render(ctx, page, count):
    return pdf_editor.render_preview(ctx.path, page, ops_for_page(ctx.working_ops, page, count), 100)


def check_page(ctx, page):
    count, order, _blanks = structure(ctx)
    if page not in order:
        raise ToolError('no_page')
    if page not in scope_pages(ctx, order):
        raise ToolError('out_of_scope')
    return count, order


def load_page(ctx, page):
    count, _order = check_page(ctx, page)
    layout = render(ctx, page, count)
    if layout is None:
        raise ToolError('no_page')
    if layout.get('ocr_pending'):
        raise ToolError('ocr_pending')
    return layout


def as_pages(ctx, value):
    if value in (None, '', 'all', []):
        _count, order, _blanks = structure(ctx)
        pages = scope_pages(ctx, order)
        if not pages:
            raise ToolError('out_of_scope')
        return pages
    items = value if isinstance(value, list) else re.findall(r'\d+', value) if isinstance(value, str) else [value]
    pages = list(dict.fromkeys(as_int({'pages': item}, 'pages') for item in items))
    for page in pages:
        check_page(ctx, page)
    return pages


def find_block(ctx, value):
    match = BLOCK_RE.match(str(value or '').strip())
    if not match:
        raise ToolError('stale_block')
    page, index = int(match.group(1)), int(match.group(2))
    count, order, _blanks = structure(ctx)
    if page not in order:
        raise ToolError('stale_block')
    if page not in scope_pages(ctx, order):
        raise ToolError('out_of_scope')
    layout = render(ctx, page, count)
    if not layout or layout.get('ocr_pending') or index >= len(layout['blocks']):
        raise ToolError('stale_block')
    block = layout['blocks'][index]
    if block_id(page, index, block) != match.group(0):
        raise ToolError('stale_block')
    return page, index, block, layout


def selected_blocks(ctx, page, layout):
    scope = ctx.scope or {}
    items = list(enumerate(layout['blocks']))
    ids = set(scope.get('block_ids') or [])
    if scope.get('kind') != 'selection' or not ids:
        return items
    return [(i, b) for i, b in items if block_id(page, i, b) in ids]


def dominant(block):
    spans = [s for line in block['lines'] for s in line['spans']]
    return max(spans, key=lambda s: len(s['t'].strip()))


def block_info(page, index, block):
    span = dominant(block)
    return {
        'id': block_id(page, index, block), 'text': pdf_ai.block_text(block), 'bbox': rounded(block['bbox']),
        'size': round(span['s'], 1), 'bold': bool(span['b']), 'italic': bool(span['i']), 'color': span['c'], 'align': block['align'],
    }


def word_changes(before, after, limit=240):
    a, b = before.split(), after.split()
    parts = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        old, new = ' '.join(a[i1:i2]), ' '.join(b[j1:j2])
        parts.append(f'{old} → {new}' if old and new else f'+ {new}' if new else f'− {old}')
    text = ', '.join(parts)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def is_bullet(text):
    return all(c.isspace() or c in pdf_editor.BULLETS or 0xF000 <= ord(c) <= 0xF0FF for c in text)


def checkable(text):
    return pdf_ai.translatable(text) and not is_bullet(text) and len(text) <= pdf_ai.MAX_TEXT


def plausible(before, after):
    return difflib.SequenceMatcher(None, before, after, autojunk=False).ratio() >= MIN_SIMILARITY


def progress(ctx, name, done, total):
    ctx.emit('tool_progress', {'name': name, 'done': done, 'total': total})


def search_matches(ctx, args):
    query = str(args.get('query') or '').strip()[:200]
    kinds = as_patterns(args)
    if not query and not kinds:
        raise ToolError('bad_args', 'Give "query" or "patterns".')
    pages = as_pages(ctx, args.get('pages'))
    found, _truncated = pdf_editor.search_document(ctx.path, ctx.working_ops, query, kinds)
    wanted = set(pages)
    return [m for m in found if m['page'] in wanted]


def block_at(layout, page, rect):
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    for index, block in enumerate(layout['blocks']):
        x0, y0, x1, y1 = block['bbox']
        if x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1:
            return block_id(page, index, block)
    return None


def text_proposal(ctx, page, block, text, title, reason=''):
    before = pdf_ai.block_text(block)
    return make_proposal(
        'text', page, title, [pdf_ai.block_op(page, block, text)], page_base(ctx.ops, page),
        before=before, after=text, reason=reason or word_changes(before, text), rects=[block['bbox']],
    )


def proposed(proposals, **extra):
    return ToolResult(dict({'proposals': [p['id'] for p in proposals]}, **extra), proposals)


@tool(
    'list_pages',
    'List the pages of the document in reading order. Use the "page" id in other tools. '
    '"position" is the place in the document (0 = first page). Example: {}',
)
def list_pages(ctx, args):
    count, order, _blanks = structure(ctx)
    allowed = set(scope_pages(ctx, order))
    pages = []
    for position, page in enumerate(order[:MAX_LIST_PAGES]):
        layout = render(ctx, page, count)
        item = {'page': page, 'position': position, 'in_scope': page in allowed, 'edited': any(op.get('page') == page for op in ctx.working_ops)}
        if layout and not layout.get('ocr_pending'):
            item.update(width=layout['width'], height=layout['height'], blocks=len(layout['blocks']), scanned=layout['scanned'])
        else:
            item['ocr_pending'] = True
        pages.append(item)
    return ToolResult({'count': len(order), 'pages': pages, 'truncated': len(order) > MAX_LIST_PAGES})


@tool(
    'read_page',
    'Read the text blocks of one page with their ids, position (bbox ' + POINT + ') and style. '
    'Always call it before changing a page. Ids change when the page changes, so read again after edits. '
    'Example: {"page": 0}',
    {
        'page': PAGE,
        'max_chars': {'type': 'integer', 'description': 'Size limit of the answer. Default 6000.'},
        'start': {'type': 'integer', 'description': 'Index of the first block to return, to continue a truncated read. Default 0.'},
    },
    ['page'],
)
def read_page(ctx, args):
    page = as_int(args, 'page')
    layout = load_page(ctx, page)
    budget = max(500, min(20000, as_int(args, 'max_chars', 6000)))
    start = max(0, as_int(args, 'start', 0))
    blocks, used, following = [], 0, None
    for index, block in enumerate(layout['blocks'][start:], start):
        info = block_info(page, index, block)
        size = len(json.dumps(info, ensure_ascii=False))
        if used + size > budget:
            if not blocks:
                info['text'] = info['text'][:budget]
                blocks.append(info)
                index += 1
            following = index if index < len(layout['blocks']) else None
            break
        used += size
        blocks.append(info)
    content = {
        'page': page, 'width': layout['width'], 'height': layout['height'], 'scanned': layout['scanned'], 'blocks': blocks,
        'images': [rounded(i['bbox']) for i in layout['images'][:20]],
        'annots': [{'kind': a['kind'], 'rect': rounded(a['rect']), 'text': a['text'][:200]} for a in layout['annots'][:30]],
        'truncated': following is not None,
    }
    if following is not None:
        content['message'] = f'Only part of the page fits. Call read_page with page={page} and start={following} to read the rest.'
    return ToolResult(content)


@tool(
    'search',
    'Find text or personal data in the document. Returns each match with its page, text, rectangles and block_id. '
    'Example: {"query": "invoice"} or {"patterns": ["pesel", "email"], "pages": [0]}',
    {'query': QUERY, 'patterns': PATTERN_LIST, 'pages': PAGES},
)
def search(ctx, args):
    found = search_matches(ctx, args)
    layouts = {}
    matches = []
    for match in found[:MAX_MATCHES]:
        page = match['page']
        if page not in layouts:
            layouts[page] = load_page(ctx, page)
        rects = [rounded(r) for r in match['rects']]
        matches.append({'page': page, 'text': match['text'], 'kind': match['kind'], 'rects': rects, 'block_id': block_at(layouts[page], page, rects[0])})
    return ToolResult({'matches': matches, 'total': len(found), 'truncated': len(found) > MAX_MATCHES})


@tool(
    'replace_text',
    'Propose new text for one block. Give the full new text of the block, not only the changed words. '
    'Example: {"block_id": "p0b3-a1b2c3", "text": "New sentence.", "reason": "Shorter wording"}',
    {
        'block_id': BLOCK,
        'text': {'type': 'string', 'description': 'The complete new text of the block.'},
        'reason': {'type': 'string', 'description': 'Short reason shown to the user.'},
    },
    ['block_id', 'text'],
)
def replace_text(ctx, args):
    page, _index, block, _layout = find_block(ctx, args.get('block_id'))
    text = as_text(args, 'text')
    if squash(text) == squash(pdf_ai.block_text(block)):
        raise ToolError('no_change')
    proposal = text_proposal(ctx, page, block, text, 'Replace text', str(args.get('reason') or '').strip()[:300])
    return proposed([proposal])


@tool(
    'proofread',
    'Fix spelling, grammar and punctuation on whole pages. Checks every text block and proposes only blocks with mistakes. '
    'Prefer this over replace_text for typos. Example: {"pages": [0]} or {"pages": [0, 1], "language": "Polish"}',
    {
        'pages': PAGES,
        'language': {'type': 'string', 'description': 'Language of the text, e.g. "Polish". Optional.'},
        'start': {'type': 'integer', 'description': 'Block index to start from on the first page, to continue a truncated run. Default 0.'},
    },
)
def proofread(ctx, args):
    pages = as_pages(ctx, args.get('pages'))
    language = str(args.get('language') or '').strip()[:40]
    start = max(0, as_int(args, 'start', 0))
    work = []
    for n, page in enumerate(pages):
        layout = load_page(ctx, page)
        for index, block in selected_blocks(ctx, page, layout):
            if (n or index >= start) and checkable(pdf_ai.block_text(block)):
                work.append((n, page, index, block))
    proposals, changes, error, checked = [], [], None, 0
    batch = work[:MAX_PROOFREAD_BLOCKS]
    for _n, page, index, block in batch:
        progress(ctx, 'proofread', checked, len(batch))
        text = pdf_ai.block_text(block)
        try:
            fixed = pdf_ai.fix_text(text, language or None).strip()
        except pdf_ai.AiError as e:
            error = e
            break
        checked += 1
        if not fixed or squash(fixed) == squash(text) or not plausible(text, fixed):
            continue
        proposal = text_proposal(ctx, page, block, fixed, 'Fix typos')
        proposals.append(proposal)
        changes.append({'block_id': block_id(page, index, block), 'changes': proposal['reason']})
    content = {'checked': checked, 'changes': changes, 'truncated': len(work) > MAX_PROOFREAD_BLOCKS}
    if error is not None:
        content.update(error=error.code, message=str(error))
    elif content['truncated']:
        n, page, index, _block = work[MAX_PROOFREAD_BLOCKS]
        rest = pages[n:]
        content['message'] = f'Stopped after {MAX_PROOFREAD_BLOCKS} blocks. Call proofread with pages={rest} and start={index} to continue.'
    progress(ctx, 'proofread', checked, checked)
    return proposed(proposals, **content)


def styled_runs(block, size, color, bold, italic):
    scale = size / (dominant(block)['s'] or 12) if size else 1
    runs = []
    for n, line in enumerate(block['lines']):
        spans = [dict(s) for s in line['spans']]
        spans[0]['t'] = spans[0]['t'].lstrip()
        spans[-1]['t'] = spans[-1]['t'].rstrip()
        if n + 1 < len(block['lines']):
            spans[-1]['t'] += '\n' if line['brk'] else ' '
        for span in spans:
            if size:
                span['s'] = round(span['s'] * scale, 2)
                span['rise'] = round((span.get('rise') or 0) * scale, 2)
            if color:
                span['c'] = color
            if bold is not None:
                span['b'] = bold
            if italic is not None:
                span['i'] = italic
        runs.extend(s for s in spans if s['t'])
    return runs


def as_flag(args, key):
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes')
    return bool(value)


@tool(
    'set_style',
    'Change the look of one block without changing its text. Give only what should change. '
    'Example: {"block_id": "p0b0-a1b2c3", "size": 18, "bold": true, "color": "#1d4ed8", "align": "center"}',
    {
        'block_id': BLOCK,
        'size': {'type': 'number', 'description': 'Font size in points, e.g. 12.'},
        'color': {'type': 'string', 'description': 'Text color as hex, e.g. "#ff0000".'},
        'bold': {'type': 'boolean'},
        'italic': {'type': 'boolean'},
        'align': {'type': 'string', 'enum': list(ALIGNS)},
    },
    ['block_id'],
)
def set_style(ctx, args):
    page, _index, block, _layout = find_block(ctx, args.get('block_id'))
    size = as_number(args, 'size') if args.get('size') is not None else None
    if size is not None and not 4 <= size <= 200:
        raise ToolError('bad_args', '"size" must be between 4 and 200.')
    color = as_color(args, 'color', '#000000') if args.get('color') else None
    bold, italic = as_flag(args, 'bold'), as_flag(args, 'italic')
    align = str(args.get('align') or '').strip().lower() or None
    if align and align not in ALIGNS:
        raise ToolError('bad_args', '"align" must be one of: ' + ', '.join(ALIGNS))
    span = dominant(block)
    changes = [
        f'size {size:g}' if size is not None and size != span['s'] else '',
        f'color {color}' if color and color != span['c'].lower() else '',
        ('bold' if bold else 'not bold') if bold is not None and bold != span['b'] else '',
        ('italic' if italic else 'not italic') if italic is not None and italic != span['i'] else '',
        f'align {align}' if align and align != block['align'] else '',
    ]
    changes = [c for c in changes if c]
    if not changes:
        raise ToolError('no_change')
    text = pdf_ai.block_text(block)
    op = dict(pdf_ai.block_op(page, block, text), runs=styled_runs(block, size, color, bold, italic), fit=False, align=align or block['align'])
    proposal = make_proposal('style', page, 'Change style', [op], page_base(ctx.ops, page), before=text, after=text, reason=', '.join(changes), rects=[block['bbox']])
    return proposed([proposal])


@tool(
    'insert_text',
    'Add new text at a point (x, y ' + POINT + '; y is the text baseline). '
    'Use like_block_id to copy font, size and color from an existing block. '
    'Example: {"page": 0, "x": 72, "y": 760, "text": "Approved", "like_block_id": "p0b2-a1b2c3"}',
    {
        'page': PAGE,
        'x': {'type': 'number', 'description': 'Left edge ' + POINT + '.'},
        'y': {'type': 'number', 'description': 'Baseline ' + POINT + '.'},
        'text': {'type': 'string'},
        'like_block_id': BLOCK,
    },
    ['page', 'x', 'y', 'text'],
)
def insert_text(ctx, args):
    page = as_int(args, 'page')
    layout = load_page(ctx, page)
    x, y = as_number(args, 'x'), as_number(args, 'y')
    if not (0 <= x < layout['width'] and 0 < y <= layout['height']):
        raise ToolError('bad_args', f'The point must be inside the page ({layout["width"]:g} x {layout["height"]:g}).')
    text = as_text(args, 'text')
    if args.get('like_block_id'):
        _page, _index, like, _layout = find_block(ctx, args['like_block_id'])
        run, family, lh = dict(dominant(like), t=text, rise=0), 'original', like['lh']
    else:
        run, family, lh = dict(DEFAULT_RUN, t=text), 'sans', 1.2
    size = run['s']
    rect = [x, round(y - size * 0.9, 2), round(x + size * 6, 2), round(y + size * 0.3, 2)]
    op = {'type': 'text', 'page': page, 'remove': [], 'rect': rect, 'baseline': y, 'lh': lh, 'align': 'left', 'family': family, 'grow': True, 'runs': [run]}
    proposal = make_proposal('insert', page, 'Insert text', [op], page_base(ctx.ops, page), after=text, reason=text[:120], rects=[rect])
    return proposed([proposal])


@tool(
    'delete_text',
    'Remove one text block from the page. Example: {"block_id": "p0b4-a1b2c3"}',
    {'block_id': BLOCK},
    ['block_id'],
)
def delete_text(ctx, args):
    page, _index, block, _layout = find_block(ctx, args.get('block_id'))
    text = pdf_ai.block_text(block)
    op = dict(pdf_ai.block_op(page, block, ''), runs=[])
    proposal = make_proposal('delete', page, 'Delete text', [op], page_base(ctx.ops, page), before=text, reason=text[:120], rects=[block['bbox']])
    return proposed([proposal])


@tool(
    'highlight',
    'Highlight text with a marker: every match of "query" on the page, or a whole block. '
    'Example: {"page": 0, "query": "deadline"} or {"block_id": "p0b2-a1b2c3", "color": "#86efac"}',
    {
        'page': PAGE, 'query': QUERY, 'block_id': BLOCK,
        'color': {'type': 'string', 'description': 'Marker color as hex. Default "#ffd400" (yellow).'},
    },
)
def highlight(ctx, args):
    color = as_color(args, 'color', HIGHLIGHT)
    if args.get('block_id'):
        page, _index, block, _layout = find_block(ctx, args['block_id'])
        rects, text = [line['bbox'] for line in block['lines']], pdf_ai.block_text(block)
    else:
        page = as_int(args, 'page')
        query = as_text(args, 'query', 200)
        found = search_matches(ctx, {'query': query, 'pages': [page]})
        rects = [r for m in found for r in m['rects']]
        text = query
        if not rects:
            return ToolResult({'matches': 0, 'proposals': [], 'message': f'"{query}" was not found on page {page}.'})
    op = {'type': 'annot', 'page': page, 'kind': 'highlight', 'rects': rects, 'color': color}
    proposal = make_proposal('annot', page, 'Highlight', [op], page_base(ctx.ops, page), reason=text[:120], rects=rects)
    return proposed([proposal], matches=len(rects))


@tool(
    'add_note',
    'Add a sticky note (comment) at a point (x, y ' + POINT + '). Example: {"page": 0, "x": 500, "y": 60, "text": "Check this date"}',
    {
        'page': PAGE,
        'x': {'type': 'number', 'description': 'X ' + POINT + '.'},
        'y': {'type': 'number', 'description': 'Y ' + POINT + '.'},
        'text': {'type': 'string'},
    },
    ['page', 'x', 'y', 'text'],
)
def add_note(ctx, args):
    page = as_int(args, 'page')
    layout = load_page(ctx, page)
    x, y = as_number(args, 'x'), as_number(args, 'y')
    if not (0 <= x <= layout['width'] and 0 <= y <= layout['height']):
        raise ToolError('bad_args', f'The point must be inside the page ({layout["width"]:g} x {layout["height"]:g}).')
    text = as_text(args, 'text', 2000)
    rect = [x, y, round(x + 20, 2), round(y + 20, 2)]
    op = {'type': 'annot', 'page': page, 'kind': 'note', 'rect': rect, 'text': text, 'color': NOTE_COLOR}
    proposal = make_proposal('annot', page, 'Add note', [op], page_base(ctx.ops, page), after=text, reason=text[:120], rects=[rect])
    return proposed([proposal])


@tool(
    'redact',
    'Black out text permanently: matches of "query" and/or built-in personal data patterns. One proposal per page. '
    'Example: {"patterns": ["pesel", "iban"]} or {"query": "Jan Kowalski", "pages": [1]}',
    {'query': QUERY, 'patterns': PATTERN_LIST, 'pages': PAGES},
)
def redact(ctx, args):
    found = search_matches(ctx, args)
    by_page = {}
    for match in found:
        by_page.setdefault(match['page'], []).append(match)
    proposals = []
    for page, matches in by_page.items():
        rects = [r for m in matches for r in m['rects']]
        kinds = {}
        for m in matches:
            kinds[m['kind']] = kinds.get(m['kind'], 0) + 1
        texts = ', '.join(dict.fromkeys(m['text'] for m in matches))
        reason = ', '.join(f'{n} × {kind}' for kind, n in kinds.items())
        op = {'type': 'redact', 'page': page, 'rects': rects}
        proposals.append(make_proposal('redact', page, 'Redact', [op], page_base(ctx.ops, page), before=texts[:500], reason=reason, rects=rects))
    content = {'matches': len(found), 'pages': list(by_page)}
    if not found:
        content['message'] = 'Nothing to redact was found.'
    return proposed(proposals, **content)


@tool(
    'translate',
    'Translate whole pages into another language. One proposal per page. '
    'Example: {"pages": [0, 1], "language": "English"}',
    {'pages': PAGES, 'language': {'type': 'string', 'description': 'Target language, e.g. "English".'}},
    ['language'],
)
def translate(ctx, args):
    pages = as_pages(ctx, args.get('pages'))
    language = as_text(args, 'language', 40)
    proposals, done = [], []
    for page in pages[:MAX_TRANSLATE_PAGES]:
        layout = load_page(ctx, page)
        progress(ctx, 'translate', len(done), min(len(pages), MAX_TRANSLATE_PAGES))
        blocks = [b for _i, b in selected_blocks(ctx, page, layout) if pdf_ai.translatable(pdf_ai.block_text(b))]
        ops = pdf_ai.translate_page(dict(layout, blocks=blocks), page, language) if blocks else []
        done.append(page)
        if not ops:
            continue
        before = '\n\n'.join(pdf_ai.block_text(b) for b in blocks)
        after = '\n\n'.join(op['runs'][0]['t'] for op in ops)
        proposals.append(make_proposal(
            'text', page, f'Translate to {language}', ops, page_base(ctx.ops, page),
            before=before, after=after, reason=f'{len(ops)} blocks → {language}', rects=[b['bbox'] for b in blocks],
        ))
    content = {'translated': done, 'truncated': len(pages) > MAX_TRANSLATE_PAGES}
    if content['truncated']:
        content['message'] = f'Translated {MAX_TRANSLATE_PAGES} pages. Call translate with pages={pages[MAX_TRANSLATE_PAGES:]} to continue.'
    progress(ctx, 'translate', len(done), len(done))
    return proposed(proposals, **content)


@tool(
    'page_action',
    'Rotate, delete or move a page, or insert a blank page after it. "to" is the target position (0 = first). '
    'Example: {"action": "rotate", "page": 0, "angle": 90} or {"action": "move", "page": 3, "to": 0}',
    {
        'action': {'type': 'string', 'enum': ['rotate', 'delete', 'move', 'insert_blank']},
        'page': PAGE,
        'to': {'type': 'integer', 'description': 'Target position for move or insert_blank.'},
        'angle': {'type': 'integer', 'enum': [90, 180, 270], 'description': 'Clockwise rotation. Default 90.'},
    },
    ['action', 'page'],
)
def page_action(ctx, args):
    action = str(args.get('action') or '').strip().lower()
    page = as_int(args, 'page')
    count, order = check_page(ctx, page)
    position = order.index(page)
    target = page
    if action == 'rotate':
        angle = as_int(args, 'angle', 90) % 360
        if angle not in (90, 180, 270):
            raise ToolError('bad_args', '"angle" must be 90, 180 or 270.')
        op, title, reason = {'type': 'page', 'action': 'rotate', 'page': page, 'angle': angle}, 'Rotate page', f'Page {position + 1}: {angle}°'
    elif action == 'delete':
        if len(order) < 2:
            raise ToolError('bad_args', 'The only page cannot be deleted.')
        op, title, reason = {'type': 'page', 'action': 'delete', 'page': page}, 'Delete page', f'Page {position + 1}'
    elif action == 'move':
        to = max(0, min(len(order) - 1, as_int(args, 'to')))
        if to == position:
            raise ToolError('no_change')
        op, title, reason = {'type': 'page', 'action': 'move', 'page': page, 'to': to}, 'Move page', f'Page {position + 1} → {to + 1}'
    elif action == 'insert_blank':
        _count, _order, blanks = structure(ctx)
        target = count + len(blanks)
        to = max(0, min(len(order), as_int(args, 'to', position + 1)))
        layout = render(ctx, page, count)
        size = [layout['width'], layout['height']] if layout and not layout.get('ocr_pending') else [595.0, 842.0]
        op = {'type': 'page', 'action': 'insert', 'page': target, 'to': to, 'size': size}
        title, reason = 'Insert blank page', f'New page at position {to + 1}'
    else:
        raise ToolError('bad_args', '"action" must be rotate, delete, move or insert_blank.')
    proposal = make_proposal('page', target, title, [op], page_base(ctx.ops, target), reason=reason)
    extra = {'new_page': target} if action == 'insert_blank' else {}
    return proposed([proposal], **extra)


@tool(
    'finish',
    'End your turn with a short summary for the user, in the user\'s language. Call it once, at the end. '
    'Example: {"summary": "I proposed 3 typo fixes on page 1."}',
    {'summary': {'type': 'string'}},
    ['summary'],
)
def finish(ctx, args):
    return ToolResult({'done': True, 'summary': str(args.get('summary') or '').strip()[:2000]})
