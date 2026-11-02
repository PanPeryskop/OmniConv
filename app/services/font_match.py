import io
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path

import fitz
from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTCollection, TTFont

from ..config import Config

logging.getLogger('fontTools').setLevel(logging.ERROR)

SUBSET_RE = re.compile(r'^[A-Z]{6}\+')
STYLE_WORDS = ('bolditalic', 'boldoblique', 'semibold', 'demibold', 'extrabold', 'ultrabold', 'bold', 'black', 'heavy',
               'italic', 'oblique', 'regular', 'medium', 'book', 'light', 'thin', 'normal', 'plain')
SPACED_STYLE_RE = re.compile(r'(?:[ _]+(?:' + '|'.join(STYLE_WORDS) + r'))+$', re.I)
VENDOR_SUFFIX_RE = re.compile(r'(?:psmt|mt|ps)$')
BOLD_WORDS = ('bold', 'black', 'heavy', 'semibold', 'demibold', 'extrabold', 'ultrabold')
ITALIC_WORDS = ('italic', 'oblique')
FONT_EXTENSIONS = ('.ttf', '.otf', '.ttc', '.otc')
PROBE_CHARS = 'ąęłńóśźżĄĘŁŃÓŚŹŻ'
INDEX_VERSION = 3

METRIC_GROUPS = [
    ('sans', ['Arial', 'Helvetica', 'Liberation Sans', 'Arimo', 'Nimbus Sans', 'Nimbus Sans L', 'FreeSans', 'TeX Gyre Heros']),
    ('sans', ['Arial Narrow', 'Helvetica Narrow', 'Liberation Sans Narrow', 'Nimbus Sans Narrow']),
    ('serif', ['Times New Roman', 'Times', 'Liberation Serif', 'Tinos', 'Nimbus Roman', 'Nimbus Roman No9 L', 'FreeSerif', 'TeX Gyre Termes']),
    ('mono', ['Courier New', 'Courier', 'Liberation Mono', 'Cousine', 'Nimbus Mono PS', 'Nimbus Mono L', 'FreeMono', 'TeX Gyre Cursor']),
    ('sans', ['Calibri', 'Carlito']),
    ('serif', ['Cambria', 'Caladea']),
    ('serif', ['Georgia', 'Gelasio']),
    ('sans', ['Segoe UI', 'Selawik']),
    ('sans', ['Verdana', 'DejaVu Sans', 'Bitstream Vera Sans']),
    ('sans', ['Tahoma', 'DejaVu Sans']),
    ('mono', ['Consolas', 'Inconsolata', 'DejaVu Sans Mono']),
    ('serif', ['Book Antiqua', 'Palatino Linotype', 'Palatino', 'TeX Gyre Pagella', 'P052', 'URW Palladio L']),
    ('serif', ['Bookman Old Style', 'TeX Gyre Bonum', 'URW Bookman', 'URW Bookman L']),
    ('serif', ['Century Schoolbook', 'TeX Gyre Schola', 'C059', 'Century Schoolbook L']),
    ('sans', ['Century Gothic', 'TeX Gyre Adventor', 'URW Gothic', 'URW Gothic L']),
    ('serif', ['Computer Modern', 'CMU Serif', 'Latin Modern Roman', 'LM Roman 10']),
]


def key_of(name):
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


def family_key(name):
    return VENDOR_SUFFIX_RE.sub('', key_of(name)) or key_of(name)


METRIC_ALIASES = {}
METRIC_CLASS = {}
for _kind, _group in METRIC_GROUPS:
    for _name in _group:
        METRIC_ALIASES.setdefault(family_key(_name), _group)
        METRIC_CLASS.setdefault(family_key(_name), _kind)


def parse_name(name):
    bare = SUBSET_RE.sub('', name or '').strip()
    lower = bare.lower()
    bold = any(w in lower for w in BOLD_WORDS)
    italic = any(w in lower for w in ITALIC_WORDS)
    family = re.split(r'[-,]', bare, maxsplit=1)[0]
    family = SPACED_STYLE_RE.sub('', family)
    return family.strip(), bold, italic


