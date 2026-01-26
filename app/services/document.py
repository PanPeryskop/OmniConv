from typing import Optional, Dict, Any

from .converter import BaseConverter
from ..utils.exceptions import (
    ConversionError, 
    UnsupportedFormatError,
    PasswordRequiredError,
    InvalidPasswordError
)


class DocumentConverter(BaseConverter):
    INPUT_FORMATS = {'pdf', 'md'}
    OUTPUT_FORMATS = {'docx', 'txt', 'pdf', 'pdf_ocr'}
    
    def convert(
        self,
        input_path: str,
        output_path: str,
        output_format: str,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        options = options or {}
        output_format = output_format.lower()
        
        if output_format not in self.OUTPUT_FORMATS:
            raise UnsupportedFormatError(output_format, list(self.OUTPUT_FORMATS))
        
        if output_format == 'docx':
            return self._pdf_to_docx(input_path, output_path, options)
        elif output_format == 'txt':
            return self._pdf_to_text(input_path, output_path, options)
        elif output_format == 'pdf':
            # Check if input is markdown
            if input_path.lower().endswith('.md'):
                return self._md_to_pdf(input_path, output_path, options)
            raise ConversionError("PDF output only supported from Markdown input")
        elif output_format == 'pdf_ocr':
            from .ocr import OCRService
            ocr = OCRService(self._progress_callback)
            return ocr.ocr_pdf_to_searchable(input_path, output_path, options)
        
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
            error_msg = str(e).lower()
            if 'password' in error_msg or 'encrypted' in error_msg:
                if password:
                    raise InvalidPasswordError()
                raise PasswordRequiredError()
            raise ConversionError(f"PDF to DOCX conversion failed: {str(e)}")
    
    def _pdf_to_text(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        from pdfminer.high_level import extract_text
        from pypdf import PdfReader
        
        try:
            self.report_progress(10)
            password = options.get('password')
            
            reader = PdfReader(input_path)
            if reader.is_encrypted:
                if password:
                    if not reader.decrypt(password):
                        raise InvalidPasswordError()
                else:
                    raise PasswordRequiredError()
            
            self.report_progress(30)
            text = extract_text(input_path, password=password)
            self.report_progress(80)
            
            if self.is_cancelled:
                return None
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            
            self.report_progress(100)
            return output_path
            
        except (PasswordRequiredError, InvalidPasswordError):
            raise
        except Exception as e:
            raise ConversionError(f"Text extraction failed: {str(e)}")
    
    def _md_to_pdf(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        """Convert Markdown file to PDF using markdown and weasyprint."""
        import markdown
        from weasyprint import HTML, CSS
        
        try:
            self.report_progress(10)
            
            # Read markdown file
            with open(input_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            
            self.report_progress(30)
            
            if self.is_cancelled:
                return None
            
            # Convert markdown to HTML
            html_content = markdown.markdown(
                md_content,
                extensions=['tables', 'fenced_code', 'codehilite', 'toc']
            )
            
            self.report_progress(50)
            
            # Wrap in HTML document with styling
            full_html = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
        }}
        h1, h2, h3, h4, h5, h6 {{
            margin-top: 1.5em;
            margin-bottom: 0.5em;
            color: #1a1a1a;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Consolas', 'Monaco', monospace;
        }}
        pre {{
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        pre code {{
            background: none;
            padding: 0;
        }}
        blockquote {{
            border-left: 4px solid #ddd;
            margin: 0;
            padding-left: 20px;
            color: #666;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px 12px;
            text-align: left;
        }}
        th {{
            background: #f4f4f4;
        }}
        a {{
            color: #0066cc;
        }}
    </style>
</head>
<body>
{html_content}
</body>
</html>
'''
            
            self.report_progress(70)
            
            # Convert HTML to PDF
            HTML(string=full_html).write_pdf(output_path)
            
            self.report_progress(100)
            return output_path
            
        except Exception as e:
            raise ConversionError(f"Markdown to PDF conversion failed: {str(e)}")
    
    @staticmethod
    def get_supported_input_formats() -> set:
        return DocumentConverter.INPUT_FORMATS
    
    @staticmethod
    def get_supported_output_formats() -> set:
        return DocumentConverter.OUTPUT_FORMATS
