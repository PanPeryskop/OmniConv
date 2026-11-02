import re

DELIMITERS = b'()<>[]{}/%'
WHITESPACE = b' \t\r\n\f\x00'
TEXT_OPS = {b'Tj', b'TJ', b"'", b'"'}
PAINT_OPS = {b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*', b'S', b's', b'sh', b'Do', b'BI', b'BI?'}
MCID_RE = re.compile(rb'/MCID\s+(\d+)')


def literal_end(data, i):
    depth = 0
    while i < len(data):
        c = data[i]
        if c == 0x5C:
            i += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


COMPONENTS = {b'G': 1, b'DeviceGray': 1, b'RGB': 3, b'DeviceRGB': 3, b'CMYK': 4, b'DeviceCMYK': 4, b'I': 1, b'Indexed': 1}
EI_RE = re.compile(rb'\sEI(?=\s|$)')


def inline_value(header, *names):
    for name in names:
        match = re.search(rb'/' + name + rb'\s*(\[[^\]]*\]|/?[^\s/\[]+)', header)
        if match:
            return match.group(1).lstrip(b'/').strip(b'[]').split()[0] if match.group(1).startswith(b'[') else match.group(1).lstrip(b'/')
    return None


def inline_image_end(data, i):
    start = data.find(b'ID', i)
    if start < 0:
        return len(data), False
    header = data[i:start]
    body = start + 3
    if inline_value(header, b'F', b'Filter') is None:
        try:
            width = int(inline_value(header, b'W', b'Width'))
            height = int(inline_value(header, b'H', b'Height'))
            mask = inline_value(header, b'IM', b'ImageMask') == b'true'
            bits = 1 if mask else int(inline_value(header, b'BPC', b'BitsPerComponent') or 8)
            components = 1 if mask else COMPONENTS.get(inline_value(header, b'CS', b'ColorSpace') or b'G')
            if components:
                match = EI_RE.match(data, body + height * ((width * components * bits + 7) // 8))
                if match:
                    return match.end(), True
        except (TypeError, ValueError):
            pass
    match = EI_RE.search(data, body)
    return (match.end() if match else len(data)), False


def tokens(data):
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        if c in WHITESPACE:
            i += 1
        elif c == 0x25:
            end = data.find(b'\n', i)
            i = n if end < 0 else end
        elif c == 0x28:
            end = literal_end(data, i)
            yield 'operand', data[i:end], i
            i = end
        elif data.startswith(b'<<', i) or data.startswith(b'>>', i):
            yield 'operand', data[i:i + 2], i
            i += 2
        elif c == 0x3C:
            close = data.find(b'>', i)
            end = n if close < 0 else close + 1
            yield 'operand', data[i:end], i
            i = end
        elif c in b'[]{}':
            yield 'operand', data[i:i + 1], i
            i += 1
        else:
            j = i + 1
            while j < n and data[j] not in WHITESPACE and data[j] not in DELIMITERS:
                j += 1
            word = data[i:j]
            if c == 0x2F or re.fullmatch(rb'[+-]?(\d+\.?\d*|\.\d+)', word) or word in (b'true', b'false', b'null'):
                yield 'operand', word, i
            elif word == b'BI':
                end, exact = inline_image_end(data, j)
                yield 'operator', b'BI' if exact else b'BI?', i
                i = end
                continue
            else:
                yield 'operator', word, i
            i = j


def sequences(data):
    found, stack, operands_start = [], [], None
    for kind, value, offset in tokens(data):
        if kind == 'operand':
            if operands_start is None:
                operands_start = offset
            continue
        start = offset if operands_start is None else operands_start
        operands_start = None
        if value in (b'BDC', b'BMC'):
            head = data[start:offset]
            tag = re.match(rb'\s*/([^\s/<\[]+)', head)
            mcid = MCID_RE.search(head) if value == b'BDC' else None
            stack.append({'start': start, 'tag': tag.group(1).decode('latin-1') if tag else 'Span',
                          'mcid': int(mcid.group(1)) if mcid else None, 'text': False, 'paint': False})
        elif value == b'EMC' and stack:
            item = stack.pop()
            item['end'] = offset + 3
            found.append(item)
        elif value in TEXT_OPS:
            for item in stack:
                item['text'] = True
        elif value in PAINT_OPS:
            for item in stack:
                item['paint'] = True
    return found


def reliable(data):
    return all(value != b'BI?' for kind, value, _offset in tokens(data) if kind == 'operator')


def text_ids(data):
    return {s['mcid']: s['tag'] for s in sequences(data) if s['text'] and s['mcid'] is not None}


def without_sequence(data, mcid):
    matches = [s for s in sequences(data) if s['mcid'] == mcid]
    if not matches or any(s['text'] or s['paint'] for s in matches):
        return None
    for item in sorted(matches, key=lambda s: -s['start']):
        data = data[:item['start']] + data[item['end']:]
    return data


def is_tagged(doc, page):
    return doc.xref_get_key(page.xref, 'StructParents')[0] != 'null'


def contents(page):
    xrefs = page.get_contents()
    return xrefs, b'\n'.join(page.parent.xref_stream(x) or b'' for x in xrefs)


def detach(page, before):
    doc = page.parent
    page.clean_contents()
    xrefs, data = contents(page)
    removed = [m for m in before if m not in text_ids(data)]
    if not removed or len(xrefs) != 1 or not reliable(data):
        return None
    mcid = min(removed)
    cleaned = without_sequence(data, mcid)
    if cleaned is None:
        return None
    doc.update_stream(xrefs[0], cleaned)
    return mcid, before[mcid]


def attach(page, marker, previous):
    mcid, tag = marker
    doc = page.parent
    current = page.get_contents()
    last_old = max((i for i, x in enumerate(current) if x in previous), default=-1)
    added = current[last_old + 1:]
    if not added:
        return
    first, last = added[0], added[-1]
    doc.update_stream(first, f'/{tag} <</MCID {mcid}>> BDC\n'.encode() + doc.xref_stream(first))
    doc.update_stream(last, doc.xref_stream(last) + b'\nEMC\n')