def font_dirs():
    home = Path.home()
    if sys.platform == 'win32':
        windir = Path(os.environ.get('WINDIR', 'C:/Windows'))
        local = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
        return [windir / 'Fonts', local / 'Microsoft' / 'Windows' / 'Fonts']
    if sys.platform == 'darwin':
        return [Path('/System/Library/Fonts'), Path('/Library/Fonts'), home / 'Library' / 'Fonts']
    return [Path('/usr/share/fonts'), Path('/usr/local/share/fonts'), home / '.fonts', home / '.local' / 'share' / 'fonts']


def name_record(font, *ids):
    table = font['name'] if 'name' in font else None
    if not table:
        return ''
    for name_id in ids:
        record = table.getDebugName(name_id)
        if record:
            return record
    return ''


def panose_of(os2):
    panose = getattr(os2, 'panose', None)
    if not panose:
        return []
    return [panose.bFamilyType, panose.bSerifStyle, panose.bWeight, panose.bProportion, panose.bContrast,
            panose.bStrokeVariation, panose.bArmStyle, panose.bLetterForm, panose.bMidline, panose.bXHeight]


def classify(panose, mono, name):
    lower = (name or '').lower()
    if mono or (len(panose) > 3 and panose[0] == 2 and panose[3] == 9):
        return 'mono'
    known = METRIC_CLASS.get(family_key(parse_name(name)[0]))
    if known:
        return known
    if 'sans' in lower or 'gothic' in lower or 'grotesk' in lower:
        return 'sans'
    if 'serif' in lower or 'roman' in lower or 'times' in lower:
        return 'serif'
    if len(panose) > 1 and panose[0] == 2:
        if 11 <= panose[1] <= 13:
            return 'sans'
        if 2 <= panose[1] <= 10:
            return 'serif'
    return 'sans'


def sfnt_profile(font):
    upm = font['head'].unitsPerEm if 'head' in font else 1000
    os2 = font['OS/2'] if 'OS/2' in font else None
    post = font['post'] if 'post' in font else None
    family = name_record(font, 16, 1)
    subfamily = name_record(font, 17, 2)
    full = name_record(font, 4) or f'{family} {subfamily}'.strip()
    selection = os2.fsSelection if os2 else 0
    style = subfamily.lower()
    bold = bool(selection & 0x20) or any(w in style for w in BOLD_WORDS)
    italic = bool(selection & 0x01) or any(w in style for w in ITALIC_WORDS)
    panose = panose_of(os2) if os2 else []
    mono = bool(post and post.isFixedPitch)
    profile = {
        'family': family, 'style': subfamily, 'full': full, 'ps': name_record(font, 6),
        'bold': bold, 'italic': italic, 'weight': os2.usWeightClass if os2 else (700 if bold else 400),
        'panose': panose, 'kind': classify(panose, mono, f'{family} {full}'),
        'xh': round(getattr(os2, 'sxHeight', 0) / upm, 4) if os2 else 0,
        'cap': round(getattr(os2, 'sCapHeight', 0) / upm, 4) if os2 else 0,
        'avg': round(os2.xAvgCharWidth / upm, 4) if os2 else 0,
    }
    return profile


def cff_profile(buffer):
    cff = CFFFontSet()
    cff.decompile(io.BytesIO(buffer), None)
    name = cff.fontNames[0]
    top = cff[name]
    family = getattr(top, 'FamilyName', '') or parse_name(name)[0]
    weight = str(getattr(top, 'Weight', '') or '').lower()
    full = getattr(top, 'FullName', '') or name
    bold = any(w in f'{weight} {full.lower()}' for w in BOLD_WORDS)
    italic = bool(getattr(top, 'ItalicAngle', 0)) or any(w in full.lower() for w in ITALIC_WORDS)
    mono = bool(getattr(top, 'isFixedPitch', 0))
    return {
        'family': family, 'style': weight, 'full': full, 'ps': name, 'bold': bold, 'italic': italic,
        'weight': 700 if bold else 400, 'panose': [], 'kind': classify([], mono, f'{family} {full}'),
        'xh': 0, 'cap': 0, 'avg': 0,
    }


