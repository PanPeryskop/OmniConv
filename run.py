import ctypes
import json
import logging
import math
import os
import re
import shutil
import urllib.request
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

try:
    import pystray
    from PIL import Image, ImageDraw, ImageEnhance
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

FROZEN = getattr(sys, 'frozen', False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('OMNICONV_PORT', '5000'))
LOCAL_URL = f'http://127.0.0.1:{PORT}'
ARGS = set(sys.argv[1:])
AUTOSTART = '--autostart' in ARGS
OPEN_BROWSER = not AUTOSTART and '--no-browser' not in ARGS
IS_WINDOWS = sys.platform == 'win32'
CREATE_NO_WINDOW = 0x08000000
LOG_DIR = os.path.join(APP_DIR, 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'omniconv.log')
STARTUP_LNK = os.path.join(
    os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'OmniConv.lnk'
)

TEXTS = {
    'pl': {
        'starting': 'uruchamianie…',
        'updating': 'aktualizacja yt-dlp…',
        'running': 'działa',
        'ytdlp': 'yt-dlp {version}',
        'ytdlp_updated': 'Zaktualizowano yt-dlp do wersji {version}.',
        'error': 'błąd serwera',
        'status': 'OmniConv: {state}',
        'open': 'Otwórz OmniConv',
        'youtube': 'Pobieranie wideo',
        'pdf': 'Narzędzia PDF',
        'outputs': 'Folder z plikami',
        'copy_lan': 'Kopiuj adres w sieci ({url})',
        'autostart': 'Uruchamiaj razem z Windows',
        'logs': 'Pokaż logi',
        'restart': 'Uruchom ponownie',
        'quit': 'Zakończ',
        'tip_starting': 'OmniConv: uruchamianie…',
        'tip_running': 'OmniConv działa: {url}\nKliknij, aby otworzyć',
        'tip_error': 'OmniConv: błąd serwera, zobacz logi',
        'copied': 'Skopiowano {url}',
        'wait': 'OmniConv jeszcze się uruchamia. Otworzę przeglądarkę, gdy będzie gotowy.',
        'autostart_failed': 'Nie udało się zmienić autostartu.',
        'server_failed': 'Serwer nie wystartował. Szczegóły w logach.',
    },
    'en': {
        'starting': 'starting…',
        'updating': 'updating yt-dlp…',
        'running': 'running',
        'ytdlp': 'yt-dlp {version}',
        'ytdlp_updated': 'yt-dlp updated to {version}.',
        'error': 'server error',
        'status': 'OmniConv: {state}',
        'open': 'Open OmniConv',
        'youtube': 'Video downloader',
        'pdf': 'PDF tools',
        'outputs': 'Output folder',
        'copy_lan': 'Copy network address ({url})',
        'autostart': 'Start with Windows',
        'logs': 'Show logs',
        'restart': 'Restart',
        'quit': 'Quit',
        'tip_starting': 'OmniConv: starting…',
        'tip_running': 'OmniConv is running: {url}\nClick to open',
        'tip_error': 'OmniConv: server error, see logs',
        'copied': 'Copied {url}',
        'wait': 'OmniConv is still starting. The browser will open when it is ready.',
        'autostart_failed': 'Could not change the autostart setting.',
        'server_failed': 'The server did not start. See the logs for details.',
    },
}


def detect_language():
    if IS_WINDOWS:
        try:
            return 'pl' if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x15 else 'en'
        except Exception:
            return 'en'
    import locale
    return 'pl' if (locale.getlocale()[0] or '').lower().startswith('pl') else 'en'


LANG = detect_language()


def tr(key, **kwargs):
    return TEXTS[LANG][key].format(**kwargs)


