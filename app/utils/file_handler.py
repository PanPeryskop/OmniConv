import ipaddress
import mimetypes
import os
import re
import shutil
import socket
import urllib.request
import uuid
import time
from urllib.parse import unquote, urlparse
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
    base_name = re.sub(r'(_[0-9a-f]{8})+$', '', secure_filename(base_name)) or 'file'
    
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


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_remote_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_remote_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Only http and https links are supported')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    try:
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError(f'Host not found: {parsed.hostname}')
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split('%')[0])
        if getattr(ip, 'ipv4_mapped', None):
            ip = ip.ipv4_mapped
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError('This address cannot be downloaded from')


def _url_opener():
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.UnknownHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        _SafeRedirectHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def download_file_from_url(url: str, upload_folder: Path) -> Tuple[str, str, str]:
    url = (url or '').strip()
    check_remote_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 OmniConv'})
    file_id = generate_file_id()
    saved_path = None
    try:
        with _url_opener().open(request, timeout=30) as response:
            original_filename = secure_filename(
                response.headers.get_filename() or unquote(os.path.basename(urlparse(response.geturl()).path))
            ) or 'downloaded_file'
            if not get_file_extension(original_filename):
                guessed = mimetypes.guess_extension((response.headers.get_content_type() or '').lower())
                if guessed:
                    original_filename += guessed
            ext = get_file_extension(original_filename)
            saved_path = upload_folder / (f"{file_id}.{ext}" if ext else file_id)
            with open(saved_path, 'wb') as out:
                shutil.copyfileobj(response, out, 1024 * 1024)
    except ValueError:
        raise
    except Exception as e:
        if saved_path and os.path.exists(saved_path):
            os.remove(saved_path)
        raise Exception(f"Failed to download file: {str(e)}")

    return file_id, str(saved_path), original_filename
