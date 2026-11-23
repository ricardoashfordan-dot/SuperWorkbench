#!/usr/bin/env python3
import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "workbench"))
import config  # noqa: E402
import server  # noqa: E402


def _find_app_browser() -> str:
    """Locate an installed Chromium/Edge browser capable of --app=<url> standalone window mode."""
    if os.name == "nt":
        candidates = [
            shutil.which("msedge"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            shutil.which("chrome"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
    else:
        candidates = [
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("microsoft-edge"),
        ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return ""


def _apply_win32_window_icon(ico_path: Path) -> None:
    """Apply icon.ico directly to the Super Workbench HWND (both titlebar and Windows taskbar)."""
    if os.name != "nt" or not ico_path.exists():
        return
    try:
        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        GCLP_HICON = -14
        GCLP_HICONSM = -34

        hicon_big = user32.LoadImageW(0, str(ico_path), IMAGE_ICON, 64, 64, LR_LOADFROMFILE)
        hicon_small = user32.LoadImageW(0, str(ico_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if not hicon_big and not hicon_small:
            return

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        set_class_ptr = getattr(user32, "SetClassLongPtrW", getattr(user32, "SetClassLongW", None))

        # Poll up to ~4.5 seconds while the --app window is opening
        for _ in range(18):
            matched = []

            def _cb(hwnd, _lparam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        if "Super Workbench" in buf.value:
                            matched.append(hwnd)
                return True

            user32.EnumWindows(WNDENUMPROC(_cb), 0)
            if matched:
                for hwnd in matched:
                    if hicon_small:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
                    if hicon_big:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
                    if set_class_ptr:
                        try:
                            if hicon_big:
                                set_class_ptr(hwnd, GCLP_HICON, hicon_big)
                            if hicon_small:
                                set_class_ptr(hwnd, GCLP_HICONSM, hicon_small)
                        except Exception:
                            pass
                time.sleep(0.6)
                # Apply once more after Chromium finishes page favicon load
                for hwnd in matched:
                    if hicon_small:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
                    if hicon_big:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
                return
            time.sleep(0.25)
    except Exception:
        pass


def open_desktop_window(url: str, force_tab: bool = False) -> None:
    if not force_tab:
        browser_bin = _find_app_browser()
        if browser_bin:
            try:
                config.ensure_data_dir()
                profile_dir = config.DATA_DIR / "desktop_app_profile"
                profile_dir.mkdir(parents=True, exist_ok=True)
                cmd = [
                    browser_bin,
                    f"--app={url}",
                    f"--user-data-dir={profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ]
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=config.NO_WINDOW_FLAGS,
                )
                ico_path = config.STATIC_DIR / "icon.ico"
                threading.Thread(target=_apply_win32_window_icon, args=(ico_path,), daemon=True).start()
                return
            except OSError:
                pass
    webbrowser.open(url)


def _is_server_alive(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/live", timeout=0.45) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Super Workbench — Local Multi-Agent Orchestration Studio")
    parser.add_argument("--host", default=config.HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=config.PORT, help="Bind port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open window")
    parser.add_argument("--tab", action="store_true", help="Open in a normal browser tab instead of standalone app window")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    # Single-instance check: if server is already running, just pop open the desktop window
    if _is_server_alive(url):
        if not args.no_browser:
            open_desktop_window(url, force_tab=args.tab)
            if os.name == "nt":
                # Keep alive briefly so background Win32 icon thread can finish painting the HWND
                time.sleep(2.2)
        return

    if not args.no_browser:
        def _open() -> None:
            time.sleep(0.55)
            open_desktop_window(url, force_tab=args.tab)
        threading.Thread(target=_open, daemon=True).start()

    server.run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
