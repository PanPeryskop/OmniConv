# OmniConv

OmniConv is a universal file conversion tool developed in Python. It leverages various libraries to provide a wide range of conversion options for different file types.

## Features

- **Audio Conversion**: OmniConv supports conversion between various audio formats including MP3, WAV, OGG, FLAC, AAC, and more.
- **Image Conversion**: OmniConv can convert between different image formats such as PNG, JPG, JPEG, GIF, BMP, TIFF, WEBP, and ICO.
- **Video Conversion**: OmniConv allows conversion between popular video formats like MP4, AVI, MKV, MOV, WMV, FLV, and WEBM. It also supports extracting audio from video files.
- **PDF to DOCX Conversion**: OmniConv can convert PDF files to DOCX format. It also supports password-protected PDF files. (Also PDF to DOCX with OCR)
- **PDF OCR**: OmniConv can extract text from images and PDF files using OCR (Optical Character Recognition).

## Libraries Used

- **customtkinter**: Used for creating the GUI of the application.
- **pydub**: Used for handling audio file conversions.
- **PIL (Pillow)**: Used for handling image file conversions.
- **pdf2docx**: Used for converting PDF files to DOCX format.
- **moviepy**: Used for handling video file conversions and extracting audio from video files.
- **ocrmypdf**: Used for extracting text from images and PDF files using OCR.

## How to Install Release

1.  Click on newest release in this repository. Current is:https://github.com/PanPeryskop/OmniConv/releases/tag/v1.2 . 
2.  Click on **Omniconv.exe**. Download will start automatically
3.  You don't need any additional files, so you can start using it instantly after downloading is complete
4.  **OmniConv** will save converted files on your *Desktop*. If you have a file with the same name as the converted file, OmniConv will not overwrite it, it will just rename the converted file.
5.  Enjoy!

**WARNING** * if ffmpeg, ghostscript or tesseract are not installed, OmniConv will ask you to run it as administrator to install it.

## How to Use

1. Run the `main.py` script or **OmniConv.exe** (if you installed release)  to start the application.
2. Click on the "Browse" button to select the file you want to convert.
3. Choose the desired output format from the options that appear.
4. The application will start the conversion process and notify you when it's done.

Output file will be saved on Desktop.

## Future Improvements

Future versions of OmniConv aim to support more file formats and provide more conversion options.

## Important

If you encounter any errors, please report them in the ***Issues*** section of this repository.