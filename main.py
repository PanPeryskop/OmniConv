import time

import customtkinter
import os
import customtkinter as tk
import subprocess
import ctypes
import ocrmypdf
import re
import shutil

from pydub import AudioSegment
from PIL import Image
from customtkinter import filedialog
from pathlib import Path
from pdf2docx import Converter as pdf2docx
import threading

from moviepy import VideoFileClip
from moviepy import AudioFileClip
from colorama import Fore
from langdetect import DetectorFactory, LangDetectException, detect_langs
from pdfminer.high_level import extract_text
from ocrmypdf.exceptions import EncryptedPdfError

DetectorFactory.seed = 0

LANGDETECT_TO_TESSERACT = {
    "en": "eng",
    "pl": "pol",
    "de": "deu",
    "fr": "fra",
    "es": "spa",
    "pt": "por",
    "it": "ita",
    "nl": "nld",
    "sv": "swe",
    "no": "nor",
    "da": "dan",
    "fi": "fin",
    "cs": "ces",
    "sk": "slk",
    "sl": "slv",
    "hu": "hun",
    "ro": "ron",
    "bg": "bul",
    "uk": "ukr",
    "ru": "rus",
    "hr": "hrv",
    "sr": "srp",
    "lt": "lit",
    "lv": "lav",
    "et": "est",
    "tr": "tur",
    "el": "ell",
    "ja": "jpn",
    "ko": "kor",
    "zh-cn": "chi_sim",
    "zh-tw": "chi_tra",
}


