from typing import Optional, Dict, Any
from pathlib import Path

from .converter import BaseConverter
from ..utils.exceptions import ConversionError, UnsupportedFormatError


class VideoConverter(BaseConverter):
    INPUT_FORMATS = {
        'mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm',
        '3gp', 'mpeg', 'mpg', 'm4v', 'ts', 'mts', 'vob'
    }
    
    OUTPUT_FORMATS = {'mp4', 'webm', 'avi', 'mkv', 'mov', 'gif'}
    AUDIO_OUTPUT_FORMATS = {'mp3', 'wav', 'aac', 'ogg'}
    
    VIDEO_CODECS = {
        'mp4': 'libx264',
        'webm': 'libvpx',
        'avi': 'mpeg4',
        'mkv': 'libx264',
        'mov': 'libx264',
    }
    
    def convert(
        self,
        input_path: str,
        output_path: str,
        output_format: str,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        from moviepy import VideoFileClip
        
        options = options or {}
        output_format = output_format.lower()
        
        try:
            self.report_progress(5)
            
            if output_format in self.AUDIO_OUTPUT_FORMATS:
                return self._extract_audio(input_path, output_path, output_format, options)
            
            if output_format == 'gif':
                return self._create_gif(input_path, output_path, options)
            
            if output_format not in self.OUTPUT_FORMATS:
                raise UnsupportedFormatError(output_format, list(self.OUTPUT_FORMATS))
            
            video = VideoFileClip(input_path)
            self.report_progress(20)
            
            if self.is_cancelled:
                video.close()
                return None
            
            video = self._apply_options(video, options)
            self.report_progress(30)
            
            codec = self.VIDEO_CODECS.get(output_format, 'libx264')
            
            video.write_videofile(
                output_path,
                codec=codec,
                audio_codec='aac' if output_format != 'webm' else 'libvorbis',
                logger=None
            )
            
            video.close()
            self.report_progress(100)
            
            return output_path
            
        except Exception as e:
            raise ConversionError(f"Video conversion failed: {str(e)}")
    
    def _extract_audio(self, input_path: str, output_path: str, output_format: str, options: Dict[str, Any]) -> str:
        from moviepy import VideoFileClip
        
        try:
            video = VideoFileClip(input_path)
            self.report_progress(30)
            
            if video.audio is None:
                video.close()
                raise ConversionError("Video has no audio track")
            
            audio = video.audio
            audio.write_audiofile(output_path, logger=None)
            video.close()
            self.report_progress(100)
            
            return output_path
            
        except ConversionError:
            raise
        except Exception as e:
            raise ConversionError(f"Audio extraction failed: {str(e)}")
    
    def _create_gif(self, input_path: str, output_path: str, options: Dict[str, Any]) -> str:
        from moviepy import VideoFileClip
        
        try:
            video = VideoFileClip(input_path)
            self.report_progress(20)
            
            max_duration = options.get('max_duration', 10)
            if video.duration > max_duration:
                video = video.subclipped(0, max_duration)
            
            target_width = options.get('width', 480)
            if video.w > target_width:
                video = video.resized(width=target_width)
            
            self.report_progress(40)
            
            fps = options.get('fps', 10)
            video.write_gif(output_path, fps=fps, logger=None)
            video.close()
            self.report_progress(100)
            
            return output_path
            
        except Exception as e:
            raise ConversionError(f"GIF creation failed: {str(e)}")
    
    def _apply_options(self, video, options: Dict[str, Any]):
        if 'width' in options:
            video = video.resized(width=options['width'])
        elif 'height' in options:
            video = video.resized(height=options['height'])
        
        if 'fps' in options:
            video = video.with_fps(options['fps'])
        
        if 'start' in options or 'end' in options:
            start = options.get('start', 0)
            end = options.get('end', video.duration)
            video = video.subclipped(start, end)
        
        return video
    
    @staticmethod
    def get_supported_input_formats() -> set:
        return VideoConverter.INPUT_FORMATS
    
    @staticmethod
    def get_supported_output_formats() -> set:
        return VideoConverter.OUTPUT_FORMATS | VideoConverter.AUDIO_OUTPUT_FORMATS
