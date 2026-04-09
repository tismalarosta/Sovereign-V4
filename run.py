"""
run.py — Start Regis server and open the native macOS window.

Usage:
    ./venv/bin/python run.py

Behaviour:
- If port 8765 is already listening: just open the window (no second server).
- Otherwise: start uvicorn in a background daemon thread, wait until it's up,
  then open the PyWebView window on the main thread (required on macOS).

The server thread is daemonised so it exits automatically when the window closes.
"""

import socket
import sys
import threading
import time

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765
STARTUP_TIMEOUT = 30  # seconds to wait for server to become ready


def _port_open() -> bool:
    """Return True if something is already listening on the server port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((SERVER_HOST, SERVER_PORT)) == 0


def _start_server() -> None:
    """Run uvicorn in the current thread. Called from a daemon thread."""
    import uvicorn
    config = uvicorn.Config(
        "app.main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    server.run()


def main() -> None:
    if not _port_open():
        print(f"Starting Regis server on {SERVER_HOST}:{SERVER_PORT}…")
        t = threading.Thread(target=_start_server, daemon=True, name="regis-server")
        t.start()

        # Wait until the server is accepting connections
        for i in range(STARTUP_TIMEOUT):
            if _port_open():
                print(f"Server ready ({i + 1}s)")
                break
            time.sleep(1)
        else:
            print(f"ERROR: server did not start within {STARTUP_TIMEOUT}s", file=sys.stderr)
            sys.exit(1)
    else:
        print("Server already running — attaching window.")

    # PyWebView must run on the main thread on macOS
    from app.window import open_window
    open_window()


if __name__ == "__main__":
    main()
