import re
import threading
from collections import OrderedDict

import fitz
import pymupdf.mupdf as mupdf
import uharfbuzz as hb

RTL_RE = re.compile('[֐-ࣿיִ-﷿ﹰ-﻿]')
FEATURES = {'kern': True, 'liga': True, 'calt': True}


def is_rtl(text):
    return bool(RTL_RE.search(text))


def mostly_rtl(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if RTL_RE.match(c)) * 2 > len(letters)


class Shaper:
    def __init__(self, limit=64):
        self.limit = limit
        self.fonts = OrderedDict()
        self.lock = threading.Lock()

    def face(self, font):
        key = id(font)
        with self.lock:
            if key in self.fonts and self.fonts[key][0] is font:
                self.fonts.move_to_end(key)
                return self.fonts[key][1:]
        try:
            face = hb.Face(hb.Blob(font.buffer))
            entry = (font, hb.Font(face), face.upem or 1000)
        except Exception:
            entry = (font, None, 1000)
        with self.lock:
            self.fonts[key] = entry
            while len(self.fonts) > self.limit:
                self.fonts.popitem(last=False)
        return entry[1:]

    def shape(self, font, text):
        handle, upem = self.face(font)
        if handle is None or not text:
            return None
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(handle, buffer, FEATURES)
        infos, positions = buffer.glyph_infos, buffer.glyph_positions
        starts = sorted({info.cluster for info in infos})
        ends = {start: next((s for s in starts if s > start), len(text)) for start in starts}
        glyphs, seen = [], set()
        for info, pos in zip(infos, positions, strict=True):
            chars = '' if info.cluster in seen else text[info.cluster:ends[info.cluster]]
            seen.add(info.cluster)
            if info.codepoint == 0 and any(not c.isspace() and font.has_glyph(ord(c)) for c in chars):
                return None
            glyphs.append((info.codepoint, chars, pos.x_advance / upem, pos.x_offset / upem, pos.y_offset / upem))
        return glyphs


SHAPER = Shaper()


def advance(glyphs, size, spacing=0.0):
    return sum(g[2] * size + (spacing if g[1] else 0) for g in glyphs)


def append(writer, pos, font, size, glyphs, spacing=0.0):
    point = fitz.Point(pos) * writer.ictm
    rtl = any(is_rtl(g[1]) for g in glyphs)
    level, direction = (1, mupdf.FZ_BIDI_RTL) if rtl else (0, mupdf.FZ_BIDI_LTR)
    x = point.x
    for gid, chars, dx, ox, oy in glyphs:
        trm = mupdf.fz_make_matrix(size, 0, 0, size, x + ox * size, point.y + oy * size)
        mupdf.fz_show_glyph(writer.this, font.this, trm, gid, ord(chars[0]) if chars else -1, 0, level, direction, mupdf.FZ_LANG_UNSET)
        for extra in chars[1:]:
            mupdf.fz_show_glyph(writer.this, font.this, trm, -1, ord(extra), 0, level, direction, mupdf.FZ_LANG_UNSET)
        x += dx * size + (spacing if chars else 0)
    return x - point.x
