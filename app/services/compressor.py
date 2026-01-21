import os
import subprocess
import tempfile
from typing import Optional, Callable, Dict, Any
from pathlib import Path
from PIL import Image
from pydub import AudioSegment


class BaseCompressor:
    def __init__(self, progress_callback: Optional[Callable[[int], None]] = None):
        self.progress_callback = progress_callback
        self.is_cancelled = False

    def report_progress(self, progress: int):
        if self.progress_callback:
            self.progress_callback(min(100, max(0, progress)))

    def cancel(self):
        self.is_cancelled = True


class VideoCompressor(BaseCompressor):
    SUPPORTED_FORMATS = {'mp4', 'avi', 'mkv', 'mov', 'webm', 'wmv', 'flv', 'm4v'}
    
    def compress(
        self,
        input_path: str,
        output_path: str,
        target_size_mb: float,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        from moviepy import VideoFileClip
        
        options = options or {}
        self.report_progress(5)
        
        video = VideoFileClip(input_path)
        duration = video.duration
        original_width = video.w
        original_height = video.h
        video.close()
        
        self.report_progress(10)
        
        target_size_bits = target_size_mb * 8 * 1024 * 1024
        audio_bitrate = 128000
        video_bitrate = int((target_size_bits / duration) - audio_bitrate)
        video_bitrate = max(100000, video_bitrate)
        
        self.report_progress(20)
        
        scale_filter = ""
        if video_bitrate < 500000 and original_width > 1280:
            scale_filter = "-vf scale=1280:-2"
        elif video_bitrate < 300000 and original_width > 854:
            scale_filter = "-vf scale=854:-2"
        elif video_bitrate < 150000 and original_width > 640:
            scale_filter = "-vf scale=640:-2"
        
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-c:v', 'libx264',
            '-b:v', f'{video_bitrate}',
            '-maxrate', f'{int(video_bitrate * 1.5)}',
            '-bufsize', f'{int(video_bitrate * 2)}',
            '-preset', 'slow',
            '-c:a', 'aac',
            '-b:a', '128k',
        ]
        
        if scale_filter:
            cmd.extend(scale_filter.split())
        
        cmd.append(output_path)
        
        self.report_progress(30)
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        self.report_progress(50)
        process.wait()
        self.report_progress(90)
        
        if process.returncode != 0 and not os.path.exists(output_path):
            raise Exception("Video compression failed")
        
        self.report_progress(100)
        return output_path

    @staticmethod
    def get_supported_formats() -> set:
        return VideoCompressor.SUPPORTED_FORMATS


class AudioCompressor(BaseCompressor):
    SUPPORTED_FORMATS = {'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac', 'wma'}
    BITRATE_STEPS = ['320k', '256k', '192k', '160k', '128k', '96k', '64k']
    
    def compress(
        self,
        input_path: str,
        output_path: str,
        target_size_mb: float,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        options = options or {}
        self.report_progress(10)
        
        audio = AudioSegment.from_file(input_path)
        self.report_progress(30)
        
        if self.is_cancelled:
            return None
        
        target_size_bytes = target_size_mb * 1024 * 1024
        duration_seconds = len(audio) / 1000
        
        target_bitrate_kbps = int((target_size_bytes * 8) / duration_seconds / 1000)
        target_bitrate_kbps = max(32, min(320, target_bitrate_kbps))
        
        selected_bitrate = '64k'
        for bitrate in self.BITRATE_STEPS:
            bitrate_val = int(bitrate.replace('k', ''))
            if bitrate_val <= target_bitrate_kbps:
                selected_bitrate = bitrate
                break
        
        self.report_progress(50)
        
        output_format = Path(output_path).suffix.lstrip('.').lower()
        if output_format == 'm4a':
            output_format = 'mp4'
        
        audio.export(
            output_path,
            format=output_format if output_format != 'mp3' else 'mp3',
            bitrate=selected_bitrate
        )
        
        self.report_progress(100)
        return output_path

    @staticmethod
    def get_supported_formats() -> set:
        return AudioCompressor.SUPPORTED_FORMATS


class ImageCompressor(BaseCompressor):
    SUPPORTED_FORMATS = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'}
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._register_heif_support()
    
    def _register_heif_support(self):
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass
    
    def compress(
        self,
        input_path: str,
        output_path: str,
        target_size_mb: float,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        options = options or {}
        self.report_progress(10)
        
        image = Image.open(input_path)
        original_size = os.path.getsize(input_path)
        target_size_bytes = target_size_mb * 1024 * 1024
        
        if original_size <= target_size_bytes:
            image.save(output_path, quality=95, optimize=True)
            self.report_progress(100)
            return output_path
        
        self.report_progress(20)
        
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            if image.mode in ('RGBA', 'LA'):
                background.paste(image, mask=image.split()[-1])
                image = background
            else:
                image = image.convert('RGB')
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        self.report_progress(30)
        
        quality_levels = [95, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40]
        
        for quality in quality_levels:
            if self.is_cancelled:
                return None
            
            temp_path = output_path + '.temp.jpg'
            image.save(temp_path, 'JPEG', quality=quality, optimize=True)
            
            current_size = os.path.getsize(temp_path)
            progress = 30 + int((95 - quality) / 55 * 40)
            self.report_progress(progress)
            
            if current_size <= target_size_bytes:
                os.rename(temp_path, output_path)
                self.report_progress(100)
                return output_path
            
            os.remove(temp_path)
        
        self.report_progress(75)
        
        scale_factors = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
        
        for scale in scale_factors:
            if self.is_cancelled:
                return None
            
            new_width = int(image.width * scale)
            new_height = int(image.height * scale)
            resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            temp_path = output_path + '.temp.jpg'
            resized.save(temp_path, 'JPEG', quality=70, optimize=True)
            
            current_size = os.path.getsize(temp_path)
            progress = 75 + int((1 - scale) / 0.7 * 20)
            self.report_progress(progress)
            
            if current_size <= target_size_bytes:
                os.rename(temp_path, output_path)
                self.report_progress(100)
                return output_path
            
            os.remove(temp_path)
        
        final_width = int(image.width * 0.25)
        final_height = int(image.height * 0.25)
        final_image = image.resize((final_width, final_height), Image.Resampling.LANCZOS)
        final_image.save(output_path, 'JPEG', quality=60, optimize=True)
        
        self.report_progress(100)
        return output_path

    @staticmethod
    def get_supported_formats() -> set:
        return ImageCompressor.SUPPORTED_FORMATS
