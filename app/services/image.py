from typing import Optional, Dict, Any
from PIL import Image

from .converter import BaseConverter
from ..utils.exceptions import ConversionError, UnsupportedFormatError


class ImageConverter(BaseConverter):
    INPUT_FORMATS = {
        'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif',
        'webp', 'ico', 'heic', 'heif'
    }
    
    OUTPUT_FORMATS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tiff', 'ico', 'pdf', 'txt', 'pdf_ocr'}
    RGB_ONLY_FORMATS = {'jpg', 'jpeg', 'bmp', 'pdf'}
    DEFAULT_QUALITY = 90
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._register_heif_support()
    
    def _register_heif_support(self):
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass
    
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
            
        if output_format in ('txt', 'pdf_ocr'):
            from .ocr import OCRService
            ocr = OCRService(self._progress_callback)
            
            if output_format == 'txt':
                return ocr.ocr_image(input_path, output_path, options)
            elif output_format == 'pdf_ocr':
                try:
                    self.report_progress(10)
                    import tempfile
                    
                    temp_pdf = tempfile.mktemp(suffix=".pdf")
                    image = Image.open(input_path)
                    if image.mode != 'RGB':
                        image = image.convert('RGB')
                    image.save(temp_pdf, "PDF", resolution=100.0)
                    
                    self.report_progress(30)
                    
                    result = ocr.ocr_pdf_to_searchable(temp_pdf, output_path, options)
                    
                    try:
                        import os
                        os.remove(temp_pdf)
                    except:
                        pass
                        
                    return result
                    
                except Exception as e:
                    raise ConversionError(str(e))
        
        try:
            self.report_progress(10)
            image = Image.open(input_path)
            self.report_progress(30)
            
            if self.is_cancelled:
                return None
            
            image = self._apply_options(image, options)
            self.report_progress(50)
            
            image = self._ensure_compatible_mode(image, output_format)
            self.report_progress(70)
            
            save_options = self._get_save_options(output_format, options)
            
            if output_format == 'ico':
                self._save_ico(image, output_path, options)
            else:
                image.save(output_path, **save_options)
            
            self.report_progress(100)
            return output_path
            
        except Exception as e:
            raise ConversionError(f"Image conversion failed: {str(e)}")
    
    def _apply_options(self, image: Image.Image, options: Dict[str, Any]) -> Image.Image:
        if 'width' in options or 'height' in options:
            width = options.get('width')
            height = options.get('height')
            
            if width and height:
                image = image.resize((width, height), Image.Resampling.LANCZOS)
            elif width:
                ratio = width / image.width
                new_height = int(image.height * ratio)
                image = image.resize((width, new_height), Image.Resampling.LANCZOS)
            elif height:
                ratio = height / image.height
                new_width = int(image.width * ratio)
                image = image.resize((new_width, height), Image.Resampling.LANCZOS)
        
        if 'max_dimension' in options:
            max_dim = options['max_dimension']
            if image.width > max_dim or image.height > max_dim:
                ratio = min(max_dim / image.width, max_dim / image.height)
                new_size = (int(image.width * ratio), int(image.height * ratio))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        if 'rotate' in options:
            image = image.rotate(options['rotate'], expand=True)
        
        return image
    
    def _ensure_compatible_mode(self, image: Image.Image, output_format: str) -> Image.Image:
        if output_format in self.RGB_ONLY_FORMATS:
            if image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                if image.mode in ('RGBA', 'LA'):
                    background.paste(image, mask=image.split()[-1])
                    return background
                return image.convert('RGB')
            elif image.mode != 'RGB':
                return image.convert('RGB')
        return image
    
    def _get_save_options(self, output_format: str, options: Dict[str, Any]) -> Dict[str, Any]:
        save_options = {}
        format_map = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'tiff': 'TIFF', 'tif': 'TIFF'}
        save_options['format'] = format_map.get(output_format, output_format.upper())
        
        if output_format in {'jpg', 'jpeg', 'webp'}:
            save_options['quality'] = options.get('quality', self.DEFAULT_QUALITY)
        
        if output_format == 'webp':
            save_options['method'] = 4
        
        if output_format == 'png':
            save_options['optimize'] = True
        
        if output_format == 'gif':
            save_options['optimize'] = True
        
        return save_options
    
    def _save_ico(self, image: Image.Image, output_path: str, options: Dict[str, Any]):
        sizes = options.get('ico_sizes', [(16, 16), (32, 32), (48, 48), (256, 256)])
        
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        images = []
        for size in sizes:
            resized = image.copy()
            resized.thumbnail(size, Image.Resampling.LANCZOS)
            images.append(resized)
        
        images[0].save(output_path, format='ICO', sizes=[(img.width, img.height) for img in images])
    
    @staticmethod
    def get_supported_input_formats() -> set:
        return ImageConverter.INPUT_FORMATS
    
    @staticmethod
    def get_supported_output_formats() -> set:
        return ImageConverter.OUTPUT_FORMATS