class TeeStream:
    def __init__(self, primary, secondary):
        self.primary = primary
        self.secondary = secondary

    def write(self, data):
        self.primary.write(data)
        if self.secondary is not None:
            try:
                self.secondary.write(data)
            except Exception:
                self.secondary = None
        return len(data)

    def flush(self):
        self.primary.flush()
        if self.secondary is not None:
            try:
                self.secondary.flush()
            except Exception:
                self.secondary = None

    def isatty(self):
        return False

    def fileno(self):
        return self.primary.fileno()


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 5 * 1024 * 1024:
        try:
            os.replace(LOG_FILE, LOG_FILE + '.old')
        except OSError:
            pass
    log_stream = open(LOG_FILE, 'a', encoding='utf-8', buffering=1)
    sys.stdout = TeeStream(log_stream, sys.stdout)
    sys.stderr = TeeStream(log_stream, sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        stream=sys.stderr,
    )


def enable_dpi_awareness():
    if not IS_WINDOWS:
        return
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def port_in_use(port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def wait_until(predicate, timeout, interval=0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def version_tuple(version):
    return tuple(int(part) for part in re.findall(r'\d+', version or ''))


def installed_version(package):
    from importlib import metadata
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def latest_version(package, timeout=4):
    with urllib.request.urlopen(f'https://pypi.org/pypi/{package}/json', timeout=timeout) as response:
        return json.load(response)['info']['version']


def update_yt_dlp():
    if FROZEN or '--no-update' in ARGS or os.environ.get('OMNICONV_NO_UPDATE'):
        return None
    try:
        current = installed_version('yt-dlp')
        latest = latest_version('yt-dlp')
    except Exception as e:
        logging.warning('yt-dlp update check skipped: %s', e)
        return None
    if current and version_tuple(current) >= version_tuple(latest):
        logging.info('yt-dlp %s is up to date', current)
        return None
    logging.info('Updating yt-dlp %s -> %s', current, latest)
    spec = f'yt-dlp[default]=={latest}'
    uv = shutil.which('uv')
    if uv:
        cmd = [uv, 'pip', 'install', '--python', sys.executable, '--quiet', spec]
    else:
        cmd = [sys.executable, '-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', '--quiet', spec]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )
    except Exception as e:
        logging.error('yt-dlp update failed: %s', e)
        return None
    if result.returncode != 0:
        logging.error('yt-dlp update failed: %s', (result.stderr or result.stdout).strip()[-2000:])
        return None
    logging.info('yt-dlp updated to %s', latest)
    return latest


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('10.255.255.255', 1))
            return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'


def open_url(path=''):
    webbrowser.open(LOCAL_URL + path)


def open_path(path):
    if IS_WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(['xdg-open', path])


def copy_to_clipboard(text):
    if IS_WINDOWS:
        subprocess.run(['clip'], input=text.encode('utf-8'), creationflags=CREATE_NO_WINDOW, check=False)


def autostart_enabled():
    return IS_WINDOWS and os.path.exists(STARTUP_LNK)


def set_autostart(enable):
    if not enable:
        if os.path.exists(STARTUP_LNK):
            os.remove(STARTUP_LNK)
        return
    if FROZEN:
        target, arguments = sys.executable, '--autostart'
    else:
        target, arguments = 'wscript.exe', '//nologo "{}" --autostart'.format(os.path.join(APP_DIR, 'start.vbs'))
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:OC_LNK);"
        "$s.TargetPath = $env:OC_TARGET;"
        "$s.Arguments = $env:OC_ARGS;"
        "$s.WorkingDirectory = $env:OC_DIR;"
        "$s.IconLocation = $env:OC_ICON;"
        "$s.Save()"
    )
    env = dict(
        os.environ,
        OC_LNK=STARTUP_LNK,
        OC_TARGET=target,
        OC_ARGS=arguments,
        OC_DIR=APP_DIR,
        OC_ICON=os.path.join(APP_DIR, 'app', 'static', 'ico.ico'),
    )
    subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
        env=env, creationflags=CREATE_NO_WINDOW, check=True, timeout=30,
    )


