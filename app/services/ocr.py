import os
import shutil
import tempfile
import gc
from pathlib import Path
from typing import Optional, Dict, Any
from .converter import BaseConverter
from ..utils.exceptions import OCRError
from .llm import LLMService

class OCRService(BaseConverter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.llm = LLMService()

    def _extract_text(self, image_path: str, output_format: str = 'txt', use_llm: bool = False, engine: str = 'qwen', options: Dict[str, Any] = None) -> str:
        options = options or {}
        try:
            if engine in ['lighton', 'lighton_mistral']:
                text = self._extract_text_local(image_path)
                
                if engine == 'lighton_mistral':
                    self.report_progress(50)
                    text = self.llm.correct_text(text, output_format)
                    
                    if output_format == 'html':
                        theme = options.get('ocr_theme', 'light')
                        css_limit = options.get('css_limit_value') if options.get('css_limit_enabled') else None
                        return self.llm.generate_html(text, theme, css_limit)
                        
                return text

            prompt = "Transcribe the text from this image exactly as it appears. Do not add any commentary."
            
            if output_format == 'html':
                theme_opt = options.get('ocr_theme', 'light')
                if theme_opt == 'dark':
                    theme_prompt = "Use a DARK THEME (dark background #1a1a1a, light text #e0e0e0)."
                else:
                    theme_prompt = "Use a LIGHT THEME (white background, dark text)."

                css_limit_instruction = ""
                if options.get('css_limit_enabled'):
                    limit_val = options.get('css_limit_value', 1000)
                    css_limit_instruction = f"IMPORTANT: Limit the CSS styles to approximately {limit_val} characters total. prioritize essential layout and typography."

                prompt = (
                    "Transcribe the content of this image into clean, semantically correct HTML5. "
                    "Use appropriate tags (h1, p, table, etc.). "
                    f"Add a <style> block with CSS to make the document look modern and premium. {theme_prompt} "
                    f"{css_limit_instruction} "
                    "Focus on excellent typography, spacing, and clean layout. "
                    "Keep the CSS efficient and reasonable."
                    "Output ONLY the raw HTML code."
                )
            elif output_format == 'md':
                prompt = (
                    "Transcribe the content of this image into well-formatted Markdown. "
                    "Use proper Markdown syntax: # for main headings, ## for subheadings, "
                    "- or * for bullet lists, 1. 2. 3. for numbered lists, "
                    "**bold** for emphasis, *italic* for secondary emphasis, "
                    "| tables | with | proper | formatting |, "
                    "and > for blockquotes. "
                    "Structure the content logically. Output ONLY the raw markdown, no code blocks."
                )
            elif output_format in ['pdf', 'docx', 'txt']:
                prompt = (
                    "Transcribe the text from this image exactly as it appears. "
                    "Output ONLY plain text. Do NOT use Markdown formatting, do NOT use HTML tags. "
                    "Maintain the original layout using spaces and newlines where possible."
                )
            
            text = self.llm.generate_from_image(image_path, prompt)
            
            if output_format == 'html':
                if text.startswith("```html"): text = text[7:]
                if text.startswith("```"): text = text[3:]
                if text.endswith("```"): text = text[:-3]
                return text.strip()

            if output_format == 'md':
                if text.startswith("```markdown"): text = text[11:]
                elif text.startswith("```md"): text = text[5:]
                elif text.startswith("```"): text = text[3:]
                if text.endswith("```"): text = text[:-3]
                return text.strip()
                
            return text

        except Exception as e:
            raise OCRError(str(e))

    def _extract_text_local(self, image_path: str) -> str:
        try:
            import torch
            from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor

            if not hasattr(self, '_lighton_model'):
                device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
                dtype = torch.float32 if device == "mps" else torch.bfloat16
                
                if device == 'cpu':
                    dtype = torch.float32

                self._lighton_device = device
                self._lighton_dtype = dtype
                self._lighton_model = LightOnOcrForConditionalGeneration.from_pretrained(
                    "lightonai/LightOnOCR-2-1B-base", 
                    torch_dtype=dtype
                ).to(device)
                self._lighton_processor = LightOnOcrProcessor.from_pretrained("lightonai/LightOnOCR-2-1B-base")

            import base64
            import mimetypes
            
            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type:
                mime_type = 'image/png'
            
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            
            image_url = f"data:{mime_type};base64,{encoded_string}"
            
            conversation = [{"role": "user", "content": [{"type": "image", "url": image_url}]}]

            inputs = self._lighton_processor.apply_chat_template(
                conversation,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            )
            
            inputs = {
                k: v.to(device=self._lighton_device, dtype=self._lighton_dtype) 
                if v.is_floating_point() else v.to(self._lighton_device) 
                for k, v in inputs.items()
            }

            output_ids = self._lighton_model.generate(**inputs, max_new_tokens=1024)
            generated_ids = output_ids[0, inputs["input_ids"].shape[1]:]
            output_text = self._lighton_processor.decode(generated_ids, skip_special_tokens=True)
            
            return output_text

        except Exception as e:
            raise e

    @staticmethod
    def get_supported_input_formats() -> set:
        return {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff', 'pdf'}

    @staticmethod
    def get_supported_output_formats() -> set:
        return {'txt', 'md', 'html', 'ocr-txt', 'ocr-md', 'ocr-html', 'docx', 'ocr-docx', 'pdf', 'ocr-pdf'}

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
        
        if output_format.startswith('ocr-'):
            output_format = output_format[4:]
            
        if output_format in ['docx', 'pdf']:
            if ext == '.pdf':
                return self.ocr_pdf(input_path, output_path, output_format, options)
            else:
                return self.ocr_image(input_path, output_path, output_format, options)
        
        if ext == '.pdf':
            return self.ocr_pdf(input_path, output_path, output_format, options)
        else:
            return self.ocr_image(input_path, output_path, output_format, options)

    def _save_as_docx(self, text: str, output_path: str):
        from docx import Document
        doc = Document()
        for line in text.split('\n'):
            if line.strip():
                doc.add_paragraph(line)
        doc.save(output_path)

    def _save_as_pdf(self, text: str, output_path: str):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        p = fitz.Point(50, 72)
        page.insert_text(p, text, fontsize=11)
        doc.save(output_path)
        doc.close()

    def ocr_image(self, input_path: str, output_path: str, output_format: str, options: Dict[str, Any]) -> str:
        try:
            self.report_progress(10)
            engine = options.get('ocr_engine', 'qwen')
            text = self._extract_text(input_path, output_format, use_llm=options.get('use_llm', False), engine=engine, options=options)
            self.report_progress(90)
            
            if self.is_cancelled:
                return None
            
            if output_format == 'docx':
                self._save_as_docx(text, output_path)
            elif output_format == 'pdf':
                self._save_as_pdf(text, output_path)
            else:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text)
            
            self.report_progress(100)
            return output_path
            
        except Exception as e:
            raise OCRError(str(e))

    def ocr_pdf(self, input_path: str, output_path: str, output_format: str, options: Dict[str, Any]) -> str:
        import fitz
        
        temp_dir = tempfile.mkdtemp(prefix="ocr_pdf_")
        full_content = []
        
        try:
            self.report_progress(5)
            doc = fitz.open(input_path)
            total_pages = len(doc)
            
            for i, page in enumerate(doc):
                if self.is_cancelled:
                    doc.close()
                    return None
                    
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                page_path = os.path.join(temp_dir, f"page_{i}.png")
                pix.save(page_path)
                
                del pix
                gc.collect()
                
                engine = options.get('ocr_engine', 'qwen')
                content = self._extract_text(page_path, output_format, use_llm=options.get('use_llm', False), engine=engine, options=options)
                full_content.append(content)
                
                self.report_progress(5 + int((i + 1) / total_pages * 90))
                
            doc.close()
            
            text_result = "\n\n".join(full_content)

            if output_format == 'docx':
                 self._save_as_docx(text_result, output_path)
            elif output_format == 'pdf':
                 self._save_as_pdf(text_result, output_path)
            else:
                if output_format == 'html':
                    final_output = "\n<hr>\n".join(full_content)
                else:
                    final_output = text_result

                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(final_output)

            self.report_progress(100)
            return output_path

        except Exception as e:
            raise OCRError(str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
