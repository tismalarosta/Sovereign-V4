"""
Native macOS window via PyWebView.
Opens the Regis dashboard in a native webkit window.
Call open_window() after the server is confirmed listening.
"""

import webview  # type: ignore[import]

WINDOW_TITLE = "Regis"
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
SERVER_URL = "http://localhost:8765/dashboard"


def open_window() -> None:
    """
    Open the Regis native window. Blocks until the window is closed.
    Must be called from the main thread on macOS.
    """
    webview.create_window(
        WINDOW_TITLE,
        SERVER_URL,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        resizable=True,
        text_select=True,
    )
    webview.start()
