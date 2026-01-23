import os
import zipfile
import tarfile
import shutil
from pathlib import Path
from typing import List, Tuple

class ArchiveService:
    def __init__(self, upload_folder: Path):
        self.upload_folder = upload_folder

    def is_archive(self, filename: str) -> bool:
        return filename.lower().endswith(('.zip', '.tar', '.tar.gz', '.tgz', '.rar', '.7z'))

    def extract_archive(self, archive_path: str, extract_to: str) -> List[str]:
        extracted_files = []
        
        try:
            if archive_path.endswith('.zip'):
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_to)
                    extracted_files = [os.path.join(extract_to, f) for f in zip_ref.namelist()]
            
            elif archive_path.endswith(('.tar', '.tar.gz', '.tgz')):
                with tarfile.open(archive_path, 'r:*') as tar_ref:
                    tar_ref.extractall(extract_to)
                    extracted_files = [os.path.join(extract_to, f) for f in tar_ref.getnames()]
            
            # Note: rar and 7z require external libraries/tools not standard in python
            # supporting only zip/tar for "clean code" standard lib solution
            
        except Exception as e:
            raise Exception(f"Failed to extract archive: {str(e)}")
            
        # Filter for files only
        files_only = []
        for f in extracted_files:
            if os.path.isfile(f) and not os.path.basename(f).startswith('.'):
                files_only.append(f)
                
        return files_only

archive_service = ArchiveService(Path('uploads')) # path will be overriden
