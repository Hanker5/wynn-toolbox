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


def test_offscreen_saved_position_is_recentered(tmp_path, monkeypatch):
    """A saved window position from a monitor that's since been disconnected
    (e.g. -1920, 0 from an unplugged second display) must not be reused: the
    window would open where nothing can see or reach it. Fall back to
    pywebview's own centering (x=y=None) instead."""
    import json
    import sys
    import types
    from pathlib import Path
    from wynntools.web import window
    created = {}

    class Events:
        def __getattr__(self, name):
            return self

        def __iadd__(self, fn):
            return self

    fake = types.SimpleNamespace(
        screens=[types.SimpleNamespace(x=0, y=0, width=1707, height=1067)],
        create_window=lambda *a, **k: created.update(k) or
            types.SimpleNamespace(events=Events(), width=1, height=1, x=0, y=0),
        start=lambda **k: None)
    monkeypatch.setitem(sys.modules, "webview", fake)
    (tmp_path / "builds").mkdir()
    (tmp_path / "builds" / "settings.json").write_text(json.dumps(
        {"window": {"width": 1694, "height": 1004, "x": -1920, "y": 0, "maximized": False}}))
    monkeypatch.chdir(tmp_path)
    window.run("http://x", Path("builds") / "settings.json", on_close=lambda: None)
    assert created["x"] is None and created["y"] is None
    assert created["width"] == 1694 and created["height"] == 1004


def test_onscreen_saved_position_is_kept(tmp_path, monkeypatch):
    """A saved position that's still on a connected screen must be reused as-is."""
    import json
    import sys
    import types
    from pathlib import Path
    from wynntools.web import window
    created = {}

    class Events:
        def __getattr__(self, name):
            return self

        def __iadd__(self, fn):
            return self

    fake = types.SimpleNamespace(
        screens=[types.SimpleNamespace(x=0, y=0, width=1707, height=1067)],
        create_window=lambda *a, **k: created.update(k) or
            types.SimpleNamespace(events=Events(), width=1, height=1, x=0, y=0),
        start=lambda **k: None)
    monkeypatch.setitem(sys.modules, "webview", fake)
    (tmp_path / "builds").mkdir()
    (tmp_path / "builds" / "settings.json").write_text(json.dumps(
        {"window": {"width": 1200, "height": 800, "x": 100, "y": 50, "maximized": False}}))
    monkeypatch.chdir(tmp_path)
    window.run("http://x", Path("builds") / "settings.json", on_close=lambda: None)
    assert created["x"] == 100 and created["y"] == 50
