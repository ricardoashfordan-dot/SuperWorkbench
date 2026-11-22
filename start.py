#!/usr/bin/env python3
import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "workbench"))
import config  # noqa: E402
import server  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Super Workbench — Local Multi-Agent Orchestration Studio")
    parser.add_argument("--host", default=config.HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=config.PORT, help="Bind port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        def _open() -> None:
            time.sleep(0.7)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    server.run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
