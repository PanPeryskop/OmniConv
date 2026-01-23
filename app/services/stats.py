import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

class StatsService:
    def __init__(self, storage_path: str = 'stats.json'):
        self.storage_path = storage_path
        self._ensure_storage()
    
    def _ensure_storage(self):
        if not os.path.exists(self.storage_path):
            self._save_stats({
                'total_conversions': 0,
                'total_size_saved_mb': 0,
                'formats': {},
                'recent_activity': []
            })
    
    def _load_stats(self) -> Dict[str, Any]:
        try:
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except Exception:
            return {
                'total_conversions': 0,
                'total_size_saved_mb': 0,
                'formats': {},
                'recent_activity': []
            }
    
    def _save_stats(self, stats: Dict[str, Any]):
        with open(self.storage_path, 'w') as f:
            json.dump(stats, f, indent=4)
    
    def record_conversion(self, input_format: str, output_format: str, input_size: int, output_size: int):
        stats = self._load_stats()
        
        stats['total_conversions'] += 1
        
        saved_bytes = max(0, input_size - output_size)
        saved_mb = saved_bytes / (1024 * 1024)
        stats['total_size_saved_mb'] += saved_mb
        
        fmt_key = f"{input_format}->{output_format}"
        stats['formats'][fmt_key] = stats['formats'].get(fmt_key, 0) + 1
        
        activity = {
            'timestamp': datetime.now().isoformat(),
            'type': 'conversion',
            'details': fmt_key
        }
        stats['recent_activity'].insert(0, activity)
        stats['recent_activity'] = stats['recent_activity'][:50]  # Keep last 50
        
        self._save_stats(stats)
    
    def get_stats(self) -> Dict[str, Any]:
        return self._load_stats()

# Global instance
stats_service = StatsService(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'stats.json'))
