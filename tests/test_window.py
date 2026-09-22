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


def test_window_storage_path_is_absolute(tmp_path, monkeypatch):
    """Found by the player: the build list and terminal stayed blank for minutes
    at start. `wt serve` passes builds/ as a relative path, and Qt WebEngine
    stalls the page when its storage path is relative."""
    import sys
    import types
    from pathlib import Path
    from wynntools.web import window
    seen = {}

    class Events:
        def __getattr__(self, name):
            return self

        def __iadd__(self, fn):
            return self

    fake = types.SimpleNamespace(
        create_window=lambda *a, **k: types.SimpleNamespace(events=Events(), width=1, height=1,
                                                            x=0, y=0),
        start=lambda **k: seen.update(k))
    monkeypatch.setitem(sys.modules, "webview", fake)
    (tmp_path / "builds").mkdir()
    monkeypatch.chdir(tmp_path)
    window.run("http://x", Path("builds") / "settings.json", on_close=lambda: None)
    assert Path(seen["storage_path"]).is_absolute()
    assert Path(seen["storage_path"]) == (tmp_path / "builds" / ".webview").resolve()