def program_profile(buffer, ext):
    try:
        if ext in ('ttf', 'otf'):
            with TTFont(io.BytesIO(buffer), lazy=True) as font:
                return sfnt_profile(font)
        if ext in ('cff', 'cid'):
            return cff_profile(buffer)
    except Exception:
        return None
    return None


def font_dict(doc, xref):
    kind, value = doc.xref_get_key(xref, 'DescendantFonts')
    if kind == 'array':
        match = re.search(r'(\d+) 0 R', value)
        if match:
            return int(match.group(1))
    return xref


def descriptor_profile(doc, xref):
    target = font_dict(doc, xref)
    values = {}
    for key in ('Flags', 'FontWeight', 'ItalicAngle', 'XHeight', 'CapHeight', 'AvgWidth', 'StemV'):
        kind, value = doc.xref_get_key(target, f'FontDescriptor/{key}')
        if kind in ('int', 'float'):
            values[key] = float(value)
    return values


def font_kind(profile, flags, basefont):
    if flags & 1 or profile.get('kind') == 'mono':
        return 'mono'
    known = METRIC_CLASS.get(family_key(profile['name_family'])) or METRIC_CLASS.get(family_key(profile.get('family')))
    if known:
        return known
    if 'sans' in basefont.lower():
        return 'sans'
    if profile.get('panose'):
        return profile['kind']
    if flags & 2:
        return 'serif'
    return profile.get('kind') or 'sans'


def pdf_font_profile(doc, xref):
    basefont = doc.xref_get_key(xref, 'BaseFont')[1].lstrip('/')
    family, bold, italic = parse_name(basefont)
    descriptor = descriptor_profile(doc, xref)
    flags = int(descriptor.get('Flags', 0))
    profile = None
    try:
        _name, ext, _type, buffer = doc.extract_font(xref)
        if buffer:
            profile = program_profile(buffer, ext)
    except Exception:
        profile = None
    profile = profile or {'family': family, 'style': '', 'full': basefont, 'ps': basefont, 'panose': [], 'xh': 0, 'cap': 0, 'avg': 0}
    profile['basefont'] = basefont
    profile['name_family'] = family
    profile['bold'] = profile.get('bold') or bold or bool(flags & (1 << 18)) or descriptor.get('FontWeight', 400) >= 600
    profile['italic'] = profile.get('italic') or italic or bool(flags & 64) or bool(descriptor.get('ItalicAngle'))
    profile['weight'] = int(descriptor.get('FontWeight') or profile.get('weight') or (700 if profile['bold'] else 400))
    profile['kind'] = font_kind(profile, flags, basefont)
    cap = descriptor.get('CapHeight')
    if cap and not profile.get('cap'):
        profile['cap'] = round(cap / 1000, 4)
    xh = descriptor.get('XHeight')
    if xh and not profile.get('xh'):
        profile['xh'] = round(xh / 1000, 4)
    return profile


def scan_face(path, number):
    with TTFont(path, fontNumber=number, lazy=True) as font:
        profile = sfnt_profile(font)
        cmap = font.getBestCmap() or {}
        profile['latin_ext'] = all(ord(c) in cmap for c in PROBE_CHARS)
    profile['path'] = str(path)
    profile['number'] = number
    profile['key'] = family_key(profile['family'])
    return profile


def scan_file(path):
    faces = []
    count = 1
    if str(path).lower().endswith(('.ttc', '.otc')):
        try:
            with TTCollection(path, lazy=True) as collection:
                count = len(collection.fonts)
        except Exception:
            return faces
    for number in range(count):
        try:
            faces.append(scan_face(path, number))
        except Exception:
            continue
    return faces


def style_distance(entry, bold, italic, weight=None):
    score = (2 if entry['bold'] != bold else 0) + (2 if entry['italic'] != italic else 0)
    if weight:
        score += abs(entry['weight'] - weight) / 400
    return score


def profile_distance(entry, profile):
    score = style_distance(entry, profile.get('bold', False), profile.get('italic', False), profile.get('weight'))
    if entry['kind'] != profile.get('kind'):
        score += 6
    for key, scale in (('xh', 12), ('cap', 8), ('avg', 10)):
        if entry.get(key) and profile.get(key):
            score += abs(entry[key] - profile[key]) * scale
    left, right = entry.get('panose') or [], profile.get('panose') or []
    if len(left) == 10 and len(right) == 10 and left[0] == right[0] == 2:
        score += sum(abs(a - b) for a, b in zip(left[1:], right[1:], strict=True) if a and b) * 0.08
    return score


