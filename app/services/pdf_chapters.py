import re
import statistics
from collections import Counter
from dataclasses import dataclass

import fitz

MAX_PAGES = 3000
SAMPLE_PAGES = 80
TOP_SHARE = 0.45
HEAD_LINES = 4
HEADING_RATIO = 1.35
MAX_HEADING_CHARS = 90
MAX_TITLE_CHARS = 120
REPEAT_SHARE = 0.3
EMPTY_PAGE_CHARS = 80
MIN_SCORE = 3
KEYWORD_RE = re.compile(
    r'^(rozdzia[lł]|cz[eę][sś][cć]|ksi[eę]ga|chapter|part|book|kapitel|teil|abschnitt)\s+'
    r'([0-9]{1,3}|[ivxlcdm]{1,7}|[^\W\d_]+)\b[\s.:\u2013\u2014-]*(.*)$',
    re.I,
)
NUMBERED_RE = re.compile(r'^\d{1,2}[.)]?\s+\S')
TOC_TITLE_RE = re.compile(r'^(spis\s+tre[sś]ci|tre[sś][cć]|contents|table\s+of\s+contents|inhalt|inhaltsverzeichnis)$', re.I)
TOC_ENTRY_RE = re.compile(r'(\.{3,}|…|\s)\s*\d{1,4}$')
DIGITS_RE = re.compile(r'\d+')


class ChapterError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass
class Line:
    text: str
    size: float
    top: float
    bold: bool


def page_lines(page):
    height = page.rect.height or 1
    lines = []
    for block in page.get_text('dict', flags=fitz.TEXT_MEDIABOX_CLIP)['blocks']:
        for line in block.get('lines', []):
            if tuple(round(v) for v in line.get('dir', (1, 0))) != (1, 0):
                continue
            spans = [s for s in line['spans'] if s['text'].strip()]
            if not spans:
                continue
            text = ' '.join(''.join(s['text'] for s in spans).split())
            size = max(s['size'] for s in spans)
            bold = any(s['flags'] & 16 or 'bold' in s['font'].lower() for s in spans)
            lines.append(Line(text, round(size, 1), line['bbox'][1] / height, bold))
    lines.sort(key=lambda item: item.top)
    return lines


def normalized(text):
    return DIGITS_RE.sub('#', text.lower()).strip()


