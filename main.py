
import time

import customtkinter
import os
import customtkinter as tk
import subprocess
import ctypes
import ocrmypdf


from pydub import AudioSegment
from PIL import Image
from customtkinter import filedialog
from pathlib import Path
from pdf2docx import Converter as pdf2docx
import threading
from moviepy.editor import VideoFileClip
from moviepy.editor import AudioFileClip
from colorama import Fore

# def segment


def re_start(new_frame):
    new_frame.destroy()

    show_toast("Conversion has been completed ", duration=2000, color="Green", mode=1)
    app.after(2000, lambda: restart_after_toast()) #new_frame


def show_toast(message, duration, color, mode):
    toast_label = tk.CTkLabel(master=frame, text=message, font=("Roboto", 20), text_color=color)
    if mode == 1:
        y = (frame.winfo_height() - toast_label.winfo_reqheight()) // 2
        toast_label.pack(side="top", fill="x", pady=y)
    else:
        toast_label.pack(side="top", fill="x")
    app.after(duration, lambda: toast_label.destroy())


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


def go_to_conv_file(infile, f_format, new_frame):
    toast_label = tk.CTkLabel(master=new_frame, text="Conversion is in progress...", font=("Roboto", 20),
                              text_color="yellow")
    toast_label.place(x=0, y=0, relwidth=1, relheight=1)
    f_ext = get_file_ext(infile)
    outfile = get_file_name(infile)

    desktop_path = os.path.join(Path.home(), "Desktop")
    output_path_pre = os.path.join(desktop_path, outfile)
    output_path = output_path_pre + '.' + f_format

    if os.path.exists(output_path):
        i = 1
        while os.path.exists(output_path):
            output_path = output_path_pre + "_" + str(i) + '.' + f_format
            i += 1

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
            ocr_pdf(infile, output_path_pre)
        # else:
        #     ocr_pdf_and_docx(infile, output_path_pre)

    else:
        if is_audio(f_format):
            audio = AudioFileClip(infile)
            audio.write_audiofile(output_path)
        else:
            video = VideoFileClip(infile)
            video.write_videofile(output_path)

    toast_label.destroy()
    re_start(new_frame)


def ocr_pdf(infile, output_path_pre):
    output_path = output_path_pre + '.pdf'
    try:
        ocrmypdf.ocr(input_file=infile, output_file=output_path, deskew=True)
    except Exception as e:
        try:
            password = get_password()
            if password:
                ocrmypdf.ocr(input_file=infile, output_file=output_path, userpw=password)
        except Exception as e:
            show_toast("Incorrect password or another error occurred...", duration=2000, color="red", mode=0)


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
        supported_formats.extend(["mp3", "wav", "ogg", "flac", "aac"])
    elif is_graph(f_ext):
        supported_formats.extend(["png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp", "ico"])
    elif is_vid(f_ext):
        supported_formats.extend(["mp4", "mp3", "wav", "webm", ])
    elif is_pdf(f_ext):
        supported_formats.extend(["docx", "OcrPdf"]) #"OcrPdfAndDocx"
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


def is_admin():
    return ctypes.windll.shell32.IsUserAnAdmin()


def uninstall_chocolatey():
    print(Fore.BLUE + "\nUninstalling Chocolatey...\n")
    command = 'powershell -Command "Remove-Item -Recurse -Force C:\\ProgramData\\chocolatey"'
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    process.wait()

    print(Fore.BLUE + "\nRemoving Chocolatey from PATH...\n")
    command = ('powershell -Command "[Environment]::SetEnvironmentVariable(\'PATH\', '
               '(([Environment]::GetEnvironmentVariable(\'PATH\', \'Machine\') -split \';\' | Where-Object { $_ '
               '-notmatch \'chocolatey\' }) -join \';\'), \'Machine\')"')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    process.wait()


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

print(Fore.CYAN + "Starting the app...\n")
print(Fore.RESET)
customtkinter.set_appearance_mode("Dark")
customtkinter.set_default_color_theme("dark-blue")

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
