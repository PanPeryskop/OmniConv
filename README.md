<h1 align="center">🔄 OmniConv</h1>

<p align="center">
  <strong>Universal AI-Powered File Converter & Compressor</strong><br>
  Convert audio, video, images, and documents with OCR support — all locally, no cloud needed.
</p>

<p align="center">
  <a href="#-features">Features</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-supported-formats">Formats</a> •
  <a href="#-tech-stack">Tech Stack</a> •
</p>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎵 **Audio Conversion** | Convert between MP3, WAV, FLAC, OGG, M4A, AAC, AIFF, WMA and more |
| 🎬 **Video Conversion** | MP4, AVI, MKV, MOV, WEBM conversions + GIF extraction |
| 📚 **E-book Support** | **NEW!** Convert PDF to EPUB and CBZ formats |
| 📺 **YouTube Downloader** | Direct browser download, playlist support, quality selection & realtime progress |
| 🖼️ **Image Conversion** | PNG, JPG, WEBP, GIF, BMP, TIFF, HEIC, ICO support |
| 📄 **Document Conversion** | PDF to DOCX with layout preservation |
| 🔍 **OCR** | RapidOCR (fast, local, default) or Qwen 3-VL via LM Studio; searchable PDF output with auto page orientation |
| 🧰 **PDF Tools** | Compress, organize pages (reorder/rotate/delete), split, merge, convert, password protect/unlock, watermark, page numbers, metadata, extract images |
| 📦 **Smart Compression** | Video, audio, images and PDF. PDF: lossless / balanced / strong / max / target size, hybrid Ghostscript + MuPDF engine |
| 📁 **Batch Processing** | Convert multiple files at once with drag & drop |
| ⚡ **Optimized Performance** | Smart caching for invalid files & multi-core processing support |
| ⚙️ **System Integration** | Auto-start capability & persistent user settings |
| 🌙 **Dark/Light Mode** | Beautiful UI with theme switching |
| 🔒 **100% Local** | All processing happens on your machine — no data leaves |



---

## 🚀 Quick Start

### Prerequisites

- Python
- FFmpeg (for audio/video processing)
- Ghostscript (optional, strongest PDF compression; without it PDFs are compressed with MuPDF only)

### Installation

```bash
# Clone the repository
git clone https://github.com/PanPeryskop/OmniConv
cd OmniConv

# Create .venv and install dependencies (https://docs.astral.sh/uv/)
uv sync

# Run the application
uv run run.py
```

On Windows you can also double-click `start.bat` (runs in the tray, no console window) and `autostart.bat` to launch OmniConv at login. yt-dlp updates itself on every start; pass `--no-update` or set `OMNICONV_NO_UPDATE=1` to disable it.

### 🌐 Open in Browser

```
http://localhost:5000
```

---

## 📋 Supported Formats

<details>
<summary><b>🎵 Audio Formats</b></summary>

| Input | Output |
|-------|--------|
| MP3, WAV, OGG, FLAC, M4A, AAC, AC3, ALAC, DTS, EAC3, TTA, WV, AIFF, APE, WMA, OPUS | MP3, WAV, OGG, FLAC, M4A, AIFF |

</details>

<details>
<summary><b>🎬 Video Formats</b></summary>

| Input | Output |
|-------|--------|
| MP4, AVI, MKV, MOV, WMV, FLV, WEBM, 3GP, MPEG, M4V, TS, MTS, VOB | MP4, WEBM, AVI, MKV, MOV, GIF |

> 💡 **Tip:** You can also extract audio from videos to MP3, WAV, AAC, or OGG!

</details>

<details>
<summary><b>🖼️ Image Formats</b></summary>

| Input | Output |
|-------|--------|
| JPG, JPEG, PNG, GIF, BMP, TIFF, WEBP, ICO, HEIC, HEIF | PNG, JPG, WEBP, GIF, BMP, TIFF, ICO, PDF |

</details>

<details>
<summary><b>📄 Document Formats</b></summary>

| Input | Output |
|-------|--------|
| PDF, DOCX, DOC, TXT, RTF, ODT, XLS, XLSX, MD | DOCX, PDF, TXT, EPUB, CBZ |

> 🔍 **OCR Engine Options:**
> - **Qwen 3-VL:** State-of-the-art multimodal AI (high accuracy, slower).
> - **RapidOCR:** Fast, local OCR (default). Works without any extra setup.
> - **AI correction:** Optional post-correction of OCR text with Ministral 3 8B in LM Studio.

</details>

---

## 🛠️ Tech Stack

| Technology | Purpose |
|------------|---------|
| **Flask** | Web framework |
| **RapidOCR** | Local OCR engine (ONNX Runtime) |
| **MoviePy** | Video processing |
| **Pydub** | Audio processing |
| **Pillow** | Image processing |
| **FFmpeg** | Media encoding/decoding |
| **python-docx** | Document handling |
| **EbookLib** | E-book generation |

---

### 🏠 Main Converter
Clean, intuitive interface for single file conversion with drag & drop support.

### 📦 Batch Conversion
Process multiple files at once — grouped by type with individual format selection.

### 🗜️ Smart Compression
Set your target file size and let the AI optimize quality automatically.

### 📜 Conversion History
Track all your conversions with timestamps and easy re-download.

---

## 📁 Project Structure

```
OmniConv/
├── app/
│   ├── routes/
│   │   ├── api.py          # REST API endpoints
│   │   └── views.py        # Page routes
│   ├── services/
│   │   ├── audio.py        # Audio conversion
│   │   ├── video.py        # Video conversion
│   │   ├── image.py        # Image conversion
│   │   ├── document.py     # Document conversion
│   │   ├── compressor.py   # File compression
│   │   └── ocr.py          # OCR service
│   ├── static/
│   │   ├── css/styles.css  # Styling
│   │   └── js/app.js       # Frontend logic
│   └── templates/          # HTML templates
├── uploads/                # Temporary uploads
├── outputs/                # Converted files
├── pyproject.toml          # Dependencies (uv)
├── uv.lock
└── run.py                  # Entry point
```

---

## ⚙️ Configuration

Environment variables (optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_DEBUG` | `False` | Enable debug mode |
| `MAX_CONTENT_LENGTH` | `500MB` | Maximum upload size |
| `UPLOAD_FOLDER` | `./uploads` | Upload directory |
| `OUTPUT_FOLDER` | `./outputs` | Output directory |