def render_icon_master(size=1024):
    top, bottom = (167, 139, 250), (99, 102, 241)
    gradient = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(gradient)
    for y in range(size):
        t = y / (size - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        draw.line([(0, y), (size, y)], fill=color)

    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.24), fill=255)
    icon = gradient
    icon.putalpha(mask)

    draw = ImageDraw.Draw(icon)
    cx = cy = size / 2
    radius = size * 0.27
    width = int(size * 0.095)
    head = size * 0.15
    white = (255, 255, 255, 255)
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    for start, end in ((200, 330), (20, 150)):
        draw.arc(box, start=start, end=end, fill=white, width=width)
        a0 = math.radians(start)
        sx = cx + (radius - width / 2) * math.cos(a0)
        sy = cy + (radius - width / 2) * math.sin(a0)
        draw.ellipse([sx - width / 2, sy - width / 2, sx + width / 2, sy + width / 2], fill=white)
        a1 = math.radians(end)
        mid = radius - width / 2
        px, py = cx + mid * math.cos(a1), cy + mid * math.sin(a1)
        tx, ty = -math.sin(a1), math.cos(a1)
        nx, ny = math.cos(a1), math.sin(a1)
        tip = (px + tx * head * 0.95, py + ty * head * 0.95)
        left = (px + nx * head * 0.75 - tx * head * 0.15, py + ny * head * 0.75 - ty * head * 0.15)
        right = (px - nx * head * 0.75 - tx * head * 0.15, py - ny * head * 0.75 - ty * head * 0.15)
        draw.polygon([tip, left, right], fill=white)
    return icon


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def build_frames(master, dimmed):
    source = master
    if dimmed:
        rgb = ImageEnhance.Color(master).enhance(0.1)
        rgb = ImageEnhance.Brightness(rgb).enhance(0.85)
        rgb.putalpha(master.getchannel('A'))
        source = rgb
    return {s: source.resize((s, s), Image.Resampling.LANCZOS) for s in ICON_SIZES}


if TRAY_AVAILABLE:
    class TrayIcon(pystray.Icon):
        frames = None

        def _assert_icon_handle(self):
            if not IS_WINDOWS or not self.frames:
                return super()._assert_icon_handle()
            if self._icon_handle:
                return
            load_image = ctypes.WINFUNCTYPE(
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint
            )(('LoadImageW', ctypes.windll.user32))
            size = ctypes.windll.user32.GetSystemMetrics(49) or 16
            fd, path = tempfile.mkstemp(suffix='.ico')
            os.close(fd)
            try:
                base = self.frames[256]
                base.save(
                    path, format='ICO',
                    sizes=[(s, s) for s in ICON_SIZES],
                    append_images=[self.frames[s] for s in ICON_SIZES if s != 256],
                )
                self._icon_handle = load_image(None, path, 1, size, size, 0x10)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass


