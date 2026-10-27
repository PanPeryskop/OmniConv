from typing import Dict, Any, List, Optional, Tuple
import yt_dlp
import os
import re
import time
import logging

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    def __init__(self, message: str, category: str = 'unknown', retry_possible: bool = False):
        super().__init__(message)
        self.category = category
        self.retry_possible = retry_possible


class VideoDownloaderService:
    MAX_RETRIES = 3
    NO_PREMIUM = '[format_note!*=?Premium]'
    INVISIBLE_CHARS = re.compile(r'[\s​-‏‪-‮⁠﻿]+')
    RETRY_DELAY = 2
    SOCKET_TIMEOUT = 30

    SINGLE_FORMAT_PLATFORMS = {
        'instagram', 'tiktok', 'twitter', 'reddit', 'facebook',
        'threads', 'snapchat', 'pinterest',
    }

    def __init__(self, download_path: str, cookies_file: Optional[str] = None):
        self.download_path = download_path
        self.cookies_file = cookies_file
        os.makedirs(download_path, exist_ok=True)

    def _get_base_opts(self, use_cookies: bool = True) -> dict:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'force_ipv4': True,
            'geo_bypass': True,
            'socket_timeout': self.SOCKET_TIMEOUT,
            'retries': 5,
            'fragment_retries': 5,
            'file_access_retries': 3,
            'extractor_retries': 3,
            'overwrites': True,
            'restrictfilenames': False,
            'windowsfilenames': True,
            'merge_output_format': 'mp4',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Sec-Ch-Ua': '"Chromium";v="126", "Google Chrome";v="126"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
            },
        }

        if use_cookies and self.cookies_file and os.path.exists(self.cookies_file):
            opts['cookiefile'] = self.cookies_file

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ffmpeg_path = os.path.join(base_dir, 'dist', 'OmniConv', 'ffmpeg', 'ffmpeg.exe')
        if os.path.exists(ffmpeg_path):
            opts['ffmpeg_location'] = os.path.dirname(ffmpeg_path)

        return opts

    @staticmethod
    def _classify_error(error: Exception) -> Tuple[str, str, bool]:
        msg = str(error).lower()

        if any(kw in msg for kw in ['login', 'sign in', 'authentication', 'cookie', 'session', '401', '403 forbidden']):
            return (
                'auth',
                'This content requires login. Try configuring browser cookies or use a cookies.txt file.',
                False
            )

        if any(kw in msg for kw in ['geo', 'not available in your country', 'blocked', 'geo_restricted']):
            return (
                'geo_blocked',
                'This content is not available in your region.',
                False
            )

        if any(kw in msg for kw in ['age', 'age-restricted', 'age_limit']):
            return (
                'age_restricted',
                'This content is age-restricted. Try configuring browser cookies.',
                False
            )

        if any(kw in msg for kw in ['429', 'rate limit', 'too many requests', 'throttl']):
            return (
                'rate_limited',
                'Too many requests. Please wait a minute and try again.',
                True
            )

        if any(kw in msg for kw in ['private', 'not public', 'is private']):
            return (
                'private',
                'This content is private and cannot be downloaded.',
                False
            )

        if any(kw in msg for kw in ['404', 'not found', 'removed', 'deleted', 'does not exist', 'unavailable']):
            return (
                'not_found',
                'Content not found. It may have been removed or the URL is incorrect.',
                False
            )

        if any(kw in msg for kw in ['timeout', 'timed out', 'connection', 'network', 'socket', 'urlopen', 'eof', 'reset by peer']):
            return (
                'network',
                'Network error. Check your internet connection and try again.',
                True
            )

        if any(kw in msg for kw in ['unsupported url', 'no video', 'unable to extract', 'not a valid url']):
            return (
                'unsupported',
                'This URL is not supported or does not contain downloadable media.',
                False
            )

        if any(kw in msg for kw in ['format', 'requested format', 'no video formats']):
            return (
                'format_error',
                'The requested format is not available. Try a different quality.',
                True
            )

        return (
            'unknown',
            f'Download error: {str(error)[:200]}',
            True
        )

    def _detect_platform(self, url: str) -> Optional[str]:
        url_lower = url.lower()
        platforms = {
            'youtube': ['youtube.com', 'youtu.be'],
            'instagram': ['instagram.com', 'instagr.am'],
            'tiktok': ['tiktok.com', 'vm.tiktok.com'],
            'twitter': ['twitter.com', 'x.com', 't.co'],
            'facebook': ['facebook.com', 'fb.watch', 'fb.com'],
            'reddit': ['reddit.com', 'redd.it'],
            'vimeo': ['vimeo.com'],
            'twitch': ['twitch.tv', 'clips.twitch.tv'],
            'dailymotion': ['dailymotion.com', 'dai.ly'],
            'threads': ['threads.net'],
            'pinterest': ['pinterest.com', 'pin.it'],
            'snapchat': ['snapchat.com'],
            'bilibili': ['bilibili.com', 'b23.tv'],
            'soundcloud': ['soundcloud.com'],
            'spotify': ['spotify.com', 'open.spotify.com'],
        }
        for platform, domains in platforms.items():
            if any(domain in url_lower for domain in domains):
                return platform
        return None

    def _execute_with_retry(self, operation, url: str, ydl_opts: dict, max_retries: int = None):
        retries = max_retries or self.MAX_RETRIES
        last_error = None

        for attempt in range(retries + 1):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return operation(ydl, url)
            except Exception as e:
                last_error = e
                category, user_msg, retry_possible = self._classify_error(e)

                if not retry_possible or attempt >= retries:
                    logger.error(f"Download failed (attempt {attempt + 1}/{retries + 1}): {category} - {e}")
                    raise DownloadError(user_msg, category=category, retry_possible=retry_possible)

                wait_time = self.RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1} failed ({category}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

        raise DownloadError(str(last_error), category='unknown', retry_possible=False)

    def get_video_info(self, url: str) -> Dict[str, Any]:
        platform = self._detect_platform(url)

        ydl_opts = self._get_base_opts()
        ydl_opts['extract_flat'] = 'in_playlist'

        if platform == 'spotify':
            is_playlist = 'playlist' in url or 'album' in url
            return {
                'title': 'Spotify Media',
                'uploader': 'Spotify',
                'thumbnail': '',
                'duration': None,
                'is_playlist': is_playlist,
                'platform': 'spotify',
                'entries': [],
                'playlist_count': 0,
                'formats': [{
                    'format_id': 'bestaudio/best',
                    'ext': 'mp3',
                    'resolution': 'Audio Only',
                    'filesize': None,
                    'note': 'Spotify 320kbps MP3',
                }]
            }

        def _extract(ydl, url):
            return ydl.extract_info(url, download=False)

        info = self._execute_with_retry(_extract, url, ydl_opts)

        is_playlist = 'entries' in info and info.get('_type') == 'playlist'

        result = {
            'title': info.get('title') or info.get('fulltitle') or 'Unknown',
            'uploader': info.get('uploader') or info.get('channel') or info.get('uploader_id') or '',
            'thumbnail': info.get('thumbnail'),
            'duration': info.get('duration'),
            'is_playlist': is_playlist,
            'platform': platform or 'other',
            'entries': [],
            'playlist_count': 0,
        }

        if is_playlist:
            entries_data = list(info.get('entries', []))
            result['playlist_count'] = len(entries_data)
            for entry in entries_data:
                if entry:
                    result['entries'].append({
                        'id': entry.get('id'),
                        'title': entry.get('title'),
                        'duration': entry.get('duration'),
                    })
        else:
            if platform in self.SINGLE_FORMAT_PLATFORMS:
                result['formats'] = [{
                    'format_id': 'best',
                    'ext': 'mp4',
                    'resolution': 'Best Available',
                    'filesize': None,
                    'note': 'best quality',
                }]
            else:
                result['formats'] = self._get_formats(url)

        return result

    def _get_formats(self, url: str) -> List[Dict[str, Any]]:
        ydl_opts = self._get_base_opts()

        def _extract(ydl, url):
            return ydl.extract_info(url, download=False)

        info = self._execute_with_retry(_extract, url, ydl_opts)

        formats = []
        seen = set()

        raw_formats = info.get('formats', [])

        for f in raw_formats:
            if f.get('vcodec') == 'none':
                continue
            if 'premium' in (f.get('format_note') or '').lower():
                continue

            resolution = f.get('resolution') or f.get('format_note') or ''
            if not resolution and f.get('height'):
                resolution = f"{f.get('height')}p"
            if not resolution:
                continue

            if resolution in seen:
                continue
            seen.add(resolution)

            formats.append({
                'format_id': f.get('format_id'),
                'ext': f.get('ext', 'mp4'),
                'resolution': resolution,
                'filesize': f.get('filesize') or f.get('filesize_approx'),
                'note': f.get('format_note', ''),
            })

        def sort_key(fmt):
            note = fmt.get('note', '') or ''
            res = fmt.get('resolution', '') or ''
            for s in [res, note]:
                for part in s.replace('p', ' ').split():
                    try:
                        return -int(part)
                    except ValueError:
                        continue
            return 0

        formats.sort(key=sort_key)

        if formats:
            formats.insert(0, {
                'format_id': 'bestvideo+bestaudio/best',
                'ext': 'mp4',
                'resolution': 'Best Available',
                'filesize': None,
                'note': 'best quality',
            })

        formats.append({
            'format_id': 'bestaudio/best',
            'ext': 'mp3',
            'resolution': 'Audio Only',
            'filesize': None,
            'note': 'best quality',
        })

        if len(formats) == 1:
            formats.insert(0, {
                'format_id': 'bestvideo+bestaudio/best',
                'ext': 'mp4',
                'resolution': 'Best Available',
                'filesize': None,
                'note': 'best quality',
            })

        return formats

    @classmethod
    def _video_format(cls, format_id: Optional[str]) -> str:
        best = f"bestvideo{cls.NO_PREMIUM}+bestaudio/best{cls.NO_PREMIUM}/bestvideo+bestaudio/best"
        if not format_id or format_id in ('best', 'bestvideo+bestaudio/best'):
            return best
        selected = format_id
        if selected.startswith('bestvideo'):
            selected = 'bestvideo' + cls.NO_PREMIUM + selected[len('bestvideo'):]
        return f"{selected}+bestaudio/{selected}/{best}"

    @classmethod
    def _ensure_named(cls, path: str, info: Dict[str, Any]) -> str:
        if not path or not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(os.path.basename(path))
        if cls.INVISIBLE_CHARS.sub('', stem):
            return path
        new_path = os.path.join(os.path.dirname(path), f"{info.get('id') or 'video'}{ext}")
        os.replace(path, new_path)
        return new_path

    def download_video(self, url: str, format_id: str = None, progress_hook=None) -> str:
        platform = self._detect_platform(url)
        if platform == 'spotify':
            return self._download_spotify(url, False)

        ydl_opts = self._get_base_opts()
        ydl_opts['outtmpl'] = os.path.join(self.download_path, '%(title)s.%(ext)s')
        ydl_opts['noplaylist'] = True

        if progress_hook:
            ydl_opts['progress_hooks'] = [progress_hook]

        is_audio = format_id == 'bestaudio/best'

        if is_audio:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['format'] = self._video_format(format_id)

        if not is_audio:
            ydl_opts['merge_output_format'] = 'mp4'

        def _download(ydl, url):
            info = ydl.extract_info(url, download=True)
            if 'requested_downloads' in info:
                return self._ensure_named(info['requested_downloads'][0]['filepath'], info)
            filename = ydl.prepare_filename(info)
            if is_audio:
                filename = os.path.splitext(filename)[0] + '.mp3'
            return self._ensure_named(filename, info)

        return self._execute_with_retry(_download, url, ydl_opts)

    def download_playlist(self, url: str, format_id: str = None, progress_hook=None) -> List[str]:
        platform = self._detect_platform(url)
        if platform == 'spotify':
            return self._download_spotify(url, True)

        import uuid
        playlist_id = uuid.uuid4().hex[:8]
        playlist_folder = os.path.join(self.download_path, f"playlist_{playlist_id}")
        os.makedirs(playlist_folder, exist_ok=True)

        ydl_opts = self._get_base_opts()
        ydl_opts['outtmpl'] = os.path.join(playlist_folder, '%(title)s.%(ext)s')
        ydl_opts['yes_playlist'] = True
        ydl_opts['ignoreerrors'] = True

        if progress_hook:
            ydl_opts['progress_hooks'] = [progress_hook]

        is_audio = format_id == 'bestaudio/best'

        if is_audio:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['format'] = self._video_format(format_id)

        if not is_audio:
            ydl_opts['merge_output_format'] = 'mp4'

        def _download(ydl, url):
            ydl.extract_info(url, download=True)
            return None

        self._execute_with_retry(_download, url, ydl_opts)

        final_files = []
        for f in os.listdir(playlist_folder):
            full_path = os.path.join(playlist_folder, f)
            if os.path.isfile(full_path) and not f.endswith(('.part', '.ytdl', '.temp')):
                if os.path.getsize(full_path) > 0:
                    final_files.append(full_path)

        return final_files

    def _download_spotify(self, url: str, is_playlist: bool):
        import sys
        import subprocess
        import tempfile
        import shutil

        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [sys.executable, '-m', 'spotdl', url, '--output', '{title} - {artist}.{ext}', '--format', 'mp3']
            process = subprocess.run(cmd, capture_output=True, text=True, cwd=tmpdir)
            
            if process.returncode != 0:
                logger.error(f"SpotDL failed: {process.stderr}")
                raise DownloadError(f"Spotify download failed. Ensure URL is correct. {process.stderr[:100]}", category='unknown')
                
            downloaded_files = [f for f in os.listdir(tmpdir) if os.path.isfile(os.path.join(tmpdir, f))]
            if not downloaded_files:
                raise DownloadError("No files downloaded from Spotify.", category='not_found')
                
            if is_playlist:
                import uuid
                playlist_id = uuid.uuid4().hex[:8]
                playlist_folder = os.path.join(self.download_path, f"playlist_{playlist_id}")
                os.makedirs(playlist_folder, exist_ok=True)
                final_files = []
                for f in downloaded_files:
                    src = os.path.join(tmpdir, f)
                    dst = os.path.join(playlist_folder, f)
                    shutil.move(src, dst)
                    final_files.append(dst)
                return final_files
            else:
                src_file = os.path.join(tmpdir, downloaded_files[0])
                dst_file = os.path.join(self.download_path, downloaded_files[0])
                if os.path.exists(dst_file):
                    try:
                        os.remove(dst_file)
                    except:
                        pass
                shutil.move(src_file, dst_file)
                return dst_file
