#!/usr/bin/env python3
import argparse
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


def open_desktop_window(url: str, force_tab: bool = False) -> None:
    if not force_tab:
        browser_bin = _find_app_browser()
        if browser_bin:
            try:
                subprocess.Popen(
                    [browser_bin, f"--app={url}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
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
        return

    if not args.no_browser:
        def _open() -> None:
            time.sleep(0.55)
            open_desktop_window(url, force_tab=args.tab)
        threading.Thread(target=_open, daemon=True).start()

    server.run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