def compute_ocr_jobs():
    cpu_count = os.cpu_count() or 2
    if cpu_count <= 2:
        return 1
    return min(4, max(1, cpu_count // 2))


def detect_pdf_language(infile, fallback="eng", max_langs=2):
    try:
        first_page_text = extract_text(infile, page_numbers=[0]) or ""
    except Exception as exc:
        print(Fore.YELLOW + f"[OCR] Unable to read PDF for language detection: {exc}")
        return fallback

    cleaned_text = re.sub(r"\s+", " ", first_page_text).strip()

    if len(cleaned_text) < 40:
        return fallback

    try:
        lang_candidates = detect_langs(cleaned_text)
    except LangDetectException:
        return fallback

    selected_codes = []
    for candidate in lang_candidates:
        if candidate.prob < 0.35:
            continue
        tess_code = LANGDETECT_TO_TESSERACT.get(candidate.lang)
        if tess_code and tess_code not in selected_codes:
            selected_codes.append(tess_code)
        if len(selected_codes) >= max_langs:
            break

    if not selected_codes:
        return fallback

    detected = "+".join(selected_codes)
    print(Fore.CYAN + f"[OCR] Detected language(s): {detected}")
    return detected


def safe_destroy(widget):
    try:
        if widget is None:
            return
        exists = getattr(widget, "winfo_exists", lambda: True)()
        if exists:
            widget.destroy()
    except Exception:
        pass


def re_start(new_frame):
    safe_destroy(new_frame)
    show_toast("Conversion has been completed ", duration=2000, color="Green", mode=1)
    app.after(2000, lambda: restart_after_toast())


def show_toast(message, duration, color, mode):
    toast_label = tk.CTkLabel(master=frame, text=message, font=("Roboto", 20), text_color=color)
    if mode == 1:
        y = (frame.winfo_height() - toast_label.winfo_reqheight()) // 2
        toast_label.pack(side="top", fill="x", pady=y)
    else:
        toast_label.pack(side="top", fill="x")
    app.after(duration, lambda: safe_destroy(toast_label))


def get_password():
    password_dialog = customtkinter.CTkInputDialog(text="Enter the password for the PDF file", title="Decript")
    password = password_dialog.get_input()
    return password


def restart_after_toast():
    s_label.pack(pady=12, padx=10)
    entry.delete(0, tk.END)
    entry.pack(pady=12, padx=10)
    browse_button.pack(pady=12, padx=10)


def get_file_ext(infile):
    dot_index = infile.rfind('.')
    return infile[dot_index + 1:].lower() if dot_index != -1 else ''


def find_file():
    f_patch = filedialog.askopenfilename()
    entry.delete(0, tk.END)
    entry.insert(0, f_patch)


def get_file_name(infile):
    x = os.path.basename(infile).split(".")
    return x[0]


def show_format_buttons():
    supported_formats = slc_f_format(os.path.basename(entry.get()))
    if not supported_formats:
        show_toast("File format not supported", duration=2000, color="red", mode=0)
        entry.delete(0, tk.END)

    else:
        browse_button.pack_forget()
        get_before_destroy = entry.get()
        entry.pack_forget()
        s_label.pack_forget()
        new_frame = tk.CTkFrame(master=frame)
        new_frame.pack(fill="both", expand=True)

        select_label = tk.CTkLabel(master=new_frame, text="Choose Format", font=("Roboto", 24),
                                   width=frame.winfo_reqwidth())
        select_label.pack(pady=12, padx=10)
        for f_format in supported_formats:
            format_button = tk.CTkButton(master=new_frame, text=f_format,
                                         command=lambda f=f_format: conv_file(get_before_destroy, f, new_frame))

            format_button.pack(pady=12, padx=10)


def conv_file(infile, f_format, new_frame):
    conversion_thread = threading.Thread(target=go_to_conv_file, args=(infile, f_format, new_frame))
    conversion_thread.start()


def check_if_exsists(output_path_pre, output_path, f_format):
    if f_format == "OcrPdf":
        f_format = "pdf"
    if os.path.exists(output_path):
        i = 1
        while os.path.exists(output_path):
            output_path = output_path_pre + "_" + str(i) + '.' + f_format
            i += 1
    return output_path


def go_to_conv_file(infile, f_format, new_frame):
    toast_label = tk.CTkLabel(master=new_frame, text="Conversion is in progress...", font=("Roboto", 20),
                              text_color="yellow")
    toast_label.place(x=0, y=0, relwidth=1, relheight=1)
    f_ext = get_file_ext(infile)
    outfile = get_file_name(infile)

    desktop_path = os.path.join(Path.home(), "Desktop")
    output_path_pre = os.path.join(desktop_path, outfile)
    output_path = output_path_pre + '.' + f_format

    output_path = check_if_exsists(output_path_pre, output_path, f_format)

    if is_audio(f_ext):
        audio = AudioSegment.from_file(infile, format=f_ext)
        audio.export(output_path, format=f_format)

    elif is_graph(f_ext):
        image = Image.open(infile)
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        image.save(output_path)

    elif is_pdf(f_ext):
        if f_format == "docx":
            pdf_to_docx(infile, output_path)
        elif f_format == "OcrPdf":
            ocr_pdf(infile, output_path_pre, f_format)
        # else:
        #     ocr_pdf_and_docx(infile, output_path_pre)

    else:
        if is_audio(f_format):
            audio = AudioFileClip(infile)
            audio.write_audiofile(output_path)
        else:
            video = VideoFileClip(infile)
            video.write_videofile(output_path)

    safe_destroy(toast_label)
    re_start(new_frame)


def ocr_pdf(infile, output_path_pre, f_format, fallback_lang="eng"):
    output_path = output_path_pre + '.pdf'
    output_path = check_if_exsists(output_path_pre, output_path, f_format)

    detected_lang = detect_pdf_language(infile, fallback=fallback_lang)
    jobs = compute_ocr_jobs()

    optimize_level = 2 if shutil.which("pngquant") else 0
    if optimize_level == 0:
        print(Fore.YELLOW + "[OCR] pngquant not found — image optimization disabled (optimize=0).")

    base_kwargs = {
        "input_file": infile,
        "output_file": output_path,
        "deskew": True,
        "optimize": optimize_level,
        "language": detected_lang,
        "jobs": jobs,
        "rotate_pages": True,
        "force_ocr": False,
    }

    def run_ocr(kwargs):
        try:
            ocrmypdf.ocr(**kwargs)
            return True, None
        except Exception as err:
            return False, err

    success, error = run_ocr(base_kwargs)
    if success:
        print(Fore.GREEN + f"[OCR] Conversion completed using language '{base_kwargs['language']}'")
        return

    err_str = str(error).lower() if error else ""
    try:
        if isinstance(error, EncryptedPdfError):
            print(Fore.YELLOW + "[OCR] PDF is password protected. Requesting password from user...")
            password = get_password()
            if not password:
                show_toast("OCR aborted – password not provided.", duration=3000, color="red", mode=0)
                return
            protected_kwargs = dict(base_kwargs)
            protected_kwargs["userpw"] = password
            success, protected_error = run_ocr(protected_kwargs)
            if success:
                print(Fore.GREEN + "[OCR] Conversion completed with provided password.")
                return
            show_toast("OCR failed – incorrect password or unsupported encryption.", duration=3000, color="red", mode=0)
            print(Fore.RED + f"[OCR] {protected_error}")
            return
    except Exception:
        pass
    if "already has text" in err_str or "page already has text" in err_str:
        print(Fore.YELLOW + "[OCR] Page already has text — retrying with force_ocr=True (will replace existing text).")
        retry_kwargs = dict(base_kwargs)
        retry_kwargs["force_ocr"] = True
        success, retry_error = run_ocr(retry_kwargs)
        if success:
            print(Fore.GREEN + "[OCR] Conversion completed with force_ocr=True.")
            return
        error = retry_error or error

    if "image file is truncated" in err_str or "truncated" in err_str:
        print(Fore.YELLOW + "[OCR] Image truncated error — retrying OCR with optimize=0.")
        retry_kwargs = dict(base_kwargs)
        retry_kwargs["optimize"] = 0
        success, retry_error = run_ocr(retry_kwargs)
        if success:
            print(Fore.GREEN + "[OCR] Conversion completed (retry without optimize).")
            return
        error = retry_error or error

    print(Fore.RED + f"[OCR] Initial OCR attempt failed: {error}")

    if base_kwargs["language"] != fallback_lang:
        print(Fore.YELLOW + f"[OCR] Falling back to default language '{fallback_lang}'.")
        fallback_kwargs = dict(base_kwargs)
        fallback_kwargs["language"] = fallback_lang
        success, fallback_error = run_ocr(fallback_kwargs)
        if success:
            print(Fore.GREEN + f"[OCR] Conversion completed using fallback language '{fallback_lang}'.")
            return
        error = fallback_error or error

    show_toast("OCR failed – check console for details.", duration=3000, color="red", mode=0)
    print(Fore.RED + f"[OCR] Final failure: {error}")


# def ocr_pdf_and_docx(infile, output_path_pre):
#     output_path = output_path_pre + '.pdf'
#     try:
#         ocrmypdf.ocr(input_file=infile, output_file=output_path,  deskew=True)
#         output_docx_path = output_path_pre + ".docx"
#         cv = pdf2docx(output_path)
#         cv.convert(output_docx_path, start=0, end=None)
#         cv.close()
#     except Exception as e:
#         try:
#             password = get_password()
#             if password:
#                 ocrmypdf.ocr(input_file=infile, output_file=output_path, userpw=password)
#                 cv = pdf2docx(pdf_file=infile, password=password)
#                 cv.convert(pdf_file=infile, docx_file=output_path, start=0, end=None)
#                 cv.close()
#         except Exception as e:
#             show_toast("Incorrect password or another error occurred...", duration=2000, color="red", mode=0)


def pdf_to_docx(infile, output_path):
    try:
        pdf_file = infile
        cv = pdf2docx(pdf_file)
        docx_file = output_path
        cv.convert(docx_file, start=0, end=None)
        cv.close()
    except Exception as e:
        try:
            password = get_password()
            if password:
                cv = pdf2docx(pdf_file=infile, password=password)
                cv.convert(pdf_file=infile, docx_file=output_path, start=0, end=None)
                cv.close()
        except Exception as e:
            show_toast("Incorrect password or another error occurred...", duration=2000, color="red", mode=0)


# file type finder


def is_audio(f_ext):
    supported_files = ["mp3", "wav", "ogg", "flac", "m4a", "aac", "ac3", "alac", "dts", "dtshd", "eac3", "tta", "wv"]
    if f_ext in supported_files:
        # print(f"Audio file detected: {f_ext}")
        return 1
    return 0


def is_graph(f_ext):
    supported_files = ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp"]
    if f_ext in supported_files:
        # print(f"Image file detected: {f_ext}")
        return 1
    return 0


def is_vid(f_ext):
    supported_files = ["mp4", "avi", "mkv", "mov", "wmv", "flv", "webm"]
    if f_ext in supported_files:
        # print(f"Video file detected: {f_ext}")
        return 1
    return 0


def is_pdf(f_ext):
    supported_files = ["pdf"]
    if f_ext in supported_files:
        return 1
    return 0


# end of file type finder segment


def slc_f_format(infile):
    f_ext = get_file_ext(infile)
    supported_formats = []

    if is_audio(f_ext):
        supported_formats.extend(["mp3", "wav", "ogg", "flac"])
    elif is_graph(f_ext):
        supported_formats.extend(["png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp", "ico"])
    elif is_vid(f_ext):
        supported_formats.extend(["mp4", "mp3", "wav", "webm", ])
    elif is_pdf(f_ext):
        supported_formats.extend(["docx", "OcrPdf"])  # "OcrPdfAndDocx"
    else:
        supported_formats = 0

    if supported_formats:
        if f_ext.lower() in supported_formats:
            supported_formats.remove(f_ext.lower())

    return supported_formats


def check_ffmpeg():
    try:
        subprocess.call('ffmpeg', creationflags=subprocess.CREATE_NEW_CONSOLE)
        print(Fore.GREEN + "Ffmpeg is installed\n")
    except FileNotFoundError:
        print(Fore.RED + "Ffmpeg is not installed\n")
        time.sleep(0.3)
        print(Fore.YELLOW + "Checking if program is running as administrator...\n")
        if not is_admin():
            time.sleep(0.3)
            print(Fore.RED + "This script must be run as administrator. Please restart the script with administrative "
                             "privileges.")
            time.sleep(10)
            exit()
        time.sleep(0.1)
        print(Fore.RED + "ffmpeg is not installed\n")
        time.sleep(0.1)
        print(Fore.YELLOW + "Searching for Chocolatey...\n")
        is_choco = 0
        check_chocolatey(is_choco)
        install_ffmpeg(is_choco)
        

def check_pngquant():
    try:
        subprocess.call('pngquant', creationflags=subprocess.CREATE_NEW_CONSOLE)
        print(Fore.GREEN + "pngquant is installed\n")
    except FileNotFoundError:
        print(Fore.RED + "pngquant is not installed\n")
        print(Fore.YELLOW + "pngquant is required for image optimization in OCR (--optimize).")
        print(Fore.YELLOW + "Checking if program is running as administrator...\n")
        if not is_admin():
            print(Fore.RED + "This script must be run as administrator. Please restart the script with administrative privileges.")
            time.sleep(10)
            exit()
        print(Fore.YELLOW + "Searching for Chocolatey...\n")
        is_choco = 0
        check_chocolatey(is_choco)
        install_pngquant(is_choco)



def check_chocolatey(is_choco):
    time.sleep(0.1)
    try:
        subprocess.call('choco', creationflags=subprocess.CREATE_NEW_CONSOLE)
        print(Fore.GREEN + "Chocolatey is installed\n")
    except FileNotFoundError:
        print(Fore.RED + "Chocolatey is not installed\n")
        is_choco = 1
        install_chocolatey()


def check_tesseract():
    try:
        subprocess.call('tesseract', creationflags=subprocess.CREATE_NEW_CONSOLE)
        print(Fore.GREEN + "Tesseract is installed\n")
    except FileNotFoundError:
        print(Fore.RED + "Tesseract is not installed\n")
        print(Fore.YELLOW + "Checking if program is running as administrator...\n")
        if not is_admin():
            print(Fore.RED + "This script must be run as administrator. Please restart the script with administrative "
                             "privileges.")
            time.sleep(10)
            exit()
        print(Fore.YELLOW + "Searching for Chocolatey...\n")
        is_choco = 0
        check_chocolatey(is_choco)
        install_tesseract(is_choco)


def install_tesseract(is_choco):
    print(Fore.BLUE + "Installing Tesseract...\n")
    command = 'choco install tesseract -y'
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print(Fore.RED + f"Error occurred while installing Tesseract: {stderr.decode()}")
        else:
            print(Fore.GREEN + "Tesseract installed successfully.\n")
        if is_choco:
            uninstall_chocolatey()
    except Exception as e:
        print(Fore.RED + f"An error occurred while trying to run the command: {e}")
        if is_choco:
            uninstall_chocolatey()


def install_chocolatey():
    print(Fore.BLUE + "Installing Chocolatey...")
    command = ('powershell -Command "Set-ExecutionPolicy Bypass -Scope Process -Force; ['
               'System.Net.ServicePointManager]::SecurityProtocol = ['
               'System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object '
               'System.Net.WebClient).DownloadString(\'https://chocolatey.org/install.ps1\'))"')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    process.wait()
    print(Fore.GREEN + "Chocolatey installed successfully.")


def install_ffmpeg(is_choco):
    print(Fore.BLUE + "Installing ffmpeg...")
    command = 'choco install ffmpeg -y'
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print(Fore.RED + f"Error occurred while installing ffmpeg: {stderr.decode()}")
        else:
            print(Fore.GREEN + "ffmpeg installed successfully.")
        if is_choco:
            uninstall_chocolatey()
    except Exception as e:
        print(Fore.RED + f"An error occurred while trying to run the command: {e}")
        
        
def install_pngquant(is_choco):
    print(Fore.BLUE + "Installing pngquant...\n")
    command = 'choco install pngquant -y'
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print(Fore.RED + f"Error occurred while installing pngquant: {stderr.decode()}")
        else:
            print(Fore.GREEN + "pngquant installed successfully.\n")
        if is_choco:
            uninstall_chocolatey()
    except Exception as e:
        print(Fore.RED + f"An error occurred while trying to run the command: {e}")
        if is_choco:
            uninstall_chocolatey()


def is_admin():
    return ctypes.windll.shell32.IsUserAnAdmin()


def uninstall_chocolatey():
    # print(Fore.BLUE + "\nUninstalling Chocolatey...\n")
    # command = 'powershell -Command "Remove-Item -Recurse -Force C:\\ProgramData\\chocolatey"'
    # process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    # process.wait()

    # print(Fore.BLUE + "\nRemoving Chocolatey from PATH...\n")
    # command = ('powershell -Command "[Environment]::SetEnvironmentVariable(\'PATH\', '
    #            '(([Environment]::GetEnvironmentVariable(\'PATH\', \'Machine\') -split \';\' | Where-Object { $_ '
    #            '-notmatch \'chocolatey\' }) -join \';\'), \'Machine\')"')
    # process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    # process.wait()
    pass # :) choco is nice why to uninstall it


def check_ghostscript():
    try:
        process = subprocess.Popen('gswin64c', creationflags=subprocess.CREATE_NEW_CONSOLE)
        process.terminate()  # Zakończ proces

        print(Fore.GREEN + "Ghostscript is installed\n")
    except FileNotFoundError:
        print(Fore.RED + "Ghostscript is not installed\n")
        print(Fore.YELLOW + "Checking if program is running as administrator...\n")
        if not is_admin():
            print(Fore.RED + "This script must be run as administrator. Please restart the script with administrative "
                             "privileges.")
            time.sleep(10)
            exit()
        print(Fore.YELLOW + "Searching for Chocolatey...\n")
        is_choco = 0
        check_chocolatey(is_choco)
        install_ghostscript(is_choco)


def install_ghostscript(is_choco):
    print(Fore.BLUE + "Installing Ghostscript...\n")
    command = 'choco install ghostscript -y'
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print(Fore.RED + f"Error occurred while installing Ghostscript: {stderr.decode()}\n")
        else:
            print(Fore.GREEN + "Ghostscript installed successfully.\n")
        if is_choco:
            uninstall_chocolatey()
    except Exception as e:
        print(Fore.RED + f"An error occurred while trying to run the command: {e}\n")
        if is_choco:
            uninstall_chocolatey()


# code segment


check_ffmpeg()
check_tesseract()
check_ghostscript()
check_pngquant()



print(Fore.CYAN + "Starting the app...\n")
print(Fore.RESET)
customtkinter.set_appearance_mode("Dark")
customtkinter.set_default_color_theme("dark-blue")

# is_nvidia = False
# user_input = input("Do you have nvidia gpu? (y/n): ")
# if user_input.lower() == "y":
#     is_nvidia = True
# elif user_input.lower() == "n":
#     is_nvidia = False
# else:
#     print("Invalid input. Starting on CPU mode...")
#     is_nvidia = False

app = tk.CTk()
app.title("OmniConv")
app.geometry("420x600")


frame = tk.CTkFrame(master=app)
frame.pack(pady=20, padx=60, fill="both", expand=True)

s_label = tk.CTkLabel(master=frame, text="Select File", font=("Roboto", 24))
s_label.pack(pady=12, padx=10)

entry = tk.CTkEntry(master=frame)
entry.pack(pady=12, padx=10)

browse_button = tk.CTkButton(app, text="Browse", command=lambda: [find_file(), show_format_buttons()])
browse_button.pack(pady=12, padx=10)

app.mainloop()
