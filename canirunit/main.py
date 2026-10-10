from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from canirunit.api.app import create_app
from canirunit.hardware.base import get_detector
from canirunit.hardware.mock import available_profiles


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="canirunit", description="Can my PC/handheld run this game?")
    p.add_argument(
        "--mock-hardware",
        metavar="PROFILE",
        help="Use a JSON hardware profile instead of scanning. "
        f"Bundled: {', '.join(available_profiles())}",
    )
    p.add_argument("--port", type=int, default=0, help="Server port (default: random free port)")
    p.add_argument(
        "--browser", action="store_true", help="Open in the default browser, not a native window"
    )
    p.add_argument("--no-ui", action="store_true", help="Serve the API only (no window/browser)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        detector = get_detector(args.mock_hardware)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    port = args.port or _free_port()
    url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(create_app(detector), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    print(f"CanIRunIt running at {url}")

    if args.no_ui:
        thread.join()
        return 0
    if not args.browser:
        try:
            import webview  # Windows (WebView2); optional elsewhere

            webview.create_window("CanIRunIt", url, width=1280, height=800)
            webview.start()
            server.should_exit = True
            return 0
        except ImportError:
            print("pywebview not available; opening default browser instead.")
    webbrowser.open(url)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
