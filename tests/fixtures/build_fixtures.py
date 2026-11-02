import io
import os
import sys

import fitz
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

LOREM = (
    'Edytor PDF powinien zachować krój, rozmiar i kolor tekstu. Zażółć gęślą jaźń, '
    'czyli zdanie z wszystkimi polskimi znakami diakrytycznymi. The quick brown fox '
    'jumps over the lazy dog while the paragraph keeps flowing across several lines '
    'so that justification and wrapping can be checked.'
)


def png_bytes(size=(120, 80), color=(37, 99, 235), alpha=False):
    mode = 'RGBA' if alpha else 'RGB'
    image = Image.new(mode, size, color + ((0,) if alpha else ()))
    draw = ImageDraw.Draw(image)
    fill = color + ((255,) if alpha else ())
    draw.ellipse([4, 4, size[0] - 4, size[1] - 4], fill=fill)
    draw.rectangle([size[0] // 3, size[1] // 3, size[0] * 2 // 3, size[1] * 2 // 3], fill=(255, 255, 255) + ((255,) if alpha else ()))
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def jpeg_bytes(size=(160, 100)):
    image = Image.new('RGB', size)
    draw = ImageDraw.Draw(image)
    for x in range(size[0]):
        draw.line([(x, 0), (x, size[1])], fill=(x * 255 // size[0], 120, 255 - x * 255 // size[0]))
    out = io.BytesIO()
    image.save(out, 'JPEG', quality=80)
    return out.getvalue()


def embedded(code):
    return fitz.Font(fontbuffer=fitz.Font(code).buffer)


def write(page, rect, text, font, size, color=(0, 0, 0), align=fitz.TEXT_ALIGN_LEFT):
    writer = fitz.TextWriter(page.rect)
    writer.fill_textbox(rect, text, font=font, fontsize=size, align=align)
    writer.write_text(page, color=color)


def text_page(doc, fonts):
    page = doc.new_page(width=595, height=842)
    write(page, fitz.Rect(60, 50, 535, 90), 'Synthetic editor test', fonts['bold'], 24, align=fitz.TEXT_ALIGN_CENTER)
    write(page, fitz.Rect(60, 110, 535, 220), LOREM, fonts['regular'], 11, align=fitz.TEXT_ALIGN_JUSTIFY)
    write(page, fitz.Rect(60, 230, 535, 300), LOREM, fonts['serif'], 12, color=(0.6, 0.1, 0.1))
    for i, item in enumerate(['Pierwszy punkt listy', 'Drugi punkt listy', 'Trzeci punkt listy']):
        y = 330 + i * 18
        write(page, fitz.Rect(72, y, 90, y + 16), '•', fonts['regular'], 11)
        write(page, fitz.Rect(90, y, 535, y + 16), item, fonts['regular'], 11)
    write(page, fitz.Rect(60, 420, 535, 450), 'Right aligned footer line', fonts['italic'], 10, align=fitz.TEXT_ALIGN_RIGHT)
    spaced(page, (60, 500), 'ROZSTRZELONY NAGŁÓWEK', fonts['bold'], 14, 3)
    writer = fitz.TextWriter(page.rect)
    writer.append((60, 560), 'Energia E = mc', font=fonts['regular'], fontsize=12)
    writer.append((writer.last_point.x, 555), '2', font=fonts['regular'], fontsize=8)
    writer.append((writer.last_point.x, 560), ' oraz wzór wody H', font=fonts['regular'], fontsize=12)
    writer.append((writer.last_point.x, 563), '2', font=fonts['regular'], fontsize=8)
    writer.append((writer.last_point.x, 560), 'O.', font=fonts['regular'], fontsize=12)
    writer.write_text(page)
    return page


def spaced(page, origin, text, font, size, spacing):
    writer = fitz.TextWriter(page.rect)
    x, y = origin
    for char in text:
        writer.append((x, y), char, font=font, fontsize=size)
        x += font.text_length(char, fontsize=size) + spacing
    writer.write_text(page)


def image_page(doc, fonts):
    page = doc.new_page(width=595, height=842)
    write(page, fitz.Rect(60, 40, 535, 70), 'Images: XObject, alpha, JPEG, inline, form, rotated', fonts['bold'], 14)
    page.insert_image(fitz.Rect(60, 90, 240, 210), stream=png_bytes())
    page.insert_image(fitz.Rect(300, 90, 480, 210), stream=png_bytes(color=(220, 38, 38), alpha=True))
    page.insert_image(fitz.Rect(60, 240, 300, 390), stream=jpeg_bytes())
    page.insert_image(fitz.Rect(340, 240, 440, 390), stream=png_bytes(color=(22, 163, 74)), rotate=90)
    source = fitz.open()
    holder = source.new_page(width=200, height=150)
    holder.insert_image(fitz.Rect(20, 20, 180, 130), stream=png_bytes(color=(124, 58, 237)))
    page.show_pdf_page(fitz.Rect(60, 420, 260, 570), source, 0)
    xref = page.get_contents()[-1]
    inline = (
        b'\nq 120 0 0 60 320 272 cm BI /W 4 /H 2 /CS /RGB /BPC 8 ID '
        + bytes([249, 115, 22] * 4 + [234, 179, 8] * 4)
        + b' EI Q\n'
    )
    doc.update_stream(xref, doc.xref_stream(xref) + inline)
    return page


def annot_page(doc, fonts):
    page = doc.new_page(width=595, height=842)
    write(page, fitz.Rect(60, 60, 535, 90), 'Highlighted sentence for markup tests.', fonts['regular'], 14)
    write(page, fitz.Rect(60, 120, 535, 150), 'Sensitive: PESEL 44051401359, IBAN PL61109010140000071219812874', fonts['regular'], 12)
    write(page, fitz.Rect(60, 180, 535, 210), 'Text under a pending redaction mark.', fonts['regular'], 12)
    page.add_highlight_annot(fitz.Rect(60, 60, 330, 80))
    page.add_text_annot((500, 60), 'Existing note')
    page.add_rect_annot(fitz.Rect(60, 260, 200, 330))
    page.add_ink_annot([[(250, 270), (300, 320), (350, 280)]])
    page.add_redact_annot(fitz.Rect(60, 180, 300, 200))
    return page


def radio_group(doc, page, name, options, y):
    parent = doc.get_new_xref()
    kids = []
    for i, label in enumerate(options):
        x = 60 + i * 120
        kid = doc.get_new_xref()
        on, off = doc.get_new_xref(), doc.get_new_xref()
        for ap, body in ((on, b'0.15 0.39 0.92 rg 4 4 10 10 re f 0 G 0.5 0.5 17 17 re S'), (off, b'0 G 0.5 0.5 17 17 re S')):
            doc.update_object(ap, '<</Type/XObject/Subtype/Form/BBox[0 0 18 18]>>')
            doc.update_stream(ap, body)
        top = page.rect.height - y
        doc.update_object(kid, (
            f'<</Type/Annot/Subtype/Widget/Rect[{x} {top - 18} {x + 18} {top}]/Parent {parent} 0 R/P {page.xref} 0 R/F 4'
            f'/AS/{"Off" if i else label}/AP<</N<</{label} {on} 0 R/Off {off} 0 R>>>>>>'
        ))
        kids.append(kid)
    doc.update_object(parent, f'<</FT/Btn/Ff 49152/T({name})/V/{options[0]}/Kids[{" ".join(f"{k} 0 R" for k in kids)}]>>')
    return parent, kids


def form_page(doc, fonts):
    page = doc.new_page(width=595, height=842)
    write(page, fitz.Rect(60, 40, 535, 70), 'Formularz testowy', fonts['bold'], 16)
    fields = [
        ('imie', fitz.PDF_WIDGET_TYPE_TEXT, fitz.Rect(60, 90, 300, 112), 'Jan'),
        ('uwagi', fitz.PDF_WIDGET_TYPE_TEXT, fitz.Rect(60, 130, 300, 190), ''),
        ('zgoda', fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.Rect(60, 210, 78, 228), False),
        ('miasto', fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.Rect(60, 250, 300, 272), 'Katowice'),
    ]
    for name, kind, rect, value in fields:
        widget = fitz.Widget()
        widget.field_name = name
        widget.field_type = kind
        widget.rect = rect
        if name == 'uwagi':
            widget.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
        if kind == fitz.PDF_WIDGET_TYPE_COMBOBOX:
            widget.choice_values = ['Katowice', 'Kraków', 'Warszawa']
        widget.field_value = value
        page.add_widget(widget)
    parent, kids = radio_group(doc, page, 'plec', ['tak', 'nie', 'brak'], 300)
    annots = doc.xref_get_key(page.xref, 'Annots')[1].strip('[]').strip()
    doc.xref_set_key(page.xref, 'Annots', f'[{annots} {" ".join(f"{k} 0 R" for k in kids)}]')
    fields_key = doc.xref_get_key(doc.pdf_catalog(), 'AcroForm/Fields')
    current = fields_key[1].strip('[]').strip() if fields_key[0] == 'array' else ''
    doc.xref_set_key(doc.pdf_catalog(), 'AcroForm/Fields', f'[{current} {parent} 0 R]')
    return page


def rotated_page(doc, fonts):
    page = doc.new_page(width=595, height=842)
    page.set_rotation(90)
    page.insert_font(fontname='body', fontbuffer=fonts['regular'].buffer)
    page.insert_textbox(fitz.Rect(60, 60, 155, 780), 'This page is rotated by 90 degrees. ' + LOREM, fontname='body', fontsize=12, rotate=90)
    return page


def build_scan(path=None, source=None):
    path = path or os.path.join(HERE, 'pe_scan.pdf')
    with fitz.open(source or os.path.join(HERE, 'pe_test.pdf')) as original:
        pix = original[0].get_pixmap(dpi=150, colorspace=fitz.csGRAY)
    pixels = Image.frombytes('L', (pix.width, pix.height), pix.samples).convert('RGB')
    tint = Image.new('RGB', pixels.size, (246, 240, 226))
    scanned = Image.composite(pixels, tint, pixels.convert('L').point(lambda v: 255 if v < 200 else 0))
    out = io.BytesIO()
    scanned.save(out, 'JPEG', quality=82)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=out.getvalue())
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def build_tagged(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i, text in enumerate(['Pierwszy otagowany akapit.', 'Drugi otagowany akapit.']):
        page.insert_text((72, 100 + 40 * i), text, fontsize=14)
        xref = page.get_contents()[-1]
        doc.update_stream(xref, f'/P <</MCID {i}>> BDC\n'.encode() + doc.xref_stream(xref) + b'\nEMC\n')
    root, top, tree = doc.get_new_xref(), doc.get_new_xref(), doc.get_new_xref()
    paragraphs = [doc.get_new_xref(), doc.get_new_xref()]
    for i, xref in enumerate(paragraphs):
        doc.update_object(xref, f'<</Type/StructElem/S/P/P {top} 0 R/Pg {page.xref} 0 R/K {i}>>')
    kids = ' '.join(f'{x} 0 R' for x in paragraphs)
    doc.update_object(top, f'<</Type/StructElem/S/Document/P {root} 0 R/K [{kids}]>>')
    doc.update_object(tree, f'<</Nums [0 [{kids}]]>>')
    doc.update_object(root, f'<</Type/StructTreeRoot/K [{top} 0 R]/ParentTree {tree} 0 R/ParentTreeNextKey 1>>')
    doc.xref_set_key(page.xref, 'StructParents', '0')
    doc.xref_set_key(doc.pdf_catalog(), 'StructTreeRoot', f'{root} 0 R')
    doc.xref_set_key(doc.pdf_catalog(), 'MarkInfo', '<</Marked true>>')
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def build(path=None):
    path = path or os.path.join(HERE, 'pe_test.pdf')
    doc = fitz.open()
    fonts = {
        'regular': embedded('helv'), 'bold': embedded('hebo'),
        'italic': embedded('heit'), 'serif': embedded('tiro'),
    }
    text_page(doc, fonts)
    image_page(doc, fonts)
    annot_page(doc, fonts)
    form_page(doc, fonts)
    rotated_page(doc, fonts)
    doc.subset_fonts()
    doc.set_metadata({'title': 'OmniConv PDF editor test', 'creationDate': 'D:20260101000000Z', 'modDate': 'D:20260101000000Z'})
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else None
    print(build(target))
    print(build_scan(None, target))
