"""The app window's Python side (wynntools/web/window.py), without a display."""
import threading

import pytest


def test_qt_calls_run_on_the_gui_thread(monkeypatch):
    """Found by the player: moving and resizing the window did nothing. The
    page's calls arrive on worker threads, and the hand-off to Qt's GUI thread
    ran them on the worker instead, where Qt ignores window moves."""
    pytest.importorskip("qtpy")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from qtpy.QtCore import QThread
    from qtpy.QtWidgets import QApplication
    from wynntools.web.window import _QtCalls
    qt = QApplication.instance() or QApplication([])
    ran, keep = [], []

    def worker():                       # like a js_api call: made and used off the GUI thread
        keep.append(_QtCalls())         # WindowApi keeps it, as here
        keep[0](lambda: ran.append(QThread.currentThread() == qt.thread()))
    t = threading.Thread(target=worker)
    t.start(); t.join()
    for _ in range(50):
        qt.processEvents()
        if ran:
            break
    assert ran == [True]
