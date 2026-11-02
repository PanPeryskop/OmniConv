import io

import fitz
from fontTools.cffLib import CFFFontSet
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from fontTools.ttLib.tables.O_S_2f_2 import Panose

UNICODE_RANGES = (
    (0x20, 0x250), (0x2B0, 0x300), (0x370, 0x530), (0x1E00, 0x1F00),
    (0x2000, 0x2070), (0x20A0, 0x20D0), (0x2100, 0x2200), (0x2200, 0x2300), (0xFB00, 0xFB07),
)
UNITS = 1000


def unicode_map(font, order, inked):
    mapping = {}
    for start, stop in UNICODE_RANGES:
        for cp in range(start, stop):
            gid = font.has_glyph(cp)
            if 0 < gid < len(order) and (chr(cp).isspace() or inked(order[gid])):
                mapping[cp] = gid
    return mapping


def cff_inked(top):
    strings = top.CharStrings

    def inked(name):
        pen = BoundsPen(None)
        try:
            strings[name].draw(pen)
        except Exception:
            return False
        return pen.bounds is not None
    return inked


def glyf_inked(ttf):
    if 'glyf' not in ttf:
        return lambda name: True
    glyf = ttf['glyf']
    return lambda name: name in glyf and glyf[name].numberOfContours != 0


def cmap_table(mapping, order):
    table = newTable('cmap')
    table.tableVersion = 0
    subtable = CmapSubtable.newSubtable(4)
    subtable.platformID, subtable.platEncID, subtable.language = 3, 1, 0
    subtable.cmap = {cp: order[gid] for cp, gid in mapping.items()}
    table.tables = [subtable]
    return table


def name_table(family):
    table = newTable('name')
    table.names = []
    for name_id, value in ((1, family), (2, 'Regular'), (3, family), (4, family), (6, ''.join(c for c in family if c.isalnum()) or 'Font')):
        table.setName(value, name_id, 3, 1, 0x409)
    return table


def os2_table(upm, ascent, descent):
    table = newTable('OS/2')
    table.version = 4
    for attr in ('xAvgCharWidth', 'usWeightClass', 'usWidthClass', 'fsType', 'ySubscriptXSize', 'ySubscriptYSize',
                 'ySubscriptXOffset', 'ySubscriptYOffset', 'ySuperscriptXSize', 'ySuperscriptYSize', 'ySuperscriptXOffset',
                 'ySuperscriptYOffset', 'yStrikeoutSize', 'yStrikeoutPosition', 'sFamilyClass', 'ulUnicodeRange1',
                 'ulUnicodeRange2', 'ulUnicodeRange3', 'ulUnicodeRange4', 'fsSelection', 'usFirstCharIndex',
                 'usLastCharIndex', 'ulCodePageRange1', 'ulCodePageRange2', 'sxHeight', 'sCapHeight', 'usDefaultChar',
                 'usBreakChar', 'usMaxContext', 'sTypoLineGap'):
        setattr(table, attr, 0)
    table.panose = Panose()
    table.achVendID = 'NONE'
    table.usWeightClass = 400
    table.usWidthClass = 5
    table.fsSelection = 0x40
    table.usFirstCharIndex = 0x20
    table.usLastCharIndex = 0xFFFF
    table.ulUnicodeRange1 = 0x7
    table.ulCodePageRange1 = 0x3
    table.sTypoAscender, table.sTypoDescender = ascent, descent
    table.usWinAscent, table.usWinDescent = max(ascent, 0), max(-descent, 0)
    table.xAvgCharWidth = int(upm / 2)
    return table


def post_table():
    table = newTable('post')
    table.formatType = 3.0
    for attr in ('italicAngle', 'underlinePosition', 'underlineThickness', 'isFixedPitch', 'minMemType42',
                 'maxMemType42', 'minMemType1', 'maxMemType1'):
        setattr(table, attr, 0)
    return table


