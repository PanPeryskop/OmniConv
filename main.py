import time

import customtkinter
import os
import customtkinter as tk
import subprocess
import ctypes

from pydub import AudioSegment
from PIL import Image
from customtkinter import filedialog
from pathlib import Path
from pdf2docx import Converter as pdf2docx
import threading
from moviepy.editor import VideoFileClip
from moviepy.editor import AudioFileClip


# def segment
def re_start(new_frame):
    new_frame.destroy()

    show_toast("Conversion has been completed ", duration=2000, color="Green", mode=1)
    app.after(2000, lambda: restart_after_toast(new_frame))


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


def restart_after_toast(new_frame):
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
        image.save(output_path)

    elif is_pdf(f_ext):
        try:
            pdf_file = infile
            cv = pdf2docx(pdf_file)
            docx_file = output_path
            cv.convert(docx_file, start=0, end=None)
            cv.close()
        except Exception as e:
            password = get_password()
            if password:
                try:
                    cv = pdf2docx(pdf_file=infile, password=password)
                    cv.convert(pdf_file=infile, docx_file=output_path, start=0, end=None)
                    cv.close()
                except Exception as e:
                    show_toast("Incorrect password or another error occurred...", duration=2000, color="red", mode=0)

    else:
        if is_audio(f_format):
            audio = AudioFileClip(infile)
            audio.write_audiofile(output_path)
        else:
            video = VideoFileClip(infile)
            video.write_videofile(output_path)

    toast_label.destroy()
    re_start(new_frame)


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
        supported_formats.extend(["docx"])
    else:
        supported_formats = 0

    if supported_formats:
        if f_ext.lower() in supported_formats:
            supported_formats.remove(f_ext.lower())

    return supported_formats


def check_ffmpeg():
    try:
        subprocess.call('ffmpeg', creationflags=subprocess.CREATE_NEW_CONSOLE)
        print("Ffmpeg is installed\nStarting the app...\n")
    except FileNotFoundError:
        if not is_admin():
            print("This script must be run as administrator. Please restart the script with administrative privileges.")
            time.sleep(10)
            exit()
        print("ffmpeg is not installed\nSearching for Chocolatey...\n")
        is_choco = 0
        check_chocolatey(is_choco)
        install_ffmpeg(is_choco)


def check_chocolatey(is_choco):
    try:
        subprocess.call('choco', creationflags=subprocess.CREATE_NEW_CONSOLE)
        print("Chocolatey is installed")
    except FileNotFoundError:
        print("Chocolatey is not installed")
        is_choco = 1
        install_chocolatey()


def install_chocolatey():
    print("Installing Chocolatey...")
    command = ('powershell -Command "Set-ExecutionPolicy Bypass -Scope Process -Force; ['
               'System.Net.ServicePointManager]::SecurityProtocol = ['
               'System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object '
               'System.Net.WebClient).DownloadString(\'https://chocolatey.org/install.ps1\'))"')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    process.wait()


def install_ffmpeg(is_choco):
    print("Installing ffmpeg...")
    command = 'choco install ffmpeg -y'
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print(f"Error occurred while installing ffmpeg: {stderr.decode()}")
        else:
            print("ffmpeg installed successfully.")
        if is_choco:
            uninstall_chocolatey()
    except Exception as e:
        print(f"An error occurred while trying to run the command: {e}")


def is_admin():
    return ctypes.windll.shell32.IsUserAnAdmin()


def uninstall_chocolatey():
    print("\nUninstalling Chocolatey...\n")
    command = 'powershell -Command "Remove-Item -Recurse -Force C:\\ProgramData\\chocolatey"'
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    process.wait()

    print("\nRemoving Chocolatey from PATH...\n")
    command = ('powershell -Command "[Environment]::SetEnvironmentVariable(\'PATH\', '
               '(([Environment]::GetEnvironmentVariable(\'PATH\', \'Machine\') -split \';\' | Where-Object { $_ '
               '-notmatch \'chocolatey\' }) -join \';\'), \'Machine\')"')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    process.wait()


# code segment


check_ffmpeg()

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
