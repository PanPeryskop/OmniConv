# OmniConv Flask Application

A modern universal file conversion web application with PaddleOCR integration.

## Quick Start

```bash
cd d:\projekty\OmniConv
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Then open http://localhost:5000 in your browser.

## Features

- **Audio Conversion**: MP3, WAV, OGG, FLAC, M4A, AAC, AIFF, WMA and more
- **Video Conversion**: MP4, AVI, MKV, MOV, WEBM, GIF extraction
- **Image Conversion**: PNG, JPG, WEBP, GIF, BMP, TIFF, HEIC, ICO
- **Document Conversion**: PDF to DOCX, PDF OCR with searchable text
- **OCR**: PaddleOCR with 35+ language support

## Tech Stack

- **Backend**: Flask 3.0+
- **OCR**: PaddleOCR (faster than Tesseract, works offline)
- **Media**: FFmpeg, MoviePy, Pydub, Pillow
