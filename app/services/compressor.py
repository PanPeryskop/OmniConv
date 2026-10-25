import os
import glob
import shutil
import subprocess
import tempfile
from typing import Optional, Callable, Dict, Any, List, Tuple
from pathlib import Path
from PIL import Image
from pydub import AudioSegment

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class CompressionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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
        
        cmd[1:1] = ['-progress', 'pipe:1', '-nostats', '-loglevel', 'error']

        self.report_progress(30)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=NO_WINDOW
        )

        for line in process.stdout:
            if self.is_cancelled:
                process.kill()
                return None
            if line.startswith('out_time_us=') or line.startswith('out_time_ms='):
                try:
                    seconds = int(line.split('=', 1)[1]) / 1_000_000
                except ValueError:
                    continue
                self.report_progress(30 + int(min(1.0, seconds / duration) * 65))

        process.wait()

        if process.returncode != 0 or not os.path.exists(output_path):
            raise CompressionError('err_compress_failed', "Video compression failed")
        
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
        output_format = {'m4a': 'ipod', 'aac': 'adts'}.get(output_format, output_format)

        audio.export(
            output_path,
            format=output_format,
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

        if original_size <= target_size_bytes:
            image.save(output_path, 'JPEG', quality=95, optimize=True)
            self.report_progress(100)
            return output_path

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


class PdfCompressor(BaseCompressor):
    SUPPORTED_FORMATS = {'pdf'}

    PRESETS = {
        'lossless': None,
        'balanced': (150, 80),
        'strong': (110, 65),
        'extreme': (72, 45),
    }
    TARGET_LADDER = [
        (220, 85), (150, 80), (130, 72), (110, 65),
        (96, 55), (72, 45), (60, 35), (50, 25),
    ]
    GS_TIMEOUT = 900

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.info: Dict[str, Any] = {}

    @staticmethod
    def find_ghostscript() -> Optional[str]:
        for name in ('gswin64c', 'gswin32c', 'gs'):
            path = shutil.which(name)
            if path:
                return path
        if os.name == 'nt':
            for pattern in (r'C:\Program Files\gs\gs*\bin\gswin64c.exe',
                            r'C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe'):
                matches = sorted(glob.glob(pattern))
                if matches:
                    return matches[-1]
        return None

    def compress(
        self,
        input_path: str,
        output_path: str,
        target_size_mb: float,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        import fitz

        options = options or {}
        mode = options.get('mode', 'balanced')
        if mode not in self.PRESETS and mode != 'target':
            mode = 'balanced'
        grayscale = bool(options.get('grayscale'))
        strip_metadata = bool(options.get('strip_metadata'))

        original_size = os.path.getsize(input_path)
        target_bytes = target_size_mb * 1024 * 1024 if mode == 'target' else None

        with fitz.open(input_path) as doc:
            if doc.needs_pass:
                raise CompressionError('err_pdf_password', "PDF is password protected - remove the password first")
            page_count = doc.page_count
            has_forms = bool(doc.is_form_pdf)

        gs_path = None if has_forms else self.find_ghostscript()
        self.info = {
            'mode': mode,
            'engines': ['mupdf'] + (['ghostscript'] if gs_path else []),
            'pages': page_count,
        }
        self.report_progress(5)

        with tempfile.TemporaryDirectory(prefix='omniconv_pdf_') as tmp:
            best_path, best_size = None, original_size

            def consider(path: Optional[str], label: str):
                nonlocal best_path, best_size
                if not path or not os.path.exists(path):
                    return
                if not self._is_valid(path, page_count):
                    return
                size = os.path.getsize(path)
                if size < best_size:
                    best_path, best_size = path, size
                    self.info['engine'] = label

            consider(self._structural(input_path, os.path.join(tmp, 'lossless.pdf'),
                                      strip_metadata=strip_metadata, subset=True),
                     'mupdf-lossless')
            self.report_progress(15)

            if mode == 'target':
                levels = self.TARGET_LADDER
            elif self.PRESETS[mode] is None:
                levels = []
            else:
                levels = [self.PRESETS[mode]]

            if not levels and grayscale:
                levels = [(300, 90)]

            for i, (dpi, quality) in enumerate(levels):
                if self.is_cancelled:
                    return None
                if target_bytes and best_size <= target_bytes:
                    break

                span = 80 / max(1, len(levels))
                base = 15 + i * span

                if gs_path:
                    gs_out = self._ghostscript(gs_path, input_path,
                                               os.path.join(tmp, f'gs_{dpi}_{quality}.pdf'),
                                               dpi, quality, grayscale)
                    if gs_out:
                        consider(self._structural(gs_out, os.path.join(tmp, f'gs_{dpi}_{quality}_s.pdf'),
                                                  strip_metadata=strip_metadata, subset=False),
                                 f'ghostscript {dpi} dpi / q{quality}')
                self.report_progress(int(base + span / 2))

                if self.is_cancelled:
                    return None

                consider(self._mupdf_images(input_path, os.path.join(tmp, f'mu_{dpi}_{quality}.pdf'),
                                            dpi, quality, grayscale, strip_metadata),
                         f'mupdf {dpi} dpi / q{quality}')
                self.report_progress(int(base + span))

            if best_path:
                shutil.copyfile(best_path, output_path)
                self.info['kept_original'] = False
            else:
                shutil.copyfile(input_path, output_path)
                self.info['kept_original'] = True
                self.info['engine'] = 'original'

        if target_bytes is not None:
            self.info['target_reached'] = os.path.getsize(output_path) <= target_bytes

        self.report_progress(100)
        return output_path

    @staticmethod
    def _is_valid(path: str, page_count: int) -> bool:
        import fitz
        try:
            with fitz.open(path) as doc:
                if doc.page_count != page_count:
                    return False
                doc[0].get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
            return True
        except Exception:
            return False

    @staticmethod
    def _save_structural(doc, out_path: str, strip_metadata: bool):
        if strip_metadata:
            doc.set_metadata({})
            doc.del_xml_metadata()
        doc.save(
            out_path,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            use_objstms=1,
        )

    def _structural(self, in_path: str, out_path: str, strip_metadata: bool,
                    subset: bool) -> Optional[str]:
        import fitz
        try:
            with fitz.open(in_path) as doc:
                if subset:
                    try:
                        doc.subset_fonts()
                    except Exception:
                        pass
                self._save_structural(doc, out_path, strip_metadata)
            return out_path
        except Exception:
            return None

    def _mupdf_images(self, in_path: str, out_path: str, dpi: int, quality: int,
                      grayscale: bool, strip_metadata: bool) -> Optional[str]:
        import fitz
        try:
            with fitz.open(in_path) as doc:
                doc.rewrite_images(
                    dpi_threshold=int(dpi * 1.1),
                    dpi_target=dpi,
                    quality=quality,
                    set_to_gray=grayscale,
                )
                try:
                    doc.subset_fonts()
                except Exception:
                    pass
                self._save_structural(doc, out_path, strip_metadata)
            return out_path
        except Exception:
            return None

    @staticmethod
    def _qfactor(quality: int) -> float:
        quality = max(1, min(100, quality))
        scale = 5000 / quality if quality < 50 else 200 - 2 * quality
        return round(max(0.05, scale / 100), 3)

    def _ghostscript(self, gs_path: str, in_path: str, out_path: str,
                     dpi: int, quality: int, grayscale: bool) -> Optional[str]:
        qf = self._qfactor(quality)
        chroma = '[1 1 1 1]' if quality >= 80 else '[2 1 1 2]'
        mono_dpi = 300 if dpi >= 100 else 200
        cmd: List[str] = [
            gs_path, '-q', '-dNOPAUSE', '-dBATCH', '-dSAFER',
            '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.7',
            '-dDetectDuplicateImages=true', '-dCompressFonts=true',
            '-dSubsetFonts=true', '-dEmbedAllFonts=true',
            '-dPrinted=false', '-dPreserveAnnots=true',
            f'-dPassThroughJPEGImages={"true" if quality >= 80 else "false"}',
            '-dDownsampleColorImages=true', '-dColorImageDownsampleType=/Bicubic',
            f'-dColorImageResolution={dpi}', '-dColorImageDownsampleThreshold=1.1',
            '-dAutoFilterColorImages=false', '-dColorImageFilter=/DCTEncode',
            '-dDownsampleGrayImages=true', '-dGrayImageDownsampleType=/Bicubic',
            f'-dGrayImageResolution={dpi}', '-dGrayImageDownsampleThreshold=1.1',
            '-dAutoFilterGrayImages=false', '-dGrayImageFilter=/DCTEncode',
            '-dDownsampleMonoImages=true', '-dMonoImageDownsampleType=/Subsample',
            f'-dMonoImageResolution={mono_dpi}', '-dMonoImageDownsampleThreshold=1.5',
        ]
        if grayscale:
            cmd += ['-sColorConversionStrategy=Gray', '-dProcessColorModel=/DeviceGray']
        cmd += [
            f'-sOutputFile={out_path}',
            '-c',
            f'<< /ColorImageDict << /QFactor {qf} /Blend 1 /HSamples {chroma} /VSamples {chroma} >> '
            f'/GrayImageDict << /QFactor {qf} /Blend 1 /HSamples [1 1 1 1] /VSamples [1 1 1 1] >> '
            '>> setdistillerparams',
            '-f', in_path,
        ]
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=self.GS_TIMEOUT, creationflags=NO_WINDOW
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if result.returncode != 0 or not os.path.exists(out_path):
            return None
        return out_path

    @staticmethod
    def get_supported_formats() -> set:
        return PdfCompressor.SUPPORTED_FORMATS
