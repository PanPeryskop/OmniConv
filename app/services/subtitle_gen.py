import os
import gc
import re
import subprocess
import torch
import wave
from transformers import VoxtralForConditionalGeneration, AutoProcessor
import imageio_ffmpeg


class SubtitleGenService:
    _instance = None
    _model = None
    _processor = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_path = "mistralai/Voxtral-Mini-3B-2507"

    def _ensure_loaded(self):
        if SubtitleGenService._model is None:
            SubtitleGenService._processor = AutoProcessor.from_pretrained(self.model_path)
            SubtitleGenService._model = VoxtralForConditionalGeneration.from_pretrained(
                self.model_path,
                torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
                device_map=self.device
            )

    def unload(self):
        if SubtitleGenService._model:
            del SubtitleGenService._model
            del SubtitleGenService._processor
            SubtitleGenService._model = None
            SubtitleGenService._processor = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _extract_audio(self, input_path: str, output_wav: str):
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe, '-y',
            '-i', input_path,
            '-ar', '16000',
            '-ac', '1',
            '-c:a', 'pcm_s16le',
            output_wav
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _format_timestamp(self, seconds: float, fmt: str = 'srt') -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)

        if fmt == 'vtt':
            return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

    def _chat_generate(self, audio_path: str, prompt: str, max_tokens: int = 2048) -> str:
        self._ensure_loaded()

        conversation = [
            {
                "role": "user",
                "content": [
                    {"type": "audio", "path": audio_path},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        inputs = self._processor.apply_chat_template(conversation)
        inputs = inputs.to(
            self.device,
            dtype=torch.bfloat16 if self.device == "cuda" else torch.float32
        )

        generated_ids = self._model.generate(**inputs, max_new_tokens=max_tokens)
        result = self._processor.batch_decode(
            generated_ids[:, inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )[0]

        return result

    def generate_subtitle(self, input_path: str, output_format: str = 'srt', language: str = 'en') -> str:
        temp_wav = f"{input_path}_temp.wav"

        try:
            self._extract_audio(input_path, temp_wav)
            with wave.open(temp_wav, 'rb') as wf:
                pk = wf.getnframes()
                duration = pk / wf.getframerate()

            lang_name = {
                'en': 'English', 'pl': 'Polish', 'de': 'German',
                'fr': 'French', 'es': 'Spanish', 'it': 'Italian',
                'pt': 'Portuguese', 'nl': 'Dutch', 'ru': 'Russian',
                'ja': 'Japanese', 'zh': 'Chinese', 'ko': 'Korean',
            }.get(language, 'English')

            transcription = self._chat_generate(
                temp_wav,
                f"Transcribe this audio word for word in {lang_name}. Output ONLY the transcription text, nothing else.",
                max_tokens=2048
            )

            return self._create_subtitles(transcription, duration, output_format)

        finally:
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except:
                    pass

    def _create_subtitles(self, text: str, duration: float, fmt: str) -> str:
        sentences = re.split(r'(?<=[.!?]) +', text.strip())
        sentences = [s for s in sentences if s]

        total_chars = sum(len(s) for s in sentences)
        if total_chars == 0:
            return ""

        if fmt == 'txt':
            return text

        output = []
        if fmt == 'vtt':
            output.append("WEBVTT\n")

        current_time = 0.0

        for i, sentence in enumerate(sentences):
            char_count = len(sentence)
            segment_duration = (char_count / total_chars) * duration
            start_time = current_time
            end_time = min(current_time + segment_duration, duration)

            s_time = self._format_timestamp(start_time, fmt)
            e_time = self._format_timestamp(end_time, fmt)

            if fmt == 'vtt':
                output.append(f"\n{s_time} --> {e_time}\n{sentence}")
            else:
                output.append(f"{i+1}\n{s_time} --> {e_time}\n{sentence}\n")

            current_time = end_time

        return "\n".join(output)

    def describe_audio(self, input_path: str) -> str:
        temp_wav = f"{input_path}_desc_temp.wav"
        try:
            self._extract_audio(input_path, temp_wav)

            return self._chat_generate(
                temp_wav,
                "Describe this audio in detail. Include what is being said, the tone of voice, any background sounds, and the overall mood.",
                max_tokens=500
            )

        finally:
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except:
                    pass
