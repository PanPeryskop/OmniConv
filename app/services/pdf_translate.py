import os
import threading

import fitz

from . import pdf_ai
from .pdf_editor import PreviewCache

NEIGHBOUR_CHARS = 400
GLOSSARY_PAGES = 5
GLOSSARIES = PreviewCache(limit=32)
LOCKS = {}
LOCKS_GUARD = threading.Lock()


def clean(text):
    return '\n'.join(line.strip() for line in (text or '').splitlines() if line.strip())


def tail(text, limit=NEIGHBOUR_CHARS):
    text = clean(text)
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    start = min((cut.find(mark) for mark in ('\n', '. ') if cut.find(mark) >= 0), default=-1)
    return cut[start + 1:].strip() if 0 <= start < limit // 2 else cut.strip()


def head(text, limit=NEIGHBOUR_CHARS):
    text = clean(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind('\n'), cut.rfind('. '))
    return cut[:end + 1].strip() if end > limit // 2 else cut.strip()


def neighbours(doc, index):
    before = tail(doc[index - 1].get_text()) if 0 < index <= doc.page_count else ''
    after = head(doc[index + 1].get_text()) if 0 <= index < doc.page_count - 1 else ''
    return before, after


def glossary_source(doc):
    parts, size = [], 0
    for page in doc.pages(0, min(GLOSSARY_PAGES, doc.page_count)):
        text = clean(page.get_text())
        parts.append(text)
        size += len(text)
        if size >= pdf_ai.MAX_GLOSSARY_SOURCE:
            break
    return '\n\n'.join(parts)[:pdf_ai.MAX_GLOSSARY_SOURCE]


def glossary_key(path, language):
    stat = os.stat(path)
    return (path, stat.st_ino, stat.st_size, language.strip().lower())


def glossary(doc, path, language):
    key = glossary_key(path, language)
    cached = GLOSSARIES.get(key)
    if cached is not None:
        return cached
    with LOCKS_GUARD:
        lock = LOCKS.setdefault(key, threading.Lock())
    with lock:
        cached = GLOSSARIES.get(key)
        if cached is None:
            cached = pdf_ai.build_glossary(glossary_source(doc), language)
            if cached is not None:
                GLOSSARIES.put(key, cached)
    with LOCKS_GUARD:
        LOCKS.pop(key, None)
    return cached or []


def has_glossary(path, language):
    return GLOSSARIES.get(glossary_key(path, language)) is not None


def page_context(path, index, language):
    with fitz.open(path) as doc:
        before, after = neighbours(doc, index)
        terms = glossary(doc, path, language)
    return pdf_ai.TranslationContext(before=before, after=after, glossary=list(terms))
