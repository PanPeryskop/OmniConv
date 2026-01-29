import os
import uuid
import time
from pathlib import Path
from typing import Tuple, Optional
from werkzeug.utils import secure_filename


FILE_TYPE_MAP = {
    'mp3': 'audio', 'wav': 'audio', 'ogg': 'audio', 'flac': 'audio',
    'm4a': 'audio', 'aac': 'audio', 'ac3': 'audio', 'alac': 'audio',
    'dts': 'audio', 'eac3': 'audio', 'tta': 'audio', 'wv': 'audio',
    'aiff': 'audio', 'ape': 'audio', 'wma': 'audio', 'opus': 'audio',
    'mp4': 'video', 'avi': 'video', 'mkv': 'video', 'mov': 'video',
    'wmv': 'video', 'flv': 'video', 'webm': 'video', '3gp': 'video',
    'mpeg': 'video', 'mpg': 'video', 'm4v': 'video', 'ts': 'video',
    'mts': 'video', 'vob': 'video',
    'jpg': 'image', 'jpeg': 'image', 'png': 'image', 'gif': 'image',
    'bmp': 'image', 'tiff': 'image', 'tif': 'image', 'webp': 'image',
    'ico': 'image', 'heic': 'image', 'heif': 'image',
    'pdf': 'document', 'md': 'document', 'markdown': 'document'
}


def generate_file_id() -> str:
    return str(uuid.uuid4())


def get_file_extension(filename: str) -> str:
    if '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def get_file_type(filename: str) -> Optional[str]:
    ext = get_file_extension(filename)
    return FILE_TYPE_MAP.get(ext)


def validate_file(filename: str, allowed_extensions: set) -> bool:
    ext = get_file_extension(filename)
    return ext in allowed_extensions


def save_uploaded_file(file, upload_folder: Path) -> Tuple[str, str, str]:
    file_id = generate_file_id()
    original_filename = secure_filename(file.filename)
    ext = get_file_extension(original_filename)
    
    saved_filename = f"{file_id}.{ext}" if ext else file_id
    saved_path = upload_folder / saved_filename
    
    file.save(str(saved_path))
    
    return file_id, str(saved_path), original_filename


def get_output_path(output_folder: Path, original_filename: str, output_format: str) -> str:
    base_name = original_filename.rsplit('.', 1)[0] if '.' in original_filename else original_filename
    base_name = secure_filename(base_name)
    
    if output_format == 'pdf_ocr':
        output_format = 'pdf'
    
    job_id = generate_file_id()[:8]
    output_filename = f"{base_name}_{job_id}.{output_format}"
    output_path = output_folder / output_filename
    
    return str(output_path)


def cleanup_old_files(folder: Path, max_age_hours: int = 1) -> int:
    deleted = 0
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    
    for file_path in folder.iterdir():
        if file_path.is_file():
            file_age = current_time - file_path.stat().st_mtime
            if file_age > max_age_seconds:
                try:
                    file_path.unlink()
                    deleted += 1
                except OSError:
                    pass
    
    return deleted


def get_file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)


def download_file_from_url(url: str, upload_folder: Path) -> Tuple[str, str, str]:
    import urllib.request
    from urllib.parse import urlparse
    import tempfile
    
    # Parse filename from URL
    path = urlparse(url).path
    original_filename = os.path.basename(path)
    if not original_filename:
        original_filename = "downloaded_file"
    
    # Sanitize filename
    original_filename = secure_filename(original_filename)
    
    # Generate ID and paths
    file_id = generate_file_id()
    ext = get_file_extension(original_filename)
    if not ext:
        # Try to guess extension from content-type if requests was used, but with urllib it's harder
        # For now assume no extension if not in URL
        pass
        
    saved_filename = f"{file_id}.{ext}" if ext else file_id
    saved_path = upload_folder / saved_filename
    
    # Download
    try:
        urllib.request.urlretrieve(url, str(saved_path))
    except Exception as e:
        raise Exception(f"Failed to download file: {str(e)}")
        
    return file_id, str(saved_path), original_filename