class TrayApp:
    def __init__(self, local_ip):
        self.app = None
        self.local_ip = local_ip
        self.lan_url = f'http://{local_ip}:{PORT}'
        self.state = 'starting'
        self.ytdlp_version = installed_version('yt-dlp') or '?'
        self.open_when_ready = OPEN_BROWSER
        master = render_icon_master()
        self.frames_ready = build_frames(master, dimmed=False)
        self.frames_dimmed = build_frames(master, dimmed=True)
        self.icon = TrayIcon('OmniConv', self.frames_dimmed[256], tr('tip_starting'), menu=self.build_menu())
        self.icon.frames = self.frames_dimmed

    def build_menu(self):
        Item = pystray.MenuItem
        return pystray.Menu(
            Item(lambda item: tr('status', state=tr(self.state)), None, enabled=False),
            Item(lambda item: tr('ytdlp', version=self.ytdlp_version), None, enabled=False),
            pystray.Menu.SEPARATOR,
            Item(tr('open'), self.open_home, default=True),
            Item(tr('youtube'), lambda: self.open_page('/youtube')),
            Item(tr('pdf'), lambda: self.open_page('/pdf')),
            pystray.Menu.SEPARATOR,
            Item(tr('outputs'), self.open_outputs),
            Item(tr('copy_lan', url=self.lan_url), self.copy_lan, visible=not self.lan_url.startswith('http://127.')),
            pystray.Menu.SEPARATOR,
            Item(tr('autostart'), self.toggle_autostart, checked=lambda item: autostart_enabled(), visible=IS_WINDOWS),
            Item(tr('logs'), self.open_logs),
            Item(tr('restart'), self.restart),
            Item(tr('quit'), self.quit),
        )

    def set_state(self, state):
        self.state = state
        frames = self.frames_ready if state == 'running' else self.frames_dimmed
        self.icon.frames = frames
        self.icon.icon = frames[256]
        self.icon.title = {
            'running': tr('tip_running', url=LOCAL_URL),
            'error': tr('tip_error'),
        }.get(state, tr('tip_starting'))
        self.icon.update_menu()

    def notify(self, message):
        try:
            self.icon.notify(message, 'OmniConv')
        except Exception:
            logging.debug('Notification failed', exc_info=True)

    def open_page(self, path):
        if self.state == 'running':
            open_url(path)
        else:
            self.open_when_ready = True
            self.notify(tr('wait'))

    def open_home(self):
        self.open_page('')

    def open_outputs(self):
        folder = str(self.app.config['OUTPUT_FOLDER']) if self.app else os.path.join(APP_DIR, 'outputs')
        os.makedirs(folder, exist_ok=True)
        open_path(folder)

    def open_logs(self):
        open_path(LOG_FILE if os.path.exists(LOG_FILE) else LOG_DIR)

    def copy_lan(self):
        copy_to_clipboard(self.lan_url)
        self.notify(tr('copied', url=self.lan_url))

    def toggle_autostart(self):
        try:
            set_autostart(not autostart_enabled())
        except Exception:
            logging.exception('Autostart change failed')
            self.notify(tr('autostart_failed'))
        self.icon.update_menu()

    def restart(self):
        if FROZEN:
            cmd = [sys.executable, '--wait-port', '--no-browser']
        else:
            cmd = [sys.executable, os.path.abspath(__file__), '--wait-port', '--no-browser']
        subprocess.Popen(cmd, cwd=APP_DIR, creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0, close_fds=True)
        self.quit()

    def quit(self):
        try:
            self.icon.visible = False
            self.icon.stop()
        finally:
            os._exit(0)

    def fail(self):
        if self.state != 'error':
            self.set_state('error')
            self.notify(tr('server_failed'))

    def watch_startup(self):
        if wait_until(port_in_use, timeout=120):
            self.set_state('running')
            if self.open_when_ready:
                self.open_when_ready = False
                open_url()
        else:
            self.fail()

    def boot(self, icon):
        icon.visible = True
        self.set_state('updating')
        updated = update_yt_dlp()
        if updated:
            self.ytdlp_version = updated
            self.notify(tr('ytdlp_updated', version=updated))
        self.set_state('starting')
        try:
            self.app = create_application(self.local_ip)
        except Exception:
            logging.exception('App initialisation failed')
            self.fail()
            return
        threading.Thread(target=self.watch_startup, daemon=True, name='startup-watch').start()
        try:
            run_server(self.app)
        except Exception:
            logging.exception('Server crashed')
        self.fail()

    def run(self):
        self.icon.run(setup=self.boot)


def create_application(local_ip):
    from app import create_app
    app = create_app()
    app.config['LOCAL_IP'] = local_ip
    print('\n=======================================================')
    print('OmniConv is running!')
    print(f'Local:   {LOCAL_URL}')
    print(f'Network: http://{local_ip}:{PORT}')
    print('=======================================================\n', flush=True)
    return app


def run_server(app):
    app.socketio.run(app, host='0.0.0.0', port=PORT, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)


def main():
    setup_logging()
    enable_dpi_awareness()

    if port_in_use():
        if '--wait-port' in ARGS:
            wait_until(lambda: not port_in_use(), timeout=20)
        if port_in_use():
            logging.info('OmniConv is already running on port %s', PORT)
            if OPEN_BROWSER:
                open_url()
            return

    local_ip = get_local_ip()

    if TRAY_AVAILABLE:
        TrayApp(local_ip).run()
        return

    update_yt_dlp()
    app = create_application(local_ip)
    if OPEN_BROWSER:
        threading.Thread(
            target=lambda: wait_until(port_in_use, timeout=120) and open_url(), daemon=True
        ).start()
    run_server(app)


if __name__ == '__main__':
    main()
