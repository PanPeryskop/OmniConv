import requests
import json
import os
import base64
from pathlib import Path

class LLMService:
    def __init__(self, api_url="http://localhost:1234/api/v1/chat"):
        self.api_url = api_url

    def _send_request(self, payload):
        try:
            response = requests.post(
                self.api_url, 
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=1800
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"LLM request failed: {str(e)}")
            raise e

    def correct_text(self, text: str, output_format: str = 'txt') -> str:
        if not text or not text.strip():
            return text

        system_prompt = "You are a specialized post-OCR text correction assistant. Fix OCR errors, typos, and formatting inconsistencies."
        
        if output_format == 'md':
            system_prompt += (
                " Format the output as proper Markdown. Use # for main headings, ## for subheadings, "
                "- for bullet lists, 1. for numbered lists, **bold** and *italic* for emphasis, "
                "| table | syntax | for tables. Structure content logically. Do NOT add HTML tags."
            )
        elif output_format in ['txt', 'docx', 'pdf']:
            system_prompt += " Output ONLY plain text. Maintain original layout and spacing. Do NOT use Markdown or HTML."
        else:
            system_prompt += " Maintain original meaning and structure. Output ONLY the corrected text."

        payload = {
            "model": "mistralai/ministral-3-3b", 
            "system_prompt": system_prompt,
            "input": text,
            "temperature": 0.3,
            "stream": False
        }

        try:
            result = self._send_request(payload)
            if 'output' in result and len(result['output']) > 0:
                for item in result['output']:
                    if item.get('type') == 'message':
                        return item['content'].strip()
            return text
        except Exception:
            return text

    def generate_html(self, text: str, theme: str = 'light', css_limit: int = None) -> str:
        if not text or not text.strip():
            return "<html><body></body></html>"

        if theme == 'dark':
             theme_prompt = "Use a DARK THEME (dark background #1a1a1a, light text #e0e0e0)."
        else:
             theme_prompt = "Use a LIGHT THEME (white background, dark text)."

        css_limit_instruction = ""
        if css_limit:
            css_limit_instruction = f"IMPORTANT: Limit the CSS styles to approximately {css_limit} characters. Prioritize essential layout and typography."

        prompt = (
            "Convert the provided text into clean, semantically correct HTML5. "
            "Use appropriate tags (h1, h2, p, ul, li, etc.). "
            f"CRITICAL: Add a <style> block in the <head> with CSS to make the document look simple, modern, and beautiful. {theme_prompt} "
            f"{css_limit_instruction} "
            "(e.g., proper typography from Google Fonts like Inter, comfortable spacing, clean layout, subtle shadows). "
            "Format the output as a full HTML document (<!DOCTYPE html>...). "
            "Output ONLY the raw HTML code. Do NOT wrap in markdown code blocks."
            "Keep css reasonable length it cannot be too long. too be honest shorter the better"
        )

        payload = {
            "model": "mistralai/ministral-3-3b", 
            "system_prompt": prompt,
            "input": text,
            "temperature": 0.3,
            "stream": False
        }

        try:
            result = self._send_request(payload)
            html = ""
            if 'output' in result and len(result['output']) > 0:
                for item in result['output']:
                    if item.get('type') == 'message':
                        html = item['content'].strip()
                        break
            
            if not html:
                return f"<html><body><p>{text}</p></body></html>"

            if html.startswith("```html"): html = html[7:]
            if html.startswith("```"): html = html[3:]
            if html.endswith("```"): html = html[:-3]
            return html.strip()

        except Exception:
            return f"<html><body><p>{text.replace(chr(10), '<br>')}</p></body></html>"

    def generate_from_image(self, image_path: str, prompt: str = None) -> str:
        if not prompt:
            prompt = "Transcribe the text from this image exactly as it appears."

        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')

            # Enhanced prompt for structure
            full_prompt = (
                f"{prompt}\n\n"
                "Ensure outstanding formatting. If outputting Markdown, use proper headers, lists, and tables. "
                "If outputting HTML, ensure semantic tags. "
                "Do not include any conversational filler."
            )

            payload = {
                "model": "qwen/qwen3-vl-8b",
                "input": [
                    {
                        "type": "text",
                        "content": full_prompt
                    },
                    {
                        "type": "image",
                        "data_url": f"data:image/jpeg;base64,{base64_image}"
                    }
                ],
                "temperature": 0.1,
                "stream": False
            }

            result = self._send_request(payload)
            if 'output' in result and len(result['output']) > 0:
                for item in result['output']:
                    if item.get('type') == 'message':
                        return item['content'].strip()
            return ""

        except Exception as e:
            print(f"LLM Image generation failed: {str(e)}")
            raise e

    def chat_with_context(self, message: str, previous_response_id: str = None):
        system_msg = None
        if not previous_response_id:
            context = self._get_project_context()
            system_msg = (
                "You are the OmniConv Project Assistant. You are an expert software engineer working on this specific project. "
                "You have full knowledge of the project structure and key files provided below. "
                "Answer questions about the codebase, features, and implementation details accurately. "
                "Note: The system now supports three OCR engines: Qwen (AI), LightOn (Local), and LightOn+Mistral (Local + AI Correction). "
                "Be helpful, concise, and professional.\n\n"
                f"PROJECT CONTEXT:\n{context}"
            )

        payload = {
            "model": "mistralai/ministral-3-3b", 
            "messages": [
                {"role": "system", "content": system_msg} if system_msg else None,
                {"role": "user", "content": message}
            ],
            "temperature": 0.7,
            "stream": True
        }
        payload["messages"] = [m for m in payload["messages"] if m]
        

        payload = {
            "model": "mistralai/ministral-3-3b", 
            "input": message,
            "temperature": 0.7,
            "stream": True,
            "store": True
        }
        
        if system_msg:
            payload["system_prompt"] = system_msg
        
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id

        try:
            with requests.post(self.api_url, json=payload, stream=True, timeout=1800) as response:
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            json_str = line[6:]
                            if json_str.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(json_str)
\
                                
                                content = ""
                                if "choices" in data:
                                    delta = data["choices"][0].get("delta", {})
                                    content = delta.get("content", "")
                                    
                                if not content and "content" in data:
                                    content = data["content"]
                                    
                                if content:
                                    yield content
                                    
                            except json.JSONDecodeError:
                                pass
                                
        except Exception as e:
            yield f"Error: {str(e)}"

    def _get_project_context(self) -> str:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        context = []
        
        ignore_dirs = {'.git', '__pycache__', 'venv', '.venv', 'env', '.env', 'node_modules', '.idea', '.vscode', 'upload', 'output', 'brain', 'Lib', 'site-packages', 'Scripts', 'Include'}
        ignore_files = {'.DS_Store', 'Thumbs.db', 'package-lock.json'}
        
        context.append("File Structure:")
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            rel_path = os.path.relpath(root, project_root)
            if rel_path == '.': rel_path = ''
            
            for f in files:
                if f in ignore_files: continue
                context.append(os.path.join(rel_path, f))

        key_files = ['requirements.txt', 'app/routes/api.py', 'app/services/ocr.py']
        context.append("\nKey File Contents:")
        for kf in key_files:
            kf_path = os.path.join(project_root, kf)
            if os.path.exists(kf_path):
                try:
                    with open(kf_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Truncate if too long
                        if len(content) > 2000: content = content[:2000] + "...[TRUNCATED]"
                        context.append(f"--- {kf} ---\n{content}\n")
                except:
                    pass
                    
        return "\n".join(context)
