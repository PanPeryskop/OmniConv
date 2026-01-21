from abc import ABC, abstractmethod
from typing import Callable, Optional, Dict, Any


class BaseConverter(ABC):
    def __init__(self, progress_callback: Optional[Callable[[int], None]] = None):
        self._progress_callback = progress_callback
        self._cancelled = False
    
    def report_progress(self, percentage: int) -> None:
        if self._progress_callback:
            self._progress_callback(min(100, max(0, percentage)))
    
    def cancel(self) -> None:
        self._cancelled = True
    
    @property
    def is_cancelled(self) -> bool:
        return self._cancelled
    
    @abstractmethod
    def convert(
        self, 
        input_path: str, 
        output_path: str, 
        output_format: str,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        pass
    
    @staticmethod
    @abstractmethod
    def get_supported_input_formats() -> set:
        pass
    
    @staticmethod
    @abstractmethod
    def get_supported_output_formats() -> set:
        pass
    
    @classmethod
    def can_convert(cls, input_format: str, output_format: str) -> bool:
        return (
            input_format.lower() in cls.get_supported_input_formats() and
            output_format.lower() in cls.get_supported_output_formats()
        )
