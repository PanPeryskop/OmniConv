import os
# Disable MKLDNN and PIR to avoid static graph mode issues with PaddleOCR-VL
os.environ['FLAGS_use_mkldnn'] = '0'
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_pir_apply_inplace_pass'] = '0'
# Force dynamic graph mode to fix "int(Tensor) is not supported in static graph mode" error
os.environ['FLAGS_enable_eager_mode'] = '1'

from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
import gc
import shutil
import tempfile

from .converter import BaseConverter
from ..utils.exceptions import ConversionError, OCRError


class OCRService(BaseConverter):
    _pipeline = None
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def _get_pipeline(self):
        if OCRService._pipeline is not None:
            return OCRService._pipeline
        
        try:
            from paddleocr import PaddleOCRVL
            
            OCRService._pipeline = PaddleOCRVL()
            return OCRService._pipeline
            
        except Exception as e:
            raise OCRError(f"Failed to initialize OCR: {str(e)}")
    
    def _extract_text(self, image_path: str) -> str:
        """Extract text from image using PaddleOCR-VL.
        
        According to PaddleOCR-VL documentation, the predict() method returns
        result objects with a 'markdown' attribute containing the parsed text.
        """
        pipeline = self._get_pipeline()
        
        try:
            output = pipeline.predict(image_path)
            
            text_parts = []
            for res in output:
                # Primary: use markdown attribute (recommended by PaddleOCR-VL docs)
                if hasattr(res, 'markdown'):
                    md = res.markdown
                    # markdown can be a dict with 'markdown_text' key or a string
                    if isinstance(md, dict):
                        text = md.get('markdown_text', '') or md.get('text', '')
                        text_parts.append(str(text))
                    elif md:
                        text_parts.append(str(md))
                # Fallback: try text attribute
                elif hasattr(res, 'text') and res.text:
                    text_parts.append(str(res.text))
                # Fallback: try rec_texts for legacy compatibility
                elif hasattr(res, 'rec_texts') and res.rec_texts:
                    text_parts.extend(res.rec_texts)
            
            return '\n'.join(text_parts) if text_parts else ""
            
        except Exception as e:
            raise OCRError(f"OCR failed: {str(e)}")
    
    def convert(
        self,
        input_path: str,
        output_path: str,
        output_format: str,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        options = options or {}
        ext = Path(input_path).suffix.lower()
        output_format = output_format.lower()
        
        if ext == '.pdf':
            if output_format == 'pdf':
                return self.ocr_pdf_to_searchable(input_path, output_path, options)
            else:
                return self.ocr_pdf_to_txt(input_path, output_path, options)
        else:
            return self.ocr_image(input_path, output_path, options)
    
    def ocr_image(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        try:
            self.report_progress(10)
            text = self._extract_text(input_path)
            self.report_progress(90)
            
            if self.is_cancelled:
                return None
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            
            self.report_progress(100)
            return output_path
            
        except OCRError:
            raise
        except Exception as e:
            raise OCRError(f"Image OCR failed: {str(e)}")
    
    def ocr_pdf_to_searchable(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import fitz
        
        temp_dir = tempfile.mkdtemp(prefix="ocr_")
        
        try:
            self.report_progress(5)
            
            src_doc = fitz.open(input_path)
            total_pages = len(src_doc)
            
            for page_num in range(total_pages):
                if self.is_cancelled:
                    src_doc.close()
                    return None
                
                page = src_doc[page_num]
                mat = fitz.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=mat)
                
                temp_path = os.path.join(temp_dir, f"page_{page_num}.png")
                pix.save(temp_path)
                
                del pix
                gc.collect()
                
                text = self._extract_text(temp_path)
                
                if text:
                    page.insert_text(
                        (50, 50),
                        text,
                        fontsize=1,
                        render_mode=3
                    )
                
                progress = 5 + int((page_num + 1) / total_pages * 90)
                self.report_progress(progress)
            
            src_doc.save(output_path)
            src_doc.close()
            
            self.report_progress(100)
            return output_path
            
        except OCRError:
            raise
        except Exception as e:
            raise OCRError(f"PDF OCR failed: {str(e)}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def ocr_pdf_to_txt(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        import fitz
        
        temp_dir = tempfile.mkdtemp(prefix="ocr_")
        
        try:
            self.report_progress(5)
            
            doc = fitz.open(input_path)
            all_text = []
            total_pages = len(doc)
            
            for page_num in range(total_pages):
                if self.is_cancelled:
                    doc.close()
                    return None
                
                page = doc[page_num]
                mat = fitz.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=mat)
                
                temp_path = os.path.join(temp_dir, f"page_{page_num}.png")
                pix.save(temp_path)
                del pix
                gc.collect()
                
                text = self._extract_text(temp_path)
                
                if text:
                    all_text.append(f"--- Page {page_num + 1} ---\n{text}")
                
                progress = 5 + int((page_num + 1) / total_pages * 90)
                self.report_progress(progress)
            
            doc.close()
            
            txt_path = output_path if output_path.endswith('.txt') else output_path.replace('.pdf', '.txt')
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write('\n\n'.join(all_text))
            
            self.report_progress(100)
            return txt_path
            
        except OCRError:
            raise
        except Exception as e:
            raise OCRError(f"PDF OCR failed: {str(e)}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def get_text_from_image(self, image_path: str, lang: str = 'en') -> str:
        try:
            return self._extract_text(image_path)
        except Exception as e:
            raise OCRError(f"Text extraction failed: {str(e)}")
    
    @staticmethod
    def get_supported_input_formats() -> set:
        return {'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'pdf', 'webp'}
    
    @staticmethod
    def get_supported_output_formats() -> set:
        return {'txt', 'pdf'}
