import gc
import torch
import scipy.io.wavfile
from qwen_tts import Qwen3TTSModel


class AudioDesignService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._model = None
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model_path = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
            self._initialized = True

    def _ensure_loaded(self):
        if self._model is None:
            try:
                import flash_attn
                attn_impl = "flash_attention_2"
            except ImportError:
                attn_impl = "sdpa" if torch.version.cuda else "eager"

            self._model = Qwen3TTSModel.from_pretrained(
                self.model_path,
                device_map=self.device,
                dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
                attn_implementation=attn_impl
            )

    def unload(self):
        if self._model:
            del self._model
            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def generate_voice_design(self, text: str, voice_description: str, output_path: str) -> str:
        self._ensure_loaded()

        wavs, sr = self._model.generate_voice_design(
            text=text,
            language="English",
            instruct=voice_description
        )

        scipy.io.wavfile.write(output_path, sr, wavs[0])
        return output_path
