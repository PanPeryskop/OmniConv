import webbrowser
import threading
import os
import sys
from app import create_app

try:
    from pystray import Icon, Menu, MenuItem
    from PIL import Image
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

app = create_app()

def get_icon_path():
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'app', 'static', 'ico.ico')

def open_browser():
    webbrowser.open('http://localhost:5000')

def quit_app(icon=None):
    if icon:
        icon.stop()
    os._exit(0)

def create_tray_icon():
    if not TRAY_AVAILABLE:
        return None
    
    icon_path = get_icon_path()
    try:
        image = Image.open(icon_path)
    except:
        image = Image.new('RGB', (64, 64), color='#4a90d9')
    
    menu = Menu(
        MenuItem('🌐 Open Browser', lambda: open_browser()),
        MenuItem('❌ Quit OmniConv', lambda: quit_app(icon))
    )
    
    icon = Icon('OmniConv', image, 'OmniConv - Running', menu)
    return icon

if __name__ == '__main__':
    threading.Timer(1.5, open_browser).start()
    
    if TRAY_AVAILABLE:
        icon = create_tray_icon()
        server_thread = threading.Thread(
            target=lambda: app.run(host='127.0.0.1', port=5000, debug=False, threaded=True),
            daemon=True
        )
        server_thread.start()
        icon.run()
    else:
        app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)