class FontLibrary:
    _shared = None
    _lock = threading.Lock()

    def __init__(self, dirs=None, cache_path=None):
        self.dirs = dirs if dirs is not None else font_dirs()
        self.cache_path = cache_path
        self.entries = None
        self.by_key = {}
        self.fonts = {}
        self.ready = threading.Event()
        self.build_lock = threading.Lock()

    @classmethod
    def shared(cls):
        with cls._lock:
            if cls._shared is None:
                cls._shared = FontLibrary(cache_path=Path(Config.DATA_FOLDER) / 'font_index.json')
            return cls._shared

    def warm(self):
        threading.Thread(target=self.load, daemon=True).start()

    def files(self):
        for folder in self.dirs:
            if not folder or not os.path.isdir(folder):
                continue
            for root, _dirs, names in os.walk(folder):
                for name in names:
                    if name.lower().endswith(FONT_EXTENSIONS):
                        yield os.path.join(root, name)

    def read_cache(self):
        try:
            with open(self.cache_path, encoding='utf-8') as handle:
                data = json.load(handle)
            return data['files'] if data.get('version') == INDEX_VERSION else {}
        except Exception:
            return {}

    def write_cache(self, files):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = f'{self.cache_path}.tmp'
            with open(tmp, 'w', encoding='utf-8') as handle:
                json.dump({'version': INDEX_VERSION, 'files': files}, handle)
            os.replace(tmp, self.cache_path)
        except Exception:
            pass

    def load(self):
        with self.build_lock:
            if self.entries is not None:
                return self
            cached = self.read_cache() if self.cache_path else {}
            files = {}
            changed = False
            for path in self.files():
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                stamp = [int(stat.st_mtime), stat.st_size]
                hit = cached.get(path)
                if hit and hit['stamp'] == stamp:
                    files[path] = hit
                else:
                    files[path] = {'stamp': stamp, 'faces': scan_file(path)}
                    changed = True
            if self.cache_path and (changed or len(files) != len(cached)):
                self.write_cache(files)
            self.entries = [face for item in files.values() for face in item['faces']]
            self.by_key = {}
            for entry in self.entries:
                self.by_key.setdefault(entry['key'], []).append(entry)
            self.ready.set()
            return self

    def styled(self, key, bold, italic, weight=None):
        faces = self.by_key.get(key) or []
        if not faces:
            return None
        return min(faces, key=lambda e: style_distance(e, bold, italic, weight))

    def match(self, profile, need=''):
        self.load()
        bold, italic, weight = profile.get('bold', False), profile.get('italic', False), profile.get('weight')
        for name in (profile.get('family'), profile.get('name_family')):
            entry = self.styled(family_key(name), bold, italic, weight)
            if entry and entry['bold'] == bold and entry['italic'] == italic:
                return entry, 'exact'
        for name in (profile.get('family'), profile.get('name_family')):
            for alias in METRIC_ALIASES.get(family_key(name), ()):
                entry = self.styled(family_key(alias), bold, italic, weight)
                if entry and entry['bold'] == bold and entry['italic'] == italic:
                    return entry, 'metric'
        polish = any(ord(c) > 0xFF for c in need)
        pool = [e for e in self.entries if e['kind'] == profile.get('kind', 'sans') and (e['latin_ext'] or not polish)]
        if not pool:
            return None, None
        return min(pool, key=lambda e: profile_distance(e, profile)), 'similar'

    def font(self, entry):
        key = (entry['path'], entry['number'])
        if key not in self.fonts:
            try:
                if entry['number']:
                    buffer = io.BytesIO()
                    with TTFont(entry['path'], fontNumber=entry['number']) as face:
                        face.save(buffer)
                    self.fonts[key] = fitz.Font(fontbuffer=buffer.getvalue())
                else:
                    self.fonts[key] = fitz.Font(fontfile=entry['path'])
            except Exception:
                self.fonts[key] = None
        return self.fonts[key]