def ensure_tables(ttf, family, mapping, order, upm, ascent, descent):
    ttf['cmap'] = cmap_table(mapping, order)
    if 'name' not in ttf:
        ttf['name'] = name_table(family)
    if 'OS/2' not in ttf:
        ttf['OS/2'] = os2_table(upm, ascent, descent)
    if 'post' not in ttf:
        ttf['post'] = post_table()
    else:
        ttf['post'].formatType = 3.0


def sfnt_web_font(buffer, family):
    font = fitz.Font(fontbuffer=buffer)
    ttf = TTFont(io.BytesIO(buffer))
    order = ttf.getGlyphOrder()
    inked = cff_inked(ttf['CFF '].cff[ttf['CFF '].cff.fontNames[0]]) if 'CFF ' in ttf else glyf_inked(ttf)
    mapping = unicode_map(font, order, inked)
    if not mapping:
        return None
    upm = ttf['head'].unitsPerEm
    ascent = ttf['hhea'].ascent if 'hhea' in ttf else int(upm * 0.8)
    descent = ttf['hhea'].descent if 'hhea' in ttf else -int(upm * 0.2)
    ensure_tables(ttf, family, mapping, order, upm, ascent, descent)
    out = io.BytesIO()
    ttf.save(out)
    return out.getvalue()


def cff_web_font(buffer, family):
    font = fitz.Font(fontbuffer=buffer)
    cff = CFFFontSet()
    cff.decompile(io.BytesIO(buffer), None)
    top = cff[cff.fontNames[0]]
    order = list(top.charset)
    mapping = unicode_map(font, order, cff_inked(top))
    if not mapping:
        return None
    matrix = getattr(top, 'FontMatrix', [0.001])
    upm = int(round(1 / matrix[0])) if matrix and matrix[0] else UNITS
    ascent, descent = int(font.ascender * upm), int(font.descender * upm)
    bbox = list(getattr(top, 'FontBBox', [0, descent, upm, ascent]))
    ttf = TTFont(sfntVersion='OTTO')
    ttf.setGlyphOrder(order)
    widths = {name: 0 for name in order}
    for cp, gid in mapping.items():
        widths[order[gid]] = int(round(font.glyph_advance(cp) * upm))
    head = ttf['head'] = newTable('head')
    head.tableVersion, head.fontRevision, head.checkSumAdjustment, head.magicNumber = 1.0, 1.0, 0, 0x5F0F3CF5
    head.flags, head.unitsPerEm, head.created, head.modified = 3, upm, 0, 0
    head.xMin, head.yMin, head.xMax, head.yMax = [int(v) for v in bbox]
    head.macStyle, head.lowestRecPPEM, head.fontDirectionHint, head.indexToLocFormat, head.glyphDataFormat = 0, 3, 2, 0, 0
    hhea = ttf['hhea'] = newTable('hhea')
    hhea.tableVersion, hhea.ascent, hhea.descent, hhea.lineGap = 0x00010000, ascent, descent, 0
    hhea.advanceWidthMax = max(widths.values()) if widths else upm
    hhea.minLeftSideBearing = hhea.minRightSideBearing = hhea.xMaxExtent = 0
    hhea.caretSlopeRise, hhea.caretSlopeRun, hhea.caretOffset = 1, 0, 0
    hhea.reserved0 = hhea.reserved1 = hhea.reserved2 = hhea.reserved3 = 0
    hhea.metricDataFormat, hhea.numberOfHMetrics = 0, len(order)
    hmtx = ttf['hmtx'] = newTable('hmtx')
    hmtx.metrics = {name: (widths[name], 0) for name in order}
    maxp = ttf['maxp'] = newTable('maxp')
    maxp.tableVersion, maxp.numGlyphs = 0x00005000, len(order)
    table = ttf['CFF '] = newTable('CFF ')
    table.cff = cff
    ensure_tables(ttf, family, mapping, order, upm, ascent, descent)
    out = io.BytesIO()
    ttf.save(out)
    return out.getvalue()


def web_font_bytes(buffer, ext, family):
    try:
        if ext in ('ttf', 'otf'):
            return sfnt_web_font(buffer, family)
        if ext in ('cff', 'cid'):
            return cff_web_font(buffer, family)
    except Exception:
        return None
    return None
