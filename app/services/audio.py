from typing import Optional, Dict, Any
from pydub import AudioSegment

from .converter import BaseConverter
from ..utils.exceptions import ConversionError, UnsupportedFormatError


class AudioConverter(BaseConverter):
    INPUT_FORMATS = {
        'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac', 'ac3', 'alac',
        'dts', 'eac3', 'tta', 'wv', 'aiff', 'ape', 'wma', 'opus'
    }
    
    # AAC disabled - conversion not working
    OUTPUT_FORMATS = {'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aiff'}
    
    FORMAT_CODECS = {
        'mp3': 'libmp3lame',
        # 'aac': 'aac',  # Disabled - not working
        'm4a': 'aac',
        'ogg': 'libvorbis',
        'flac': 'flac',
        'wav': None,
        'aiff': None,
    }
    
    DEFAULT_BITRATES = {
        'mp3': '192k',
        # 'aac': '192k',  # Disabled - not working
        'm4a': '192k',
        'ogg': '192k',
    }
    
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
        
        try:
            self.report_progress(10)
            audio = AudioSegment.from_file(input_path)
            self.report_progress(40)
            
            if self.is_cancelled:
                return None
            
            export_params = self._get_export_params(output_format, options)
            self.report_progress(60)
            audio.export(output_path, **export_params)
            self.report_progress(100)
            
            return output_path
            
        except Exception as e:
            raise ConversionError(f"Audio conversion failed: {str(e)}")
    
    def _get_export_params(self, output_format: str, options: Dict[str, Any]) -> Dict[str, Any]:
        params = {'format': output_format}
        
        codec = self.FORMAT_CODECS.get(output_format)
        if codec:
            params['codec'] = codec
        
        if output_format in self.DEFAULT_BITRATES:
            bitrate = options.get('bitrate', self.DEFAULT_BITRATES[output_format])
            params['bitrate'] = bitrate
        
        if 'sample_rate' in options:
            params['parameters'] = ['-ar', str(options['sample_rate'])]
        
        return params
    
    @staticmethod
    def get_supported_input_formats() -> set:
        return AudioConverter.INPUT_FORMATS
    
    @staticmethod
    def get_supported_output_formats() -> set:
        return AudioConverter.OUTPUT_FORMATS
