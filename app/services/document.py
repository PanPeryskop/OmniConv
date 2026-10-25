from typing import Optional, Dict, Any
import os
import html
import shutil
import io
import csv

from .converter import BaseConverter
from ..utils.exceptions import (
    ConversionError, 
    UnsupportedFormatError,
    PasswordRequiredError,
    InvalidPasswordError
)

class DocumentConverter(BaseConverter):
    INPUT_FORMATS = {'pdf', 'md', 'epub', 'mobi', 'txt'}
    OUTPUT_FORMATS = {'docx', 'txt', 'pdf', 'pdf_ocr', 'md', 'html', 'images', 'csv', 'xlsx', 'epub', 'cbz'}
    
    def convert(self, input_path: str, output_path: str, output_format: str, options: Optional[Dict[str, Any]] = None) -> str:
        options = options or {}
        output_format = output_format.lower()
        
        if output_format not in self.OUTPUT_FORMATS:
            raise UnsupportedFormatError(output_format, list(self.OUTPUT_FORMATS))
        
        handlers = {
            'docx': self._pdf_to_docx,
            'txt': self._pdf_to_text,
            'md': self._pdf_to_md,
            'html': self._pdf_to_html,
            'images': self._extract_images,
            'csv': self._pdf_to_csv,
            'xlsx': self._pdf_to_xlsx,
            'epub': self._pdf_to_epub,
            'cbz': self._pdf_to_cbz,
            'pdf_ocr': self._pdf_ocr,
        }

        if output_format == 'pdf':
            if input_path.lower().endswith('.md'):
                return self._md_to_pdf(input_path, output_path, options)
            raise ConversionError("PDF output only supported from Markdown input")
            
        handler = handlers.get(output_format)
        if handler:
            return handler(input_path, output_path, options)
        
        raise UnsupportedFormatError(output_format)
    
    def _pdf_to_docx(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        from pdf2docx import Converter
        try:
            self.report_progress(10)
            password = options.get('password')
            cv = Converter(input_path, password=password)
            self.report_progress(30)
            if self.is_cancelled:
                cv.close()
                return None
            cv.convert(output_path, start=0, end=None)
            self.report_progress(90)
            cv.close()
            self.report_progress(100)
            return output_path
        except Exception as e:
            self._handle_pdf_error(e, password)

    def _pdf_to_text(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import fitz
        try:
            self.report_progress(10)
            doc = fitz.open(input_path)
            if doc.is_encrypted:
                if not options.get('password'):
                    raise PasswordRequiredError()
                doc.authenticate(options['password'])
            
            text_blocks = []
            for page in doc:
                text_blocks.append(page.get_text())
                if self.is_cancelled:
                    doc.close()
                    return None
            
            self.report_progress(80)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n\n'.join(text_blocks))
            
            doc.close()
            self.report_progress(100)
            return output_path
        except Exception as e:
            self._handle_pdf_error(e, options.get('password'))

    def _pdf_to_md(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import fitz
        try:
            self.report_progress(10)
            doc = fitz.open(input_path)
            if doc.is_encrypted:
                if not options.get('password'):
                    raise PasswordRequiredError()
                doc.authenticate(options['password'])
            
            md_content = []
            for page in doc:
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if block['type'] == 0:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                text = span["text"].strip()
                                size = span["size"]
                                if not text: continue
                                
                                if size > 18:
                                    md_content.append(f"# {text}")
                                elif size > 14:
                                    md_content.append(f"## {text}")
                                elif size > 12:
                                    md_content.append(f"### {text}")
                                else:
                                    md_content.append(text)
                            md_content.append("")
                    if self.is_cancelled:
                        doc.close()
                        return None
                        
            self.report_progress(80)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(md_content))
            
            doc.close()
            self.report_progress(100)
            return output_path
        except Exception as e:
            self._handle_pdf_error(e, options.get('password'))

    def _pdf_to_html(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import fitz
        try:
            self.report_progress(10)
            doc = fitz.open(input_path)
            if doc.is_encrypted:
                if not options.get('password'):
                    raise PasswordRequiredError()
                doc.authenticate(options['password'])
            
            html_parts = []
            for page in doc:
                html_parts.append(page.get_text("html"))
                if self.is_cancelled:
                    doc.close()
                    return None
            
            self.report_progress(80)
            full_html = f"<html><body>{'<hr>'.join(html_parts)}</body></html>"
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(full_html)
            
            doc.close()
            self.report_progress(100)
            return output_path
        except Exception as e:
            self._handle_pdf_error(e, options.get('password'))

    def _extract_images(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import fitz
        try:
            if not os.path.exists(output_path):
                os.makedirs(output_path)
            
            doc = fitz.open(input_path)
            if doc.is_encrypted:
                if not options.get('password'):
                    raise PasswordRequiredError()
                doc.authenticate(options['password'])

            count = 0
            for i, page in enumerate(doc):
                images = page.get_images()
                for j, img in enumerate(images):
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    ext = base_image["ext"]
                    filename = f"page{i+1}_img{j+1}.{ext}"
                    with open(os.path.join(output_path, filename), "wb") as f:
                        f.write(image_bytes)
                    count += 1
                
                if self.is_cancelled:
                    doc.close()
                    shutil.rmtree(output_path)
                    return None
            
            doc.close()
            
            if not count:
                shutil.rmtree(output_path)
                raise ConversionError("No images found in this PDF")
            archive_base = output_path[:-len('.images')] + '_images' if output_path.endswith('.images') else output_path
            shutil.make_archive(archive_base, 'zip', output_path)
            shutil.rmtree(output_path)
            return f"{archive_base}.zip"
        except Exception as e:
            self._handle_pdf_error(e, options.get('password'))

    def _pdf_to_csv(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import pdfplumber
        try:
            with pdfplumber.open(input_path, password=options.get('password')) as pdf:
                all_tables = []
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        all_tables.extend(table)
                    if self.is_cancelled:
                        return None
                
                with open(output_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerows(all_tables)
            return output_path
        except ImportError:
            raise ConversionError("pdfplumber required for table extraction")
        except Exception as e:
            self._handle_pdf_error(e, options.get('password'))

    def _pdf_to_xlsx(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import pdfplumber
        import openpyxl
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            
            with pdfplumber.open(input_path, password=options.get('password')) as pdf:
                row_idx = 1
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            for col_idx, cell in enumerate(row, 1):
                                ws.cell(row=row_idx, column=col_idx, value=cell)
                            row_idx += 1
                        row_idx += 2
                    if self.is_cancelled:
                        return None
            
            wb.save(output_path)
            return output_path
        except ImportError:
            raise ConversionError("pdfplumber and openpyxl required for xlsx extraction")
        except Exception as e:
            self._handle_pdf_error(e, options.get('password'))

    def _pdf_to_epub(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        try:
            import fitz
            from ebooklib import epub
            
            book = epub.EpubBook()
            
            doc = fitz.open(input_path)
            if doc.is_encrypted and options.get('password'):
                doc.authenticate(options['password'])

            meta = doc.metadata
            title = meta.get('title') or "Untitled"
            author = meta.get('author') or "Unknown"
            
            book.set_identifier(f'id_{os.path.basename(input_path)}')
            book.set_title(title)
            book.set_language('en')
            book.add_author(author)
            
            chapters = []
            toc_links = []
            
            for i, page in enumerate(doc):
                if self.is_cancelled:
                    return None
                    
                page_html = page.get_text("html")
                
                c = epub.EpubHtml(title=f'Page {i+1}', file_name=f'page_{i+1}.xhtml', lang='en')
                c.content = page_html
                book.add_item(c)
                chapters.append(c)
                toc_links.append(epub.Link(f'page_{i+1}.xhtml', f'Page {i+1}', f'page_{i+1}'))
                
                self.report_progress(int((i / len(doc)) * 90))

            book.toc = tuple(toc_links)
            
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            
            style = 'body { font-family: Times, serif; }'
            nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
            book.add_item(nav_css)
            
            book.spine = ['nav'] + chapters
            
            epub.write_epub(output_path, book, {})
            
            doc.close()
            return output_path
            
        except Exception as e:
            self._handle_pdf_error(e, options.get('password'))

    def _pdf_to_cbz(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        try:
            import fitz
            import zipfile
            
            doc = fitz.open(input_path)
            if doc.is_encrypted and options.get('password'):
                doc.authenticate(options['password'])
                
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for i, page in enumerate(doc):
                    if self.is_cancelled:
                        return None
                        
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_data = pix.tobytes("jpg")
                    zf.writestr(f"{i:04d}.jpg", img_data)
                    
                    self.report_progress(int((i / len(doc)) * 90))
            
            doc.close()
            return output_path
            
        except Exception as e:
            self._handle_pdf_error(e, options.get('password'))

    def _pdf_ocr(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        from .ocr import OCRService
        ocr = OCRService(self._progress_callback)
        return ocr.convert(input_path, output_path, 'pdf', options)

    def _md_to_pdf(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import fitz
        import markdown
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            self.report_progress(20)
            body = markdown.markdown(md_content, extensions=['tables', 'fenced_code', 'sane_lists'])
            css = (
                "body { font-family: sans-serif; font-size: 11pt; line-height: 1.45; }"
                "h1 { font-size: 20pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }"
                "pre, code { font-family: monospace; font-size: 9.5pt; background-color: #f2f2f2; }"
                "table { border-collapse: collapse; } th, td { border: 1px solid #999; padding: 3px 6px; }"
                "blockquote { color: #555; margin-left: 12pt; }"
            )
            story = fitz.Story(html=body, user_css=css)
            writer = fitz.DocumentWriter(output_path)
            mediabox = fitz.paper_rect('a4')
            where = mediabox + (54, 54, -54, -54)
            more = True
            while more:
                device = writer.begin_page(mediabox)
                more, _ = story.place(where)
                story.draw(device)
                writer.end_page()
            writer.close()
            self.report_progress(100)
            return output_path
        except Exception as e:
            raise ConversionError(f"Markdown to PDF conversion failed: {str(e)}")

    def _handle_pdf_error(self, e: Exception, password: str = None):
        error_msg = str(e).lower()
        if 'password' in error_msg or 'encrypted' in error_msg:
            if password:
                raise InvalidPasswordError()
            raise PasswordRequiredError()
        raise ConversionError(str(e))

    @staticmethod
    def get_supported_input_formats() -> set:
        return DocumentConverter.INPUT_FORMATS

    @staticmethod
    def get_supported_output_formats() -> set:
        return DocumentConverter.OUTPUT_FORMATS

    def extract_text(self, input_path: str) -> str:
        try:
            import fitz
            doc = fitz.open(input_path)
            full_text = []
            for page in doc:
                text = page.get_text()
                if text:
                    full_text.append(text)
            doc.close()
            return "\n\n".join(full_text)
        except Exception as e:
            print(f"Fitz extraction failed: {e}. Trying text read.")
            try:
                with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except Exception as read_error:
                raise ConversionError(f"Could not extract text: {str(e)} | Txt read: {str(read_error)}")

