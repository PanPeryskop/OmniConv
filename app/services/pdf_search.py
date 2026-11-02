import re

import fitz

MAX_MATCHES = 2000


def digits(value):
    return [int(c) for c in value if c.isdigit()]


def valid_pesel(value):
    d = digits(value)
    if len(d) != 11:
        return False
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return (10 - sum(a * b for a, b in zip(d, weights, strict=False)) % 10) % 10 == d[10]


def valid_nip(value):
    d = digits(value)
    if len(d) != 10:
        return False
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    check = sum(a * b for a, b in zip(d, weights, strict=False)) % 11
    return check != 10 and check == d[9]


def valid_regon(value):
    d = digits(value)
    if len(d) == 9:
        weights = (8, 9, 2, 3, 4, 5, 6, 7)
    elif len(d) == 14:
        weights = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
    else:
        return False
    return sum(a * b for a, b in zip(d, weights, strict=False)) % 11 % 10 == d[-1]


def valid_iban(value):
    compact = re.sub(r'\s', '', value).upper()
    if not 15 <= len(compact) <= 34:
        return False
    rotated = compact[4:] + compact[:4]
    return int(''.join(str(int(c, 36)) for c in rotated)) % 97 == 1


def valid_card(value):
    d = digits(value)
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return total % 10 == 0


def valid_id_card(value):
    compact = re.sub(r'\s', '', value).upper()
    if not re.fullmatch(r'[A-Z]{3}\d{6}', compact):
        return False
    values = [ord(c) - 55 for c in compact[:3]] + [int(c) for c in compact[3:]]
    weights = (7, 3, 1, 9, 7, 3, 1, 7, 3)
    return sum(a * b for a, b in zip(values, weights, strict=True)) % 10 == 0


PATTERNS = {
    'pesel': (re.compile(r'(?<!\d)\d{11}(?!\d)'), valid_pesel),
    'nip': (re.compile(r'(?<![\d-])(?:PL ?)?\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}(?![\d-])'), valid_nip),
    'regon': (re.compile(r'(?<!\d)(?:\d{14}|\d{9})(?!\d)'), valid_regon),
    'iban': (re.compile(r'\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b'), valid_iban),
    'card': (re.compile(r'(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)'), valid_card),
    'id_card': (re.compile(r'\b[A-Z]{3} ?\d{6}\b'), valid_id_card),
    'email': (re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'), None),
    'date': (re.compile(r'\b(?:\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})|\d{4}-\d{2}-\d{2})\b'), None),
    'phone': (re.compile(r'(?<![\w+])(?:\+\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]?){2,4}\d{2,4}(?!\w)'), lambda v: 9 <= len(digits(v)) <= 15),
}


def page_chars(page):
    text, boxes = [], []
    for block in page.get_text('rawdict', flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP)['blocks']:
        if block['type'] != 0:
            continue
        for line in block['lines']:
            for span in line['spans']:
                for char in span['chars']:
                    text.append(char['c'])
                    boxes.append(char['bbox'])
            text.append('\n')
            boxes.append(None)
        text.append('\n')
        boxes.append(None)
    return ''.join(text), boxes


def match_rects(boxes, start, end):
    rects = []
    for box in boxes[start:end]:
        if box is None:
            continue
        rect = fitz.Rect(box)
        last = rects[-1] if rects else None
        if last and abs(last.y0 - rect.y0) < 1 and abs(last.y1 - rect.y1) < 1 and rect.x0 - last.x1 < rect.height:
            rects[-1] = last | rect
        else:
            rects.append(rect)
    return [[round(v, 2) for v in r] for r in rects if not r.is_empty]


def query_pattern(query, whole_word):
    escaped = re.escape(query.strip())
    escaped = re.sub(r'(\\ )+', r'\\s+', escaped)
    return re.compile(rf'(?<!\w){escaped}(?!\w)' if whole_word else escaped, re.IGNORECASE)


def search_page(page, query='', kinds=(), whole_word=False):
    text, boxes = page_chars(page)
    searches = []
    if query and query.strip():
        searches.append(('text', query_pattern(query, whole_word), None))
    searches += [(kind, *PATTERNS[kind]) for kind in PATTERNS if kind in kinds]
    found, taken = [], []
    for kind, pattern, check in searches:
        for match in pattern.finditer(text):
            value = match.group(0).strip()
            if not value or (check and not check(value)):
                continue
            span = (match.start(), match.end())
            if any(a < span[1] and span[0] < b for a, b in taken):
                continue
            rects = match_rects(boxes, *span)
            if rects:
                taken.append(span)
                found.append({'kind': kind, 'text': value, 'rects': rects})
    return found
