#!/usr/bin/env python3
import argparse
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "workbench"))
import adapters  # noqa: E402
import config    # noqa: E402
import presets   # noqa: E402
import server    # noqa: E402


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


def _is_server_alive(url: str, token: str = "") -> bool:
    try:
        headers = {"X-Workbench-Token": token} if token else {}
        req = urllib.request.Request(f"{url}/api/live", headers=headers)
        with urllib.request.urlopen(req, timeout=0.45) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        # 403 means a Super Workbench server is already listening on this port
        return exc.code == 403
    except Exception:
        return False


def _check_ollama() -> dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=0.8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
            return {"reachable": True, "models": models[:12]}
    except Exception:
        return {"reachable": False, "models": []}


def run_doctor(as_json: bool = False) -> int:
    py_ok = sys.version_info >= (3, 10)
    git_bin = presets.find_git_bin()
    npx_bin = shutil.which("npx") or ""
    browser_bin = _find_app_browser()
    clis = adapters.detect_cli_status(force=True)
    ollama = _check_ollama()
    ready_clis = [k for k, v in clis.items() if v.get("ready")]
    custom_engines = adapters.load_custom_engines()

    recommendations = []
    if not py_ok:
        recommendations.append("Upgrade Python to 3.10+.")
    if not ready_clis and not ollama["reachable"] and not custom_engines:
        recommendations.append(
            "No local AI CLI or Ollama detected yet. Prepare at least ONE of: "
            "(A) Install a local CLI (Codex / Claude Code / Antigravity / Gemini CLI) and sign in, OR "
            "(B) Start local Ollama (http://127.0.0.1:11434), OR "
            "(C) Prepare an OpenAI-compatible API key (DeepSeek / OpenRouter / OpenAI) to add in Settings -> Engines & API."
        )
    elif not any(k in ready_clis for k in ("codex", "claude", "agy", "gemini")):
        recommendations.append(
            "For automated local file editing in the Core Builder role, installing one coding CLI "
            "(e.g. OpenAI Codex, Claude Code, Antigravity, or Gemini CLI) is recommended."
        )
    if not git_bin:
        recommendations.append("Optional: Install Git to unlock Live Git Diff & 1-click AI Commit in the Inspector.")
    if not npx_bin:
        recommendations.append("Optional: Install Node.js (npx) if you plan to use stdio MCP tools like Playwright or GitHub.")

    _, tok_source = config.get_or_create_session_token()
    report = {
        "ok": py_ok,
        "os": f"{platform.system()} {platform.release()}",
        "python": {"version": platform.python_version(), "ok": py_ok},
        "git": {"installed": bool(git_bin), "path": git_bin},
        "npx": {"installed": bool(npx_bin), "path": npx_bin},
        "desktop_browser": {"installed": bool(browser_bin), "path": browser_bin},
        "api_auth": {"enabled": True, "token_source": tok_source},
        "clis": {k: {"ready": bool(v.get("ready")), "path": v.get("path", "")} for k, v in clis.items()},
        "ollama": ollama,
        "custom_engines_count": len(custom_engines),
        "ready_clis": ready_clis,
        "recommendations": recommendations,
    }

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=== Super Workbench Environment Doctor ===")
        print(f"OS      : {report['os']}")
        print(f"Python  : {report['python']['version']} ({'OK' if py_ok else 'NEEDS 3.10+'})")
        print(f"Git     : {'OK (' + git_bin + ')' if git_bin else 'Not found (optional, enables Live Git Diff)'}")
        print(f"npx     : {'OK' if npx_bin else 'Not found (optional, for stdio MCP tools)'}")
        print(f"Desktop : {'OK (' + Path(browser_bin).name + ' --app mode)' if browser_bin else 'Standard browser fallback'}")
        print(f"Auth    : Enabled (session token: {tok_source})")
        print(f"CLIs    : {', '.join(ready_clis) if ready_clis else 'None detected'}")
        print(f"Ollama  : {'Online (' + str(len(ollama['models'])) + ' models)' if ollama['reachable'] else 'Offline / not running'}")
        if recommendations:
            print("\nNext Steps / Preparation:")
            for idx, rec in enumerate(recommendations, 1):
                print(f"  {idx}. {rec}")
        else:
            print("\nAll checks passed! Run `python start.py` to launch Super Workbench.")
    return 0 if py_ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Super Workbench — Local Multi-Agent Orchestration Studio")
    parser.add_argument("--host", default=config.HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=config.PORT, help="Bind port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open window")
    parser.add_argument("--tab", action="store_true", help="Open in a normal browser tab instead of standalone app window")
    parser.add_argument("--doctor", action="store_true", help="Run environment readiness check and exit")
    parser.add_argument("--json", action="store_true", help="Output --doctor report as JSON (for AI agents)")
    args = parser.parse_args()

    if args.doctor:
        raise SystemExit(run_doctor(as_json=args.json))

    url = f"http://{args.host}:{args.port}"
    tok, _ = config.get_or_create_session_token()
    auth_url = f"{url}/?token={tok}"

    # Single-instance check: if server is already running, just pop open the desktop window
    if _is_server_alive(url, tok):
        if not args.no_browser:
            open_desktop_window(auth_url, force_tab=args.tab)
            if os.name == "nt":
                # Keep alive briefly so background Win32 icon thread can finish painting the HWND
                time.sleep(2.2)
        return

    if not args.no_browser:
        def _open() -> None:
            time.sleep(0.55)
            open_desktop_window(auth_url, force_tab=args.tab)
        threading.Thread(target=_open, daemon=True).start()

    server.run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
