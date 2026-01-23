from typing import Dict, Any, List
import yt_dlp
import os

class VideoDownloaderService:
    def __init__(self, download_path: str):
        self.download_path = download_path
        os.makedirs(download_path, exist_ok=True)

    def get_video_info(self, url: str) -> Dict[str, Any]:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True, 
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            is_playlist = 'entries' in info
            
            result = {
                'title': info.get('title'),
                'uploader': info.get('uploader'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'is_playlist': is_playlist,
                'entries': []
            }
            
            if is_playlist:
                for entry in info.get('entries', []):
                    if entry:
                        result['entries'].append({
                            'id': entry.get('id'),
                            'title': entry.get('title'),
                            'duration': entry.get('duration')
                        })
            else:
                 result['formats'] = self._get_formats(url)

            return result

    def _get_formats(self, url: str) -> List[Dict[str, Any]]:
         ydl_opts = {'quiet': True, 'no_warnings': True}
         with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            seen_formats = set()

            for f in info.get('formats', []):
                # Filter for useful formats (video+audio or best audio/video)
                if f.get('ext') == 'mp4' and f.get('vcodec') != 'none':
                    resolution = f.get('resolution') or f"{f.get('width')}x{f.get('height')}"
                    fid = f.get('format_id')
                    
                    if resolution not in seen_formats:
                        formats.append({
                            'format_id': fid,
                            'ext': f.get('ext'),
                            'resolution': resolution,
                            'filesize': f.get('filesize'),
                            'note': f.get('format_note')
                        })
                        seen_formats.add(resolution)
            
            # Add audio only option
            formats.append({
                'format_id': 'bestaudio/best',
                'ext': 'mp3',
                'resolution': 'Audio Only',
                'note': 'best quality'
            })
            
            return formats


    def download_video(self, url: str, format_id: str = None, is_playlist: bool = False, progress_hook=None) -> str:
        # Locate FFmpeg relative to this file or app
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ffmpeg_path = os.path.join(base_dir, 'dist', 'OmniConv', 'ffmpeg', 'ffmpeg.exe')
        
        # If not in dist, try local bin or path
        if not os.path.exists(ffmpeg_path):
             ffmpeg_path = 'ffmpeg' # Fallback to PATH

        ydl_opts = {
            'outtmpl': os.path.join(self.download_path, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': os.path.dirname(ffmpeg_path) if 'ffmpeg.exe' in ffmpeg_path else None,
            # Force overwrite to avoid errors with existing files
            'overwrites': True,
        }
        
        if progress_hook:
            ydl_opts['progress_hooks'] = [progress_hook]

        if format_id == 'bestaudio/best':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        elif format_id:
             ydl_opts['format'] = f"{format_id}+bestaudio/best" if format_id != 'best' else 'bestvideo+bestaudio/best'
        else:
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
        
        if is_playlist:
            ydl_opts['yes_playlist'] = True
        else:
            ydl_opts['noplaylist'] = True

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Return absolute path of the downloaded file
            # For playlists this might return the last file or be complex, 
            # but for single video:
            if 'requested_downloads' in info:
                return info['requested_downloads'][0]['filepath']
            else:
                 # Fallback/estimate
                 filename = ydl.prepare_filename(info)
                 if format_id == 'bestaudio/best':
                     filename = os.path.splitext(filename)[0] + '.mp3'
                 return filename