def body_size(pages):
    sizes = Counter()
    step = max(1, len(pages) // SAMPLE_PAGES)
    for lines in pages[::step]:
        for line in lines:
            sizes[line.size] += len(line.text)
    if not sizes:
        return 0
    return statistics.median(sizes.elements())


def running_lines(pages):
    counts = Counter()
    for lines in pages:
        counts.update({normalized(line.text) for line in lines})
    limit = max(3, len(pages) * REPEAT_SHARE)
    return {text for text, count in counts.items() if count >= limit}


def toc_page(lines):
    if any(TOC_TITLE_RE.match(line.text) for line in lines[:HEAD_LINES]):
        return True
    entries = sum(1 for line in lines if TOC_ENTRY_RE.search(line.text))
    return entries >= 6 and entries >= len(lines) * 0.4


def heading(lines, index, body, previous_chars):
    tops = [line for line in lines if line.top < TOP_SHARE][:HEAD_LINES]
    best = None
    for position, line in enumerate(tops):
        if len(line.text) > MAX_HEADING_CHARS:
            continue
        keyword = KEYWORD_RE.match(line.text)
        big = body and line.size >= body * HEADING_RATIO
        score = 0
        if keyword:
            score += 3 + (1 if big else 0)
        elif big:
            score += 2
        if big and NUMBERED_RE.match(line.text):
            score += 1
        if position == 0:
            score += 1
            if previous_chars < EMPTY_PAGE_CHARS and index:
                score += 1
        if line.bold:
            score += 0.5
        if score >= MIN_SCORE and (not best or score > best[0]):
            best = (score, position, line, bool(keyword))
    if not best:
        return None
    _score, position, line, keyword = best
    title = line.text
    following = tops[position + 1] if position + 1 < len(tops) else None
    if following and len(following.text) <= MAX_HEADING_CHARS and body and following.size >= body * HEADING_RATIO:
        if keyword and not KEYWORD_RE.match(line.text).group(3):
            title = f'{title} - {following.text}'
        elif not keyword and following.size == line.size:
            title = f'{title} {following.text}'
    return {'page': index, 'title': title[:MAX_TITLE_CHARS], 'size': line.size, 'keyword': keyword}


def chapters_from_headings(doc):
    count = min(doc.page_count, MAX_PAGES)
    pages = [page_lines(doc[i]) for i in range(count)]
    body = body_size(pages)
    running = running_lines(pages) if count >= 4 else set()
    found = []
    previous_chars = 0
    for index, lines in enumerate(pages):
        kept = [line for line in lines if normalized(line.text) not in running]
        if kept and not toc_page(kept):
            candidate = heading(kept, index, body, previous_chars)
            if candidate:
                found.append(candidate)
        previous_chars = sum(len(line.text) for line in kept)
    labelled = [c for c in found if c['keyword']]
    if len(labelled) >= 2:
        found = labelled
    else:
        sizes = Counter(round(c['size']) for c in found if c['page'])
        tier = next((size for size in sorted(sizes, reverse=True) if sizes[size] >= 2), None)
        found = [c for c in found if tier and round(c['size']) >= tier] if tier else []
    if len(found) > max(2, count * 0.6):
        return []
    return [(c['page'], c['title']) for c in found]


def chapters_from_bookmarks(doc, level):
    entries = []
    for depth, title, page in doc.get_toc(simple=True):
        if depth <= level and 0 < page <= doc.page_count:
            entries.append((page - 1, ' '.join(str(title).split())[:MAX_TITLE_CHARS]))
    return entries


def ranges(starts, page_count):
    titles = {}
    for start, title in starts:
        titles.setdefault(start, title)
    begins = sorted(titles)
    if not begins or begins[0] != 0:
        begins.insert(0, 0)
        titles.setdefault(0, '')
    return [
        {'start': begin, 'end': (begins[i + 1] if i + 1 < len(begins) else page_count) - 1, 'title': titles[begin]}
        for i, begin in enumerate(begins)
    ]


def detect(path, level=1, source='auto'):
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise ChapterError('err_pdf_damaged', 'The PDF could not be opened') from e
    with doc:
        if doc.needs_pass:
            raise ChapterError('err_pdf_encrypted', 'The PDF is password protected')
        toc = doc.get_toc(simple=True)
        levels = max((depth for depth, *_ in toc), default=0)
        level = max(1, min(int(level or 1), max(levels, 1)))
        starts, used = [], 'none'
        if source in ('auto', 'bookmarks') and toc:
            starts, used = chapters_from_bookmarks(doc, level), 'bookmarks'
        if not starts and source in ('auto', 'headings'):
            starts, used = chapters_from_headings(doc), 'headings'
        if not starts:
            used = 'none'
        sample = range(min(doc.page_count, 30))
        text_pages = sum(1 for i in sample if doc[i].get_text().strip())
        return {
            'source': used, 'levels': levels, 'level': level, 'pages': doc.page_count, 'bookmarks': bool(toc),
            'scanned': text_pages < max(1, len(sample)) * 0.3,
            'chapters': ranges(starts, doc.page_count) if starts else [{'start': 0, 'end': doc.page_count - 1, 'title': ''}],
        }


def groups_from_starts(items, page_count):
    starts = {}
    for item in items or []:
        try:
            start = int(item.get('start'))
        except (AttributeError, TypeError, ValueError):
            continue
        if 0 <= start < page_count:
            starts.setdefault(start, str(item.get('title') or '').strip()[:MAX_TITLE_CHARS])
    return ranges(list(starts.items()), page_count)
