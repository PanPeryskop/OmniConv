from typing import Optional, Dict, Any

from .converter import BaseConverter
from ..utils.exceptions import (
    ConversionError, 
    UnsupportedFormatError,
    PasswordRequiredError,
    InvalidPasswordError
)


class DocumentConverter(BaseConverter):
    INPUT_FORMATS = {'pdf'}
    OUTPUT_FORMATS = {'docx', 'txt'}  # pdf_ocr disabled - OCR not working
    
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
    
    @staticmethod
    def get_supported_input_formats() -> set:
        return DocumentConverter.INPUT_FORMATS
    
    @staticmethod
    def get_supported_output_formats() -> set:
        return DocumentConverter.OUTPUT_FORMATS
