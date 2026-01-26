import os
import torch
import gc
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor
from .converter import BaseConverter
from ..utils.exceptions import OCRError

class OCRService(BaseConverter):
    _model = None
    _processor = None
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def _get_resources(self):
        if OCRService._model is not None and OCRService._processor is not None:
            return OCRService._model, OCRService._processor
        
        try:
            device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float32 if device == "mps" else torch.bfloat16
            
            OCRService._model = LightOnOcrForConditionalGeneration.from_pretrained(
                "lightonai/LightOnOCR-2-1B", 
                torch_dtype=dtype
            ).to(device)
            
            OCRService._processor = LightOnOcrProcessor.from_pretrained("lightonai/LightOnOCR-2-1B")
            
            return OCRService._model, OCRService._processor
            
        except Exception as e:
            raise OCRError(str(e))
    
    def _extract_text(self, image_path: str) -> str:
        model, processor = self._get_resources()
        
        try:
            device = model.device
            dtype = model.dtype
            
            conversation = [{"role": "user", "content": [{"type": "image", "url": image_path}]}]
            
            inputs = processor.apply_chat_template(
                conversation,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            )
            
            inputs = {k: v.to(device=device, dtype=dtype) if v.is_floating_point() else v.to(device) for k, v in inputs.items()}
            
            output_ids = model.generate(**inputs, max_new_tokens=1024)
            generated_ids = output_ids[0, inputs["input_ids"].shape[1]:]
            output_text = processor.decode(generated_ids, skip_special_tokens=True)
            
            return output_text
            
        except Exception as e:
            raise OCRError(str(e))
    
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
            elif output_format == 'docx':
                return self.ocr_to_docx(input_path, output_path, options)
            else:
                return self.ocr_pdf_to_txt(input_path, output_path, options)
        else:
            if output_format == 'docx':
                return self.ocr_to_docx(input_path, output_path, options)
            return self.ocr_image(input_path, output_path, options)

    def ocr_to_docx(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        from docx import Document
        
        try:
            self.report_progress(10)
            
            if input_path.lower().endswith('.pdf'):
                import fitz
                doc = fitz.open(input_path)
                full_text = ""
                temp_dir = tempfile.mkdtemp(prefix="ocr_docx_")
                
                try:
                    for i, page in enumerate(doc):
                        if self.is_cancelled:
                            doc.close()
                            return None
                            
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                        page_path = os.path.join(temp_dir, f"page_{i}.png")
                        pix.save(page_path)
                        
                        text = self._extract_text(page_path)
                        if text:
                            full_text += text + "\n\n"
                        
                        self.report_progress(10 + int((i + 1) / len(doc) * 80))
                        
                finally:
                    doc.close()
                    shutil.rmtree(temp_dir, ignore_errors=True)
            else:
                full_text = self._extract_text(input_path)
                self.report_progress(90)

            document = Document()
            document.add_paragraph(full_text)
            document.save(output_path)
            
            self.report_progress(100)
            return output_path
            
        except Exception as e:
            raise OCRError(str(e))

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
            raise OCRError(str(e))
    
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
            raise OCRError(str(e))
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
            raise OCRError(str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def get_text_from_image(self, image_path: str, lang: str = 'en') -> str:
        try:
            return self._extract_text(image_path)
        except Exception as e:
            raise OCRError(str(e))
    
    @staticmethod
    def get_supported_input_formats() -> set:
        return {'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'pdf', 'webp'}
    
    @staticmethod
    def get_supported_output_formats() -> set:
        return {'txt', 'pdf', 'docx'}
